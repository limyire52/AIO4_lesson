"""설치: pip install openai / 실행: python lmstudio_my.py"""

from openai import APIError, OpenAI

# LM Studio에 표시된 서버 주소를 입력하세요.
BASE_URL = "http://localhost:1235/v1"
SYSTEM_PROMPT = "당신은 친절한 AI 도우미입니다. 질문에 한국어로 답하세요."


def main():
    with OpenAI(base_url=BASE_URL, api_key="lmstudio", timeout=120.0,
                max_retries=0) as client:
        try:
            models = client.models.list()
        except APIError as error:
            print(f"서버 연결 실패: {error}")
            print(f"LM Studio 서버 실행 여부와 주소({BASE_URL})를 확인하세요.")
            return

        if not models.data:
            print("사용 가능한 모델이 없습니다. LM Studio에서 채팅 모델을 로드하세요.")
            return

        model_id = models.data[0].id
        print(f"사용 모델: {model_id}")
        print("질문을 입력하세요. /clear: 대화 초기화, /exit: 종료\n")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        while True:
            question = input("나: ").strip()
            if question.lower() in ("/exit", "exit", "quit", "종료"):
                print("대화를 종료합니다.")
                break
            if question.lower() == "/clear":
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                print("대화 기록을 초기화했습니다.\n")
                continue
            if not question:
                continue

            # 요청에 성공한 대화만 기록에 추가합니다.
            try:
                response = client.chat.completions.create(
                    model=model_id,
                    messages=messages + [{"role": "user", "content": question}],
                    temperature=0.7,
                    max_tokens=1024,
                )
            except APIError as error:
                print(f"응답 요청 실패: {error}\n다시 질문을 입력해주세요.\n")
                continue

            answer = response.choices[0].message.content if response.choices else None
            if not answer:
                print("답변이 비어 있습니다. 다른 질문을 입력해주세요.\n")
                continue
            messages.extend([
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ])
            print(f"AI: {answer}\n")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n대화를 종료합니다.")
