# argparse는 명령줄 입력, secrets는 추측하기 어려운 세션 ID 생성에 사용한다.
import argparse
import os
import secrets

import redis
from dotenv import load_dotenv

# 가상의 계정 목록이다. 실제 회원 DB나 비밀번호 인증을 대신하지 않는다.
DEMO_USERS = {"demo-a": "민수", "demo-b": "지연"}
SESSION_TTL = 60  # 생성 시점부터 60초이며 조회할 때 연장하지 않는다.


def main():
    # command와 value는 CMD에서 python main.py 뒤에 입력하는 두 인자다.
    parser = argparse.ArgumentParser(description="Redis 세션 생성·조회·로그아웃 실습")
    parser.add_argument("command", choices=["create", "get", "logout"], help="수행할 동작")
    parser.add_argument("value", help="create: 가상 사용자 ID, 그 외: 발급받은 세션 ID")
    args = parser.parse_args()  # 잘못된 명령·누락된 인자는 도움말과 종료 코드 2로 처리한다.
    # .env는 현재 작업 폴더에서 읽으며, 이미 존재하는 환경변수가 우선한다.
    load_dotenv(".env", override=False, interpolate=False)
    host = os.getenv("REDIS_HOST", "")
    port_text = os.getenv("REDIS_PORT", "")
    if not host.strip() or not port_text.strip():
        raise ValueError("REDIS_HOST와 REDIS_PORT의 필수 설정을 확인하세요.")
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError("REDIS_PORT는 1~65535 범위의 정수여야 합니다.") from None
    if not 1 <= port <= 65535:
        raise ValueError("REDIS_PORT는 1~65535 범위의 정수여야 합니다.")
    # 블록 종료 시 이 클라이언트가 소유하는 연결 풀도 닫는다.
    with redis.Redis(
        host=host,                 # 외부 설정에서 읽은 서버 주소
        port=port,                 # PC에 공개된 Redis 포트
        decode_responses=True,     # True는 str 응답, 기본 False는 bytes 응답
        socket_connect_timeout=2,  # 연결 단계의 제한 시간(초)
        socket_timeout=2,          # 소켓 읽기/쓰기 단계의 제한 시간(초)
    ) as client:
        if args.command == "create":
            if args.value not in DEMO_USERS:
                raise ValueError("create에는 demo-a 또는 demo-b를 사용하세요.")
            # 32는 난수 바이트 수다. sid_ 접두사는 ID가 -로 시작해 CLI 옵션으로 오인되는 일을 막는다.
            session_id = "sid_" + secrets.token_urlsafe(32)
            key = f"lesson03:session:{session_id}"
            client.set(key, args.value, ex=SESSION_TTL)  # 사용자 ID와 60초 만료를 함께 저장한다.
            # 가상 로컬 실습에서 다음 명령으로 전달하기 위해서만 ID를 표시한다.
            print("SESSION_ID:", session_id)
            print("생성한 사용자:", DEMO_USERS[args.value])
            print("만료 시간(초):", SESSION_TTL)
        else:
            key = f"lesson03:session:{args.value}"
            if args.command == "get":
                # 조회 시 사용자 ID를 입력받아 신뢰하지 않고 Redis에서 찾은 값만 사용한다.
                user_id = client.get(key)
                if user_id is None:
                    print("접근 거절: 세션이 없거나 만료되었습니다.")
                    raise SystemExit(1)
                if user_id not in DEMO_USERS:
                    raise ValueError("저장된 세션의 사용자 정보를 확인하세요.")
                print("세션 사용자:", DEMO_USERS[user_id])
                # TTL 조회는 관찰용이다. GET과 TTL 사이에도 시간이 흐를 수 있다.
                print("남은 TTL:", client.ttl(key))
            else:
                # 서버 측 키를 지워 같은 ID를 다시 써도 조회가 실패하도록 만든다.
                print("로그아웃으로 삭제한 세션 수:", client.delete(key))


# 이 파일을 직접 실행할 때만 실습을 시작한다.
if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        # 직접 만든 검증 오류 메시지이며 설정값·세션 원문은 포함하지 않는다.
        print("입력/설정 오류:", exc)
        raise SystemExit(1)
    except redis.exceptions.RedisError as exc:
        # 연결 문자열 등을 노출하지 않도록 상세 내용 대신 종류만 보여준다.
        print("Redis 오류:", type(exc).__name__)
        print("서버 상태·설정·실습 키의 자료형을 확인하세요.")
        raise SystemExit(1)