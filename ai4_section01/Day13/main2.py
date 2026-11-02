# os는 환경변수 조회, Annotated는 매개변수에 Header/Depends 정보를 붙이는 표준 기능입니다.
import os
from typing import Annotated
# HTTPX는 타임아웃과 연결 수명, python-dotenv는 .env 로딩을 담당합니다.
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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

# title은 Swagger 화면의 제목이며 인증 정책을 바꾸지 않습니다.
app = FastAPI(title="3차시 - Bearer JWT로 현재 사용자 확인")


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


# HTTPBearer를 사용하면 OpenAPI에 Bearer 인증 스킴과 Swagger의 Authorize UI가 등록됩니다.
bearer_scheme = HTTPBearer(auto_error=False)


@app.get("/me", response_model=CurrentUser)
def me(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
):
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials.strip():
        raise HTTPException(401, "Authorization: Bearer 토큰이 필요합니다.", headers={"WWW-Authenticate": "Bearer"})
    # 헤더 형식 확인과 JWT 진위 검증은 서로 다릅니다. 실제 검증은 get_user가 담당합니다.
    return verified_user(credentials.credentials.strip())