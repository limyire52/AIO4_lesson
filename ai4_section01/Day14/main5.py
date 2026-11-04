import argparse
import json
import os
import sqlite3
from contextlib import closing  # sqlite 연결을 종료할때 실제 로 close
import redis
from dotenv import load_dotenv
load_dotenv()

DEMO_USERS = {'demo-a':'홍길동', 'demo-b' : '강감찬'}
CACHE_TTL = 60  
MAX_MESSAGES = 6  # 원본 전체 중 최근 6개 메세지만 캐시 / 문맥에 사용

def read_settings():
    host = os.getenv('REDIS_HOST')
    port = os.getenv('REDIS_PORT')
    db_path = os.getenv('SQLITE_PATH')
    if not host or not port or not db_path:
        raise ValueError('필수값 누락')    
    return host,int(port),db_path

def initialize(conn):
    # 정상종료 commit 예외발생 rollback  
    with conn:
        conn.execute("""
        create table if not exists messages (
            id integer primary key autoincrement,
            owner text not null,
            role text not null check(role in ('user','assistant')),
            content text not null
        )
        """)
        if conn.execute("select count(*) from messages").fetchone()[0] == 0:
            conn.executemany(
                "insert into messages(owner, role, content) values(?,?,?)",
                [
                    ('demo-a','user','내 이름은 민수'),
                    ('demo-a','assistant','모의응답: 내 이름은 민수'),
                    ('demo-b','user','내 이름은 지연'),
                    ('demo-b','assistant','모의응답: 내 이름은 지연'),
                ],
            )

def read_source(conn, owner):
    '''owner:사용자  conn:db path'''
    rows = conn.execute(
        "select role,content from messages where owner = ? order by id desc limit ?",
        (owner,MAX_MESSAGES)
    ).fetchall()
    return [ {'role':role,'content':content }   for role,content in rows  ]

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


def cache_key(owner):
    return f"lesson05:history:{owner}"  # 사용자별 조회 결과의 캐시 이름

def load_history(conn, client, owner):
    key = cache_key(owner)
    raw = client.get(key)
    if raw is not None:  # 빈 목록을 담은 문자열 "[]"도 유효한 HIT다.
        return decode_history(raw), "HIT"
    messages = read_source(conn, owner)
    # ensure_ascii=False는 한글을 읽기 쉬운 문자로 저장한다. ex는 초 단위 만료다.
    client.set(key, json.dumps(messages, ensure_ascii=False), ex=CACHE_TTL)
    return messages, "MISS"

def show_history(messages, source):
    print("조회 경로:", source)
    if not messages:
        print("대화 이력이 없습니다.")
    for index, message in enumerate(messages, start=1):  # 표시 번호만 1부터 시작한다.
        print(f"{index}. {message['role']}: {message['content']}")

def main():
    parser = argparse.ArgumentParser(description="원본에서 복원하는 Redis 이력 캐시")
    parser.add_argument("command", choices=['init', 'history', 'evict'], help="실행할 동작")
    # init에는 value가 없으므로 ?로 생략을 허용한다. 명령별 필수 여부는 아래에서 검사한다.
    parser.add_argument("value", nargs="?", default="", help="가상 사용자 ID")
    args = parser.parse_args()
    if args.command == "init":
        if args.value:
            raise ValueError("init에는 추가 인자를 넣지 마세요.")
    elif not args.value.strip():
        raise ValueError("이 명령에는 사용자 ID가 필요합니다.")
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
                print("삭제한 캐시 수:", client.delete(cache_key(owner)))



if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print("입력/접근/설정 오류:", exc)  # 직접 만든 고정 메시지이며 설정값은 출력하지 않는다.
        raise SystemExit(1)
    except redis.exceptions.RedisError as exc:
        print("Redis 오류:", type(exc).__name__)
        print("서버 상태를 확인하세요. 이 차시는 Redis 장애 시 조회를 중단합니다.")
        raise SystemExit(1)
    except sqlite3.Error as exc:
        print("원본 DB 오류:", type(exc).__name__)
        print("DB 경로·권한·init 실행 여부를 확인하세요. 원본 오류는 캐시로 숨기지 않습니다.")
        raise SystemExit(1)