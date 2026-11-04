# argparse는 명령 입력, json은 메시지 변환, sqlite3는 파일 기반 원본 저장에 사용한다.
import argparse
import json
import os
import sqlite3
from contextlib import closing  # sqlite 연결을 블록 종료 시 실제로 닫는다.

import redis
from dotenv import load_dotenv

DEMO_USERS = {"demo-a": "민수", "demo-b": "지연"}
CACHE_TTL = 60  # 캐시의 수명(초). 원본 DB의 수명과 다르다.
MAX_MESSAGES = 6  # 원본 전체 중 최근 여섯 메시지만 캐시·문맥에 사용한다.


def read_settings():
    # 현재 폴더의 .env를 읽되 기존 환경변수와 특수문자 원문을 보존한다.
    load_dotenv(".env", override=False, interpolate=False)
    host = os.getenv("REDIS_HOST", "")
    port_text = os.getenv("REDIS_PORT", "")
    db_path = os.getenv("SQLITE_PATH", "")
    if not host.strip() or not port_text.strip() or not db_path.strip():
        raise ValueError("REDIS_HOST, REDIS_PORT, SQLITE_PATH의 필수값을 확인하세요.")
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError("REDIS_PORT는 1~65535 범위의 정수여야 합니다.") from None
    if not 1 <= port <= 65535:
        raise ValueError("REDIS_PORT는 1~65535 범위의 정수여야 합니다.")
    return host, port, db_path


def initialize(conn):
    # SQL은 main.py에 직접 둔다. AUTOINCREMENT는 삭제된 최대 ID의 재사용도 방지한다.
    with conn:  # 정상 종료 시 COMMIT, 쓰기 중 예외 시 ROLLBACK한다. 연결 종료는 하지 않는다.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL
            )
        """)
        if conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0:
            # executemany의 ?에는 각 튜플 값을 바인딩한다. SQL 문자열을 이어 붙이지 않는다.
            conn.executemany(
                "INSERT INTO messages (owner, role, content) VALUES (?, ?, ?)",
                [
                    ("demo-a", "user", "내 이름은 민수"),
                    ("demo-a", "assistant", "모의 응답: 내 이름은 민수"),
                    ("demo-b", "user", "내 이름은 지연"),
                    ("demo-b", "assistant", "모의 응답: 내 이름은 지연"),
                ],
            )
    print("원본 준비 완료: 기존 데이터가 있으면 유지합니다.")


def read_source(conn, owner):
    # owner는 사용자 구분, LIMIT은 최근 개수다. DESC로 최신 항목을 고른다.
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE owner = ? ORDER BY id DESC LIMIT ?",
        (owner, MAX_MESSAGES),
    ).fetchall()
    # 모델에는 과거→현재 순서가 필요하므로 조회 결과를 다시 뒤집는다.
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def decode_history(raw):
    try:
        messages = json.loads(raw)  # JSON 문자열을 Python 목록으로 되돌린다.
    except json.JSONDecodeError:
        raise ValueError("캐시의 JSON 형식을 확인하세요.") from None
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        raise ValueError("캐시의 메시지 목록 형식을 확인하세요.")
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in ("user", "assistant")
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError("캐시의 role/content 형식을 확인하세요.")
    return messages


def cache_key(conn, owner):
    # 원본의 최신 ID를 버전으로 사용한다. 이 작은 SQL 조회는 HIT일 때도 실행한다.
    version = conn.execute(
        "SELECT COALESCE(MAX(id), 0) FROM messages WHERE owner = ?", (owner,),
    ).fetchone()[0]
    return f"lesson06:history:{owner}:v{version}"

def load_history(conn, client, owner):
    key = cache_key(conn, owner)
    raw = client.get(key)
    if raw is not None:  # 빈 목록을 담은 문자열 "[]"도 유효한 HIT다.
        return decode_history(raw), "HIT"
    messages = read_source(conn, owner)
    # ensure_ascii=False는 한글을 읽기 쉬운 문자로 저장한다. ex는 초 단위 만료다.
    client.set(key, json.dumps(messages, ensure_ascii=False), ex=CACHE_TTL)
    return messages, "MISS"

def save_turn(conn, owner, text, reply):
    # 한 턴의 두 메시지를 같은 sqlite 트랜잭션에 넣는다. 둘째 INSERT 실패 시 모두 취소된다.
    with conn:
        conn.executemany(
            "INSERT INTO messages (owner, role, content) VALUES (?, ?, ?)",
            [(owner, "user", text), (owner, "assistant", reply)],
        )
    print("원본 저장 완료: 2개 메시지")


def invalidate(client, key):
    print("이전 캐시 삭제 수:", client.delete(key))  # 원본 COMMIT 이후에만 호출한다.

def show_history(messages, source):
    print("조회 경로:", source)
    if not messages:
        print("대화 이력이 없습니다.")
    for index, message in enumerate(messages, start=1):  # 표시 번호만 1부터 시작한다.
        print(f"{index}. {message['role']}: {message['content']}")

def main():
    parser = argparse.ArgumentParser(description="원본 저장 후 버전으로 캐시 갱신")
    parser.add_argument("command", choices=['init', 'history', 'add', 'evict'], help="실행할 동작")
    # init에는 value가 없으므로 ?로 생략을 허용한다. 명령별 필수 여부는 아래에서 검사한다.
    parser.add_argument("value", nargs="?", default="", help="가상 사용자 ID")
    parser.add_argument("text", nargs="?", default="", help="add에서만 사용하는 메시지")
    args = parser.parse_args()
    if args.command == "init":
        if args.value or args.text:
            raise ValueError("init에는 추가 인자를 넣지 마세요.")
    elif not args.value.strip():
        raise ValueError("이 명령에는 사용자 ID가 필요합니다.")
    if args.command == "add" and not args.text.strip():
        raise ValueError("메시지는 공백이 아닌 문자열이어야 합니다.")
    if args.command != "add" and args.text:
        raise ValueError("메시지는 add 명령에서만 사용하세요.")
    host, port, db_path = read_settings()
    if args.command != "init" and not os.path.isfile(db_path):
        raise ValueError("원본 DB가 없습니다. 현재 폴더와 SQLITE_PATH를 확인하고 init을 실행하세요.")
    # timeout=5는 sqlite 쓰기 잠금 대기 한도(초)다. closing은 연결 종료를 담당한다.
    with closing(sqlite3.connect(db_path, timeout=5)) as conn:
        if args.command == "init":
            initialize(conn)  # Redis가 꺼져 있어도 원본 초기화는 가능하다.
            return
        # 객체 생성 시 연결 성공을 단정하지 않는다. 필요한 명령이 실제 연결을 수행한다.
        with redis.Redis(
            host=host,                 # 환경설정의 Redis 주소
            port=port,                 # PC에 공개한 포트
            decode_responses=True,     # True: str 응답, 기본 False: bytes 응답
            socket_connect_timeout=1,  # 연결 단계 제한(초), 기본 5초 대신 짧게 확인
            socket_timeout=1,          # 소켓 읽기/쓰기 제한(초), 전체 실행시간 제한은 아님
        ) as client:
            if args.value not in DEMO_USERS:
                raise ValueError("demo-a 또는 demo-b를 사용하세요.")
            owner = args.value
            if args.command == "history":
                messages, source = load_history(conn, client, owner)
                show_history(messages, source)
            elif args.command == "evict":
                print("삭제한 캐시 수:", client.delete(cache_key(conn, owner)))
            else:  # add: 캐시가 아니라 원본에 한 턴을 먼저 저장한다.
                old_key = cache_key(conn, owner)
                save_turn(conn, owner, args.text, f"모의 응답: {args.text}")
                invalidate(client, old_key)



if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print("입력/접근/설정 오류:", exc)  # 직접 만든 고정 메시지이며 설정값은 출력하지 않는다.
        raise SystemExit(1)
    except redis.exceptions.RedisError as exc:
        print("Redis 오류:", type(exc).__name__)
        print("서버 상태를 확인하세요. 앞서 원본 저장 완료가 출력됐다면 저장은 반영되었습니다.")
        raise SystemExit(1)
    except sqlite3.Error as exc:
        print("원본 DB 오류:", type(exc).__name__)
        print("DB 경로·권한·init 실행 여부를 확인하세요. 원본 오류는 캐시로 숨기지 않습니다.")
        raise SystemExit(1)