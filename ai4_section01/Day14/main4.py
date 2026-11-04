# python main4.py create demo-a
# python main4.py chat [세션이 발급한 id] "내 이름은 민수"
# python main4.py chat [세션이 발급한 id] "내 이름이 뭐야?"
# python main4.py history [세션이 발급한 id]

# 세션별 대화 이력을 저장하고 응답에 전달

# json은 메시지의 role/content 변환, secrets는 세션 ID, argparse는 명령 입력에 사용한다.
import argparse
import json
import os
import secrets

import redis
from dotenv import load_dotenv

DEMO_USERS = {"demo-a": "민수", "demo-b": "지연"}
SESSION_TTL = 300  # 여러 명령을 입력할 수 있도록 세션 생성 후 5분 동안 유효하다.
HISTORY_TTL = 300  # 마지막 메시지 저장 후 대화 키를 5분 동안 보관한다.
MAX_MESSAGES = 6  # user/assistant 두 메시지가 한 턴이므로 최근 세 턴을 남긴다

def read_history(client, history_key):
    # 0부터 -1까지는 전체 범위이며, 이 프로그램은 저장 후 최대 6개만 남긴다.
    raw_messages = client.lrange(history_key, 0, -1)
    messages = []
    for raw in raw_messages:
        try:
            message = json.loads(raw)  # JSON 문자열 한 개를 Python 사전으로 복원한다.
        except json.JSONDecodeError:
            raise ValueError("대화 이력에 올바르지 않은 JSON이 있습니다.") from None
        # 외부 CLI로 손상된 데이터를 넣었을 때 원문 대신 고정 오류를 반환한다.
        if (
            not isinstance(message, dict)
            or message.get("role") not in ("user", "assistant")
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError("대화 이력의 role/content 형식을 확인하세요.")
        messages.append(message)
    return messages

def make_demo_reply(messages, text):
    # LLM API가 아닌 규칙 기반 모의 응답이다. 이력이 응답 함수로 전달되는지 확인한다.
    if text == "내 이름이 뭐야?":
        for message in reversed(messages):  # 최근에 저장한 이름부터 찾는다.
            if message["role"] == "user" and message["content"].startswith("내 이름은 "):
                name = message["content"].removeprefix("내 이름은 ")
                return f"기록에서 찾은 이름: {name}"
        return "현재 보관된 이력에서 이름을 찾지 못했습니다."
    return f"모의 응답: {text}"

def main():
    parser = argparse.ArgumentParser(description="세션별 대화 이력 저장과 문맥 전달 실습")
    parser.add_argument(
        "command", choices=["create", "chat", "history", "clear", "logout"],
        help="세션 생성, 대화, 이력 조회, 이력 삭제, 로그아웃 중 하나",
    )
    parser.add_argument("value", help="create: demo-a/demo-b, 그 외: 발급받은 세션 ID")
    parser.add_argument("text", nargs="?", default="", help="chat에서만 사용하는 메시지")
    args = parser.parse_args()
    # 선택 인자 text는 생략 가능하지만 chat에는 공백이 아닌 문자열이 필요하다.
    if args.command == "chat" and not args.text.strip():
        raise ValueError("chat 메시지는 공백이 아닌 문자열이어야 합니다.")
    if args.command != "chat" and args.text:
        raise ValueError("메시지는 chat 명령에서만 입력하세요.")
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
            session_id = "sid_" + secrets.token_urlsafe(32)  # 난수 32바이트로 새 세션 ID를 만든다.
            client.set(f"lesson04:session:{session_id}", args.value, ex=SESSION_TTL)
            print("SESSION_ID:", session_id)  # 로컬 가상 실습에서 다음 명령에 전달하기 위한 출력
            print("생성한 사용자:", DEMO_USERS[args.value])
            print("만료 시간(초):", SESSION_TTL)
            return

        # 클라이언트가 보낸 ID로 서버 상태를 찾아 유효한 세션인지 먼저 확인한다.
        session_key = f"lesson04:session:{args.value}"
        history_key = f"lesson04:history:{args.value}"
        user_id = client.get(session_key)
        if user_id is None:
            print("접근 거절: 세션이 없거나 만료되었습니다.")
            raise SystemExit(1)
        if user_id not in DEMO_USERS:
            raise ValueError("저장된 세션의 사용자 정보를 확인하세요.")
        if args.command == "logout":
            # 세션과 해당 세션의 대화 키를 한 DEL 명령으로 함께 정리한다.
            print("로그아웃으로 삭제한 키 수:", client.delete(session_key, history_key))
            return
        if args.command == "clear":
            print("삭제한 대화 키 수:", client.delete(history_key))  # 세션은 유지한다.
            return

        messages = read_history(client, history_key)
        print("세션 사용자:", DEMO_USERS[user_id])
        if args.command == "history":
            if not messages:
                print("대화 이력이 없습니다.")
            for index, message in enumerate(messages, start=1):  # 1부터 번호를 표시한다.
                print(f"{index}. {message['role']}: {message['content']}")
            print("이력 TTL:", client.ttl(history_key))
            return

        # 새 입력을 추가하기 전의 이력을 응답 함수로 넘겨 문맥 재사용을 확인한다.
        reply = make_demo_reply(messages, args.text)
        # ensure_ascii=False는 기본 True와 달리 한글을 이스케이프 대신 문자로 보관한다.
        user_message = json.dumps({"role": "user", "content": args.text}, ensure_ascii=False)
        assistant_message = json.dumps({"role": "assistant", "content": reply}, ensure_ascii=False)
        # 한 RPUSH 안에 두 값을 보내 user 다음 assistant 순서로 연속 추가한다.
        client.rpush(history_key, user_message, assistant_message)
        # -6부터 -1까지 남겨 최근 6개 메시지, 즉 정상 저장된 세 턴만 보관한다.
        client.ltrim(history_key, -MAX_MESSAGES, -1)
        # 저장할 때만 대화 키의 만료를 갱신한다. 세션 자체의 만료는 연장하지 않는다.
        client.expire(history_key, HISTORY_TTL)
        print("응답 생성에 사용한 이전 메시지 수:", len(messages))
        print("모의 응답 결과:", reply)
        print("보관된 메시지 수:", client.llen(history_key))


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