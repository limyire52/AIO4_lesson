""" Redis에 만료되는 대화 세션을 발급하고 조회한다."""
import os
from uuid import UUID, uuid4  # 대화방 ID 검사와 세션 ID 생성에 사용한다.

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from redis import Redis, RedisError

# .env 설정을 기존 환경변수보다 우선하고 ${...} 원문을 보존한다.
load_dotenv(override=True, interpolate=False)
REDIS_URL = os.getenv("REDIS_URL", "")
TTL_TEXT = os.getenv("SESSION_TTL_SECONDS", "")
if not REDIS_URL.strip():
    raise RuntimeError("REDIS_URL 설정이 필요합니다.")
if not REDIS_URL.startswith(("redis://", "rediss://")):
    raise RuntimeError("REDIS_URL의 연결 방식을 확인하세요.")
if not TTL_TEXT.strip():
    raise RuntimeError("SESSION_TTL_SECONDS 설정이 필요합니다.")
try:
    SESSION_TTL_SECONDS = int(TTL_TEXT)  # .env의 문자열을 초 단위 정수로 바꾼다.
except ValueError:
    raise RuntimeError("SESSION_TTL_SECONDS는 양의 정수여야 합니다.") from None
if SESSION_TTL_SECONDS <= 0:
    raise RuntimeError("SESSION_TTL_SECONDS는 양의 정수여야 합니다.")

app = FastAPI()


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 오타 등 알 수 없는 필드를 거절한다.
    conversation_id: UUID  # UUID 형식만 검사한다. 이 차시에는 DB 연결이 없다.


def connect_redis():
    # 호출한 쪽이 with로 닫는다. URI 해석 뒤 실제 명령에서 서버와 통신한다.
    return Redis.from_url(
        REDIS_URL,
        decode_responses=True,  # GET 결과를 bytes 대신 문자열로 읽는다. 기본은 False다.
        socket_connect_timeout=3,  # 연결 수립 대기 제한(초).
        socket_timeout=3,  # 소켓 응답 대기 제한(초). 전체 HTTP 제한이 아니다.
    )


# Redis 통신/인증 오류 때만 실행되는 오류 처리기를 등록한다.
@app.exception_handler(RedisError)
def redis_error(_request, _exc):
    return JSONResponse(status_code=503, content={"detail": "Redis 연결을 확인하세요."})


@app.post("/sessions", status_code=201)
def create_session(body: SessionCreate):
    session_id = str(uuid4())  # 클라이언트에 돌려줄 새 세션 ID. 대화방 ID와 다르다.
    key = f"kdt:hybrid:l03:session:{session_id}"  # 다른 차시와 키를 구분한다.
    with connect_redis() as client:
        client.set(
            key,  # 저장할 Redis 키.
            str(body.conversation_id),  # 값은 대화방 ID 하나만 보관한다.
            ex=SESSION_TTL_SECONDS,  # SET과 만료 설정을 한 명령으로 실행한다. 단위는 초.
        )
    return {"session_id": session_id, "expires_in": SESSION_TTL_SECONDS}


@app.get("/sessions/{session_id}")
def read_session(session_id: UUID):
    # 경로 UUID를 문자열로 정규화해야 발급 때 사용한 키와 일치한다.
    key = f"kdt:hybrid:l03:session:{session_id}"
    with connect_redis() as client:
        conversation_id = client.get(key)  # 없는 키는 None이다. 조회로 TTL을 늘리지 않는다.
        ttl = client.ttl(key)  # 남은 초. -2는 키 없음, -1은 만료 설정 없음이다.
    if conversation_id is None or ttl == -2:
        raise HTTPException(status_code=401, detail="세션이 없거나 만료되었습니다.")
    if ttl == -1:
        raise HTTPException(status_code=503, detail="세션 만료 설정을 확인하세요.")
    return {"session_id": str(session_id), "conversation_id": conversation_id, "ttl": ttl}
