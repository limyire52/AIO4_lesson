""" 하이브리드 대화 백엔드 실습."""
import os  # .env에서 로드된 환경변수를 조회한다.
from uuid import UUID, uuid4  # UUID는 입력 검사, uuid4는 새 대화방 ID 생성에 쓴다.

import psycopg  # PostgreSQL 동기 드라이버다.
from psycopg.rows import dict_row  # 컬럼 이름을 키로 하는 딕셔너리 행을 받는다.
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from redis import Redis, RedisError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

# 이 파일 위치부터 상위 폴더의 .env를 찾아 읽고 해당 설정을 우선한다.
# ${...}는 치환하지 않아 접속 문자열의 원문을 보존한다.
load_dotenv(override=True, interpolate=False)
DB_URL = os.getenv("SUPABASE_DB_URL", "")
if not DB_URL.strip():  # 빈 값 판정만 하며 실제 접속값은 수정하지 않는다.
    raise RuntimeError("SUPABASE_DB_URL 설정이 필요합니다.")

REDIS_URL = os.getenv("REDIS_URL", "")
TTL_TEXT = os.getenv("SESSION_TTL_SECONDS", "")
if not REDIS_URL.strip():
    raise RuntimeError("REDIS_URL 설정이 필요합니다.")
if not REDIS_URL.startswith(("redis://", "rediss://")):
    raise RuntimeError("REDIS_URL의 연결 방식을 확인하세요.")
if not TTL_TEXT.strip():
    raise RuntimeError("SESSION_TTL_SECONDS 설정이 필요합니다.")
try:
    SESSION_TTL_SECONDS = int(TTL_TEXT)
except ValueError:
    raise RuntimeError("SESSION_TTL_SECONDS는 양의 정수여야 합니다.") from None
if SESSION_TTL_SECONDS <= 0:
    raise RuntimeError("SESSION_TTL_SECONDS는 양의 정수여야 합니다.")

app = FastAPI()


class ConversationCreate(BaseModel):
    # 미정의 필드를 거절하고 문자열 양끝 공백을 제거한 후 길이를 검사한다.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=100)  # 기본값이 없어 필수다.


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=1000)  # 공백만 있는 메시지도 거절한다.


def connect_db():
    # 호출한 쪽의 with에서 정상 commit / 예외 rollback / 연결 종료를 담당한다.
    return psycopg.connect(
        DB_URL,  # Connect > Session pooler에서 복사한 DB URI.
        connect_timeout=5,  # 연결 수립 대기 제한(초), SQL 실행 제한은 아니다.
        sslmode="require",  # 원격 DB에 TLS 암호화를 요구한다.
        row_factory=dict_row,  # 기본 튜플 대신 {컬럼: 값} 형식으로 읽는다.
    )


def init_db():
    # python main.py로 실행할 때만 호출한다. SQL 파일은 따로 읽지 않는다.
    with connect_db() as conn:
        # 전용 스키마를 사용해 다른 수업의 public 테이블과 이름이 겹치지 않게 한다.
        conn.execute("CREATE SCHEMA IF NOT EXISTS kdt_hybrid")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kdt_hybrid.conversation (
                id UUID PRIMARY KEY,
                title VARCHAR(100) NOT NULL CHECK (length(trim(title)) > 0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kdt_hybrid.messages (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                conversation_id UUID NOT NULL
                    REFERENCES kdt_hybrid.conversation(id),
                content VARCHAR(1000) NOT NULL CHECK (length(trim(content)) > 0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    # with 정상 종료로 commit이 끝난 뒤에만 완료를 출력한다.
    print("테이블 준비 완료")


# DB 드라이버 오류가 요청 처리 중 발생했을 때 FastAPI가 호출할 처리기를 등록한다.
@app.exception_handler(psycopg.Error)
def database_error(_request, _exc):
    # FastAPI가 전달하는 요청/예외는 여기서 출력하지 않는다. 모든 오류를 잡지는 않는다.
    return JSONResponse(
        status_code=503,  # 이 실습에서는 DB 처리 실패를 서비스 이용 불가로 표시한다.
        content={"detail": "DB 처리에 실패했습니다. 연결과 테이블 준비를 확인하세요."},
    )


# 데코레이터는 경로 등록이다. 실제 함수 호출은 해당 HTTP 요청이 들어왔을 때다.
@app.post("/conversations", status_code=201)  # 새 행 생성 성공은 201로 응답한다.
def create_conversation(body: ConversationCreate):
    conversation_id = uuid4()
    with connect_db() as conn:
        row = conn.execute(
            """INSERT INTO kdt_hybrid.conversation (id, title)
               VALUES (%s, %s) RETURNING id, title, created_at""",
            (conversation_id, body.title),  # %s 자리에 바인딩할 값. 문자열로 합치지 않는다.
        ).fetchone()  # RETURNING이 돌려준 새 행 하나를 읽는다.
    return row  # with 종료로 commit한 뒤 FastAPI가 UUID/시간을 JSON으로 변환한다.


@app.get("/conversations")
def list_conversations():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM kdt_hybrid.conversation ORDER BY created_at, id"
        ).fetchall()  # 모든 결과 행을 리스트로 읽는다. 이 실습은 소량 데이터만 사용한다.
    return rows


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID  # 이번에는 UUID 형식뿐 아니라 실제 DB 존재도 확인한다.


def connect_redis():
    return Redis.from_url(
        REDIS_URL,  # PC에서 접근 가능한 Redis URI.
        decode_responses=True,  # GET 결과를 문자열로 받는다. 기본은 bytes다.
        socket_connect_timeout=3,  # 연결 수립 대기 제한(초).
        socket_timeout=3,  # 소켓 응답 대기 제한(초). 총 요청 시간과 다르다.
    )


@app.exception_handler(RedisError)
def redis_error(_request, _exc):
    # 통신 실패를 세션 만료와 구분한다. 오류 원문과 접속값을 응답에 넣지 않는다.
    return JSONResponse(status_code=503, content={"detail": "Redis 연결을 확인하세요."})


@app.post("/sessions", status_code=201)
def create_session(body: SessionCreate):
    # DB에서 실제 대화방을 찾은 뒤, 기존 행을 수정하지 않고 세션만 발급한다.
    with connect_db() as conn:
        found = conn.execute(
            "SELECT id FROM kdt_hybrid.conversation WHERE id = %s", (body.conversation_id,)
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
    session_id = str(uuid4())
    with connect_redis() as client:
        client.set(
            f"kdt:hybrid:l05:session:{session_id}",  # 3차시의 임의 ID 세션과 분리한다.
            str(body.conversation_id),  # Redis에는 메시지가 아닌 대화방 ID만 저장한다.
            ex=SESSION_TTL_SECONDS,  # 발급 순간부터 흐르는 고정 만료 시간(초).
        )
    return {"session_id": session_id, "expires_in": SESSION_TTL_SECONDS}


def resolve_conversation(x_session_id):
    # Header(default=None)이므로 헤더 누락 시에도 이 함수에서 401을 정할 수 있다.
    if not x_session_id:
        raise HTTPException(status_code=401, detail="X-Session-Id 헤더가 필요합니다.")
    try:
        session_id = UUID(x_session_id)  # 잘못된 ID로 임의 Redis 키를 조회하지 않는다.
    except ValueError:
        raise HTTPException(status_code=401, detail="세션 ID 형식이 올바르지 않습니다.") from None
    with connect_redis() as client:
        raw = client.get(f"kdt:hybrid:l05:session:{session_id}")
    if raw is None:
        raise HTTPException(status_code=401, detail="세션이 없거나 만료되었습니다.")
    try:
        return UUID(raw)  # 클라이언트 본문이 아닌 서버 세션에서 대화방 ID를 결정한다.
    except ValueError:
        raise HTTPException(status_code=503, detail="저장된 세션 형식을 확인하세요.") from None


@app.post("/messages", status_code=201)
def create_message(
    body: MessageCreate,
    x_session_id: str | None = Header(default=None),  # X-Session-Id 헤더. 누락 시 None.
):
    # Redis에서 유효한 세션을 찾지 못하면 아래 DB 저장까지 진행하지 않는다.
    conversation_id = resolve_conversation(x_session_id)
    with connect_db() as conn:
        found = conn.execute(
            "SELECT id FROM kdt_hybrid.conversation WHERE id = %s", (conversation_id,)
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
        row = conn.execute(
            """INSERT INTO kdt_hybrid.messages (conversation_id, content)
               VALUES (%s, %s) RETURNING id, conversation_id, content, created_at""",
            (conversation_id, body.content),
        ).fetchone()
    return row  # commit 후 반환한다. Redis에는 메시지를 복사하지 않는다.


@app.get("/messages")
def list_messages(x_session_id: str | None = Header(default=None)):
    conversation_id = resolve_conversation(x_session_id)
    with connect_db() as conn:
        found = conn.execute(
            "SELECT id FROM kdt_hybrid.conversation WHERE id = %s", (conversation_id,)
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
        rows = conn.execute(
            """SELECT id, conversation_id, content, created_at
               FROM kdt_hybrid.messages WHERE conversation_id = %s ORDER BY id""",
            (conversation_id,),
        ).fetchall()
    return rows


# 현재 세션 정보와 TTL을 조회한다. 조회 자체는 연장하지 않는다.
@app.get("/session")
def session_status(x_session_id: str | None = Header(default=None)):
    conversation_id = resolve_conversation(x_session_id)
    with connect_redis() as client:
        ttl = client.ttl(f"kdt:hybrid:l05:session:{UUID(x_session_id)}")
    if ttl == -2:
        raise HTTPException(status_code=401, detail="세션이 만료되었습니다.")
    if ttl == -1:
        raise HTTPException(status_code=503, detail="세션 만료 설정을 확인하세요.")
    return {"conversation_id": str(conversation_id), "ttl": ttl}


# 별도 요청으로만 연장한다. 메시지 저장/조회는 TTL을 바꾸지 않는다.
@app.post("/session/renew")
def renew_session(x_session_id: str | None = Header(default=None)):
    conversation_id = resolve_conversation(x_session_id)
    with connect_db() as conn:
        found = conn.execute(
            "SELECT id FROM kdt_hybrid.conversation WHERE id = %s", (conversation_id,)
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
    with connect_redis() as client:
        renewed = client.expire(
            f"kdt:hybrid:l05:session:{UUID(x_session_id)}",
            SESSION_TTL_SECONDS,  # 현재 시점부터 이 초만큼 남도록 재설정한다.
        )  # 키가 이미 사라졌으면 False다. EXPIRE는 없는 키를 만들지 않는다.
    if not renewed:
        raise HTTPException(status_code=401, detail="세션이 만료되었습니다.")
    return {"expires_in": SESSION_TTL_SECONDS}


@app.delete("/session")
def end_session(x_session_id: str | None = Header(default=None)):
    # 형식/존재를 먼저 확인하고 Redis 키만 삭제한다. DB 행은 삭제하지 않는다.
    resolve_conversation(x_session_id)
    with connect_redis() as client:
        removed = client.delete(f"kdt:hybrid:l05:session:{UUID(x_session_id)}")
    if not removed:
        raise HTTPException(status_code=401, detail="세션이 만료되었습니다.")
    return {"ended": True}


# 초기화는 명시적으로 실행한다. Uvicorn import 시 DB를 변경하지 않는다.
if __name__ == "__main__":
    try:
        init_db()
    except psycopg.Error:
        raise SystemExit("DB 준비 실패: 접속 설정과 스키마 생성 권한을 확인하세요.") from None
