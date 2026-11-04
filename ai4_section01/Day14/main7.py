# argparse는 명령 입력, json은 메시지 변환, sqlite3는 파일 기반 원본 저장에 사용한다.
import argparse
import json
import os
import sqlite3
from contextlib import closing  # sqlite 연결을 블록 종료 시 실제로 닫는다.
import secrets  # 가상 세션 ID를 생성한다.

import redis
from dotenv import load_dotenv

DEMO_USERS = {"demo-a": "민수", "demo-b": "지연"}
CACHE_TTL = 60  # 캐시의 수명(초). 원본 DB의 수명과 다르다.
MAX_MESSAGES = 6  # 원본 전체 중 최근 여섯 메시지만 캐시·문맥에 사용한다.
SESSION_TTL = 300  # 세션은 생성 후 5분 고정 만료다.


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
    return f"lesson07:history:{owner}:v{version}"

def load_history(conn, client, owner):
    key = cache_key(conn, owner)
    try:
        raw = client.get(key)
    except redis.exceptions.RedisError as exc:
        # 이력 캐시는 사본이다. 읽지 못하면 원본으로 대체하되 원본 오류는 숨기지 않는다.
        print("캐시 읽기 실패:", type(exc).__name__, "→ sqlite 원본 사용")
        return read_source(conn, owner), "BYPASS"
    if raw is not None:
        try:
            return decode_history(raw), "HIT"
        except ValueError:
            print("캐시 형식 오류 → sqlite 원본으로 교체")
    messages = read_source(conn, owner)
    try:
        # 캐시 저장 실패와 원본 조회 실패를 구분한다. JSON 한글은 그대로 유지한다.
        client.set(key, json.dumps(messages, ensure_ascii=False), ex=CACHE_TTL)
    except redis.exceptions.RedisError as exc:
        print("캐시 저장 실패:", type(exc).__name__, "→ 원본 조회 결과 반환")
        return messages, "MISS_WRITE_FAILED"
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
    try:
        print("이전 캐시 삭제 수:", client.delete(key))
    except redis.exceptions.RedisError as exc:
        # 원본 저장은 이미 성공했다. 새 버전 키를 사용하므로 이전 캐시를 재사용하지 않는다.
        print("이전 캐시 삭제 실패:", type(exc).__name__, "→ 새 버전 키로 구분")

def show_history(messages, source):
    print("조회 경로:", source)
    if not messages:
        print("대화 이력이 없습니다.")
    for index, message in enumerate(messages, start=1):  # 표시 번호만 1부터 시작한다.
        print(f"{index}. {message['role']}: {message['content']}")

def create_session(client, owner):
    if owner not in DEMO_USERS:
        raise ValueError("create에는 demo-a 또는 demo-b를 사용하세요.")
    # sid_는 난수가 -로 시작해 CLI 옵션으로 오인되는 것을 방지한다. 32는 난수 바이트 수다.
    session_id = "sid_" + secrets.token_urlsafe(32)
    client.set(f"lesson07:session:{session_id}", owner, ex=SESSION_TTL)
    print("SESSION_ID:", session_id)  # 가상 로컬 실습에서 다음 명령에 전달하기 위한 출력
    print("세션 사용자:", DEMO_USERS[owner])


def require_session(client, session_id):
    try:
        owner = client.get(f"lesson07:session:{session_id}")
    except redis.exceptions.RedisError:
        # 세션을 확인할 수 없는데 캐시 조회처럼 성공으로 대체해서는 안 된다.
        raise PermissionError("세션 확인 불가: Redis 장애이므로 접근을 거절합니다.") from None
    if owner not in DEMO_USERS:
        raise PermissionError("세션이 없거나 만료되어 접근을 거절합니다.")
    return owner

def main():
    parser = argparse.ArgumentParser(description="캐시 장애 대체와 세션 접근 거절")
    parser.add_argument("command", choices=['init', 'history', 'add', 'evict', 'create', 'session'], help="실행할 동작")
    # init에는 value가 없으므로 ?로 생략을 허용한다. 명령별 필수 여부는 아래에서 검사한다.
    parser.add_argument("value", nargs="?", default="", help="가상 사용자 또는 세션 ID")
    parser.add_argument("text", nargs="?", default="", help="add에서만 사용하는 메시지")
    args = parser.parse_args()
    if args.command == "init":
        if args.value or args.text:
            raise ValueError("init에는 추가 인자를 넣지 마세요.")
    elif not args.value.strip():
        raise ValueError("이 명령에는 사용자 또는 세션 ID가 필요합니다.")
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
            if args.command == "create":
                create_session(client, args.value)
                return
            if args.command == "session":
                owner = require_session(client, args.value)
                print("세션 사용자:", DEMO_USERS[owner])
                return
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
    except (ValueError, PermissionError) as exc:
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