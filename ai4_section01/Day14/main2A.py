# uuid는 실행별 키 이름을 분리하고 os는 환경변수를 읽는 데 사용한다.
import os
import uuid

import redis  # Redis 서버로 명령을 보내는 클라이언트
from dotenv import load_dotenv  # .env 내용을 환경변수에 올린다.


def main():
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
    # 같은 서버를 쓰는 다른 실행의 키를 건드리지 않도록 이름을 분리한다.
    prefix = f"lesson02:{uuid.uuid4().hex}"
    string_key = f"{prefix}:status"
    hash_key = f"{prefix}:profile"
    list_key = f"{prefix}:messages"
    # 블록 종료 시 이 클라이언트가 소유하는 연결 풀도 닫는다.
    with redis.Redis(
        host=host,                 # 외부 설정에서 읽은 서버 주소
        port=port,                 # PC에 공개된 Redis 포트
        decode_responses=True,     # True는 str 응답, 기본 False는 bytes 응답
        socket_connect_timeout=2,  # 연결 단계의 제한 시간(초)
        socket_timeout=2,          # 소켓 읽기/쓰기 단계의 제한 시간(초)
    ) as client:
        print("PING:", client.ping())
        try:
            # String: 키 하나에 문자열 하나를 저장한다. ex=60은 60초 후 자동 만료다.
            client.set(string_key, "ready", ex=60)
            print("String 값:", client.get(string_key))
            print("String 자료형:", client.type(string_key))

            # Hash: mapping으로 여러 필드와 값을 한 키에 저장한다.
            added = client.hset(
                hash_key,  # 사용자 프로필을 담을 키
                mapping={"name": "민수", "level": "basic"},  # 필드:값 사전
            )
            client.expire(hash_key, 60)  # Hash 전체 키의 TTL을 60초로 설정한다.
            print("Hash 새 필드 수:", added)
            print("Hash 이름:", client.hget(hash_key, "name"))
            # 같은 필드를 수정하면 새 필드 수는 0이지만 값은 실제로 바뀐다.
            print("Hash 수정 시 새 필드 수:", client.hset(hash_key, "level", "practice"))
            print("Hash 전체:", client.hgetall(hash_key))
            print("Hash 자료형:", client.type(hash_key))

            # List: RPUSH는 인자를 나열한 순서대로 오른쪽 끝에 추가한다.
            length = client.rpush(list_key, "첫 질문", "첫 답변", "둘째 질문")
            client.expire(list_key, 60)  # List 전체 키에 TTL을 설정한다.
            print("List 길이:", length)
            print("List 전체:", client.lrange(list_key, 0, -1))
            print("List 최근 두 개:", client.lrange(list_key, -2, -1))
            print("List 자료형:", client.type(list_key))
            print("없는 Hash 필드:", client.hget(hash_key, "email"))
            print("없는 키 GET:", client.get(f"{prefix}:missing"))

            # 자료형과 맞지 않는 명령의 실패를 이 자리에서만 관찰한다.
            try:
                client.get(hash_key)  # Hash는 GET 대신 HGET/HGETALL을 사용해야 한다.
            except redis.exceptions.ResponseError:
                print("자료형 오류 확인: Hash에는 GET을 사용할 수 없습니다.")
        finally:
            # 정상·실패 시 모두 이번 실행이 생성한 세 키만 정리한다.
            print("정리한 키 수:", client.delete(string_key, hash_key, list_key))


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