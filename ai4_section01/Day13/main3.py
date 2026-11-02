# os는 환경변수 조회, Annotated는 매개변수에 Header/Depends 정보를 붙이는 표준 기능입니다.
import os
from typing import Annotated
# SQLite는 내장 DB, closing은 연결 정리, uuid4는 메모 고유 ID 생성에 사용합니다.
import sqlite3
from contextlib import closing
from uuid import uuid4
# HTTPX는 타임아웃과 연결 수명, python-dotenv는 .env 로딩을 담당합니다.
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, Depends
# HTTPBearer는 헤더를 추출하고, HTTPAuthorizationCredentials는 추출 결과의 타입입니다.
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# 요청 검증 실패를 JSON 오류로 바꾸고, Pydantic으로 입력·응답 모델을 정의합니다.
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr
# Supabase SDK는 실제 인증을 수행하고 AuthApiError는 서버 오류 code/status를 제공합니다.
from supabase import AuthApiError, AuthRetryableError, create_client
from supabase.client import ClientOptions


# load_dotenv는 파일 값을 환경변수에 추가하고 os.getenv는 그 값을 조회합니다.
load_dotenv(          
    override=False,     # 기존 프로세스 환경변수가 우선합니다. 기본값도 False입니다.
    interpolate=False,  # ${...}를 치환하지 않고 그대로 보존합니다. 기본값은 True입니다.
)
supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
# getenv의 두 번째 인자 ""는 변수가 없을 때의 값입니다. 실제 값은 출력하지 않습니다.
if not supabase_url or not supabase_key:
    raise RuntimeError("SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY를 설정하세요.")
if not supabase_url.startswith("https://") or not supabase_key.startswith("sb_publishable_"):
    raise RuntimeError("https Project URL과 sb_publishable_ 키의 형식을 확인하세요.")

# DB 파일명도 .env에서 읽습니다. 서로 다른 차시는 별도 파일을 사용합니다.
notes_db = os.getenv("NOTES_DB", "").strip()
if not notes_db:
    raise RuntimeError("NOTES_DB에 현재 차시의 SQLite 파일명을 설정하세요.")
# 서버 시작 시 테이블이 없으면 생성합니다. SQL을 별도 파일로 분리하지 않습니다.
# sqlite 연결의 with는 자동 close가 아니므로 closing으로 닫습니다. commit은 변경 확정입니다.
with closing(sqlite3.connect(notes_db)) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    conn.commit()

# title은 Swagger 화면의 제목이며 인증 정책을 바꾸지 않습니다.
app = FastAPI(title="5차시 - 내 메모의 소유자 접근 제어")


# 요청 검증 모델입니다. extra="forbid"는 정의하지 않은 필드를 거절합니다.
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr  # 자체 정규식 대신 email-validator로 형식을 검사합니다.
    # 로그인은 기존 비밀번호를 확인하므로 빈 문자열만 거절합니다.
    password: SecretStr = Field(min_length=1)


# 토큰은 호출자가 사용할 수 있도록 str로 반환합니다. SecretStr면 JSON에서도 가려집니다.
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int         # 발급 시 기준 유효기간(초)입니다.
    expires_at: int | None  # 절대 만료 시각(Unix timestamp)입니다.
    user_id: str
    email: str | None


# 인증 결과에는 필요한 사용자 정보만 담고 비밀번호·토큰을 넣지 않습니다.
class CurrentUser(BaseModel):
    id: str
    email: str | None


# 입력 검사 실패 시 실행할 함수를 등록합니다. 실제 오류 발생 시 FastAPI가 호출합니다.
@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    # 원본 입력(input)을 제외해 비밀번호·refresh token이 422 응답에 노출되지 않게 합니다.
    errors = [{"loc": e["loc"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


def make_client(http_client: httpx.Client):
    # 같은 SDK 생성 규칙을 로그인과 사용자 확인에서 사용합니다. 사용자별 전역 세션은 없습니다.
    return create_client(
        supabase_url,  # 연결할 Auth 프로젝트 주소입니다.
        supabase_key,  # 프로젝트용 publishable 키이며 사용자 JWT가 아닙니다.
        options=ClientOptions(
            persist_session=False,     # SDK 저장소에 세션을 쓰지 않습니다. 기본 True입니다.
            auto_refresh_token=False,  # 백그라운드 자동 갱신을 끕니다. 기본 True입니다.
            httpx_client=http_client,  # 전달된 HTTPX 객체의 통신 설정을 사용합니다. 기본 None입니다.
        ),
    )


def raise_auth_error(exc: AuthApiError):
    # code는 Auth 오류의 종류입니다. HTTP 상태만 보고 비밀번호 오류로 단정하지 않습니다.
    invalid_codes = ['bad_jwt', 'invalid_credentials', 'session_not_found', 'user_banned', 'user_not_found']
    if exc.code in invalid_codes:
        raise HTTPException(401, "로그인 정보 또는 토큰을 확인하세요.", headers={"WWW-Authenticate": "Bearer"}) from None
    if exc.code == "email_not_confirmed":
        raise HTTPException(403, "이메일 확인을 완료하세요.") from None
    if exc.status == 429:
        raise HTTPException(429, "요청이 많습니다. 잠시 후 재시도하세요.") from None
    if exc.status >= 500 or exc.status in (401, 403):
        raise HTTPException(503, "인증 서비스 상태 또는 프로젝트 설정을 확인하세요.") from None
    # HTTPException의 첫 인자는 상태 코드, 두 번째는 JSON detail에 넣을 문구입니다.
    raise HTTPException(400, "Auth 요청을 처리할 수 없습니다.") from None


def token_response(result, response: Response):
    # SDK 전체 응답 대신 현재 API가 필요한 필드만 반환합니다.
    if result.session is None or result.user is None:
        raise HTTPException(502, "로그인 세션 응답이 올바르지 않습니다.")
    session = result.session
    response.headers["Cache-Control"] = "no-store"  # 토큰 응답을 캐시에 저장하지 않도록 합니다.
    return TokenResponse(
        access_token=session.access_token, refresh_token=session.refresh_token,
        token_type=session.token_type, expires_in=session.expires_in,
        expires_at=session.expires_at, user_id=result.user.id, email=result.user.email,
    )


# 경로와 응답 모델을 등록합니다. 실제 POST 요청이 와야 함수 본문이 실행됩니다.
@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response):
    try:
        # timeout은 통신 단계별 10초 설정이며, with 종료 시 HTTP 연결을 닫습니다.
        with httpx.Client(timeout=10.0) as http_client:
            result = make_client(http_client).auth.sign_in_with_password({
                "email": str(body.email),
                "password": body.password.get_secret_value(),  # 전송 직전에만 원문을 꺼냅니다.
            })
    except AuthApiError as exc:
        raise_auth_error(exc)
    except (AuthRetryableError, httpx.HTTPError):
        raise HTTPException(503, "Auth 통신에 실패했습니다.") from None
    return token_response(result, response)


def verified_user(token: str):
    # 문자열을 디코딩해 믿지 않고 Auth 서버에 전달해 검증된 사용자 정보를 받습니다.
    try:
        with httpx.Client(timeout=10.0) as http_client:
            result = make_client(http_client).auth.get_user(token)  # token 인자는 사용자 access token입니다.
    except AuthApiError as exc:
        raise_auth_error(exc)
    except (AuthRetryableError, httpx.HTTPError):
        raise HTTPException(503, "Auth 통신에 실패했습니다.") from None
    if result is None or result.user is None:
        raise HTTPException(401, "사용자를 확인할 수 없습니다.", headers={"WWW-Authenticate": "Bearer"})
    return CurrentUser(id=result.user.id, email=result.user.email)


# HTTPBearer는 헤더에서 scheme/credentials를 추출하고 Swagger에 인증 입력을 만듭니다.
# auto_error=False: 누락 시 자동 종료하지 않고 None을 주어 우리가 401을 통일합니다.
# 기본값은 True이며, 이 객체 자체는 JWT의 서명이나 만료를 검증하지 않습니다.
bearer = HTTPBearer(auto_error=False)


def require_token(credentials: HTTPAuthorizationCredentials | None):
    if credentials is None:
        raise HTTPException(401, "Bearer 토큰이 필요합니다.", headers={"WWW-Authenticate": "Bearer"})
    return credentials.credentials  # credentials 필드에는 Bearer 다음의 토큰 문자열이 있습니다.


# Depends(bearer)가 먼저 실행되고 그 결과가 credentials에 들어옵니다.
def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    return verified_user(require_token(credentials))


# 함수 자체를 Depends에 전달합니다. get_current_user()처럼 미리 호출하지 않습니다.
@app.get("/me", response_model=CurrentUser)
def me(user: Annotated[CurrentUser, Depends(get_current_user)]):
    return user


class NoteInput(BaseModel):
    # 메모에는 공백 제거를 적용하지만 로그인 비밀번호에는 적용하지 않습니다.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=2000)  # 빈 메모와 지나치게 긴 메모를 거절합니다.


class Note(BaseModel):
    id: str
    owner_id: str
    content: str


def get_db():
    # 요청마다 새 연결입니다. FastAPI의 동기 의존성/경로가 다른 스레드에서 실행될 수 있어 False로 둡니다.
    # check_same_thread의 기본값은 True입니다. False가 동시 쓰기를 자동으로 안전하게 만들지는 않습니다.
    conn = sqlite3.connect(notes_db, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # 숫자 인덱스뿐 아니라 컬럼 이름으로 읽도록 합니다.
    try:
        yield conn  # FastAPI가 연결을 경로에 전달하고, 정리 시 finally를 실행합니다.
    finally:
        conn.close()


@app.post("/notes", response_model=Note, status_code=201)
def create_note(body: NoteInput, user: Annotated[CurrentUser, Depends(get_current_user)], db: Annotated[sqlite3.Connection, Depends(get_db)]):
    # owner_id는 요청에서 받지 않고 검증된 사용자 ID로 정합니다.
    note = Note(id=str(uuid4()), owner_id=user.id, content=body.content)
    # ? 자리에는 값만 바인딩합니다. SQL 문자열에 사용자의 값을 직접 합치지 않습니다.
    db.execute("INSERT INTO notes (id, owner_id, content) VALUES (?, ?, ?)", (note.id, note.owner_id, note.content))
    db.commit()  # 쓰기 변경을 확정하지 않으면 연결 종료 시 취소될 수 있습니다.
    return note


@app.get("/notes", response_model=list[Note])
def list_notes(user: Annotated[CurrentUser, Depends(get_current_user)], db: Annotated[sqlite3.Connection, Depends(get_db)]):
    rows = db.execute("SELECT id, owner_id, content FROM notes WHERE owner_id = ? ORDER BY id", (user.id,)).fetchall()
    return [dict(row) for row in rows]  # 다른 계정의 행은 SQL 조건에서부터 제외됩니다.


@app.get("/notes/{note_id}", response_model=Note)
def read_note(note_id: str, user: Annotated[CurrentUser, Depends(get_current_user)], db: Annotated[sqlite3.Connection, Depends(get_db)]):
    # id만으로 찾지 않고 소유자 조건을 함께 둡니다. 경로 매개변수 note_id는 요청 URL에서 옵니다.
    row = db.execute("SELECT id, owner_id, content FROM notes WHERE id = ? AND owner_id = ?", (note_id, user.id)).fetchone()
    if row is None:
        # 없는 ID와 타인 소유 ID를 같은 404로 처리해 존재 여부를 구분하지 않습니다.
        raise HTTPException(404, "메모를 찾을 수 없습니다.")
    return dict(row)