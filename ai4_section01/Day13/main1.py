# os.getenv는 프로세스 환경변수에서 설정값을 조회합니다.
import os

# HTTPX는 Supabase SDK에 전달할 통신 객체와 타임아웃을 관리합니다.
import httpx
# .env의 값을 환경변수에 추가합니다. 파일 내용을 직접 파싱하지 않습니다.
from dotenv import load_dotenv
# FastAPI는 요청 처리, Response는 응답 헤더, HTTPException은 오류 응답에 사용합니다.
from fastapi import FastAPI, HTTPException, Request, Response
# 요청 JSON의 형식·타입 검사 실패를 식별하고 JSON 오류 응답을 만듭니다.
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
# Pydantic으로 요청·응답 구조와 이메일·비밀번호 입력 규칙을 선언합니다.
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr
# 공식 SDK로 로그인하고, Auth API 오류와 통신 재시도 오류를 구분합니다.
from supabase import AuthApiError, AuthRetryableError, create_client
from supabase.client import ClientOptions


# lesson02 폴더에서 실행합니다. .env는 현재 작업 폴더를 기준으로 찾습니다.
load_dotenv(    
    override=False,      # 이미 설정된 환경변수가 .env보다 우선합니다.
    interpolate=False,   # 값의 ${...}를 다른 환경변수로 치환하지 않습니다.
)

# 두 번째 인자 ""는 값이 없을 때의 기본값입니다. 비밀값은 출력하지 않습니다.
supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()

if not supabase_url or not supabase_key:
    raise RuntimeError(".env 또는 환경변수의 SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY를 확인하세요.")
if not supabase_url.startswith("https://"):
    raise RuntimeError("SUPABASE_URL에는 https://로 시작하는 Project URL을 넣으세요.")
if not supabase_key.startswith("sb_publishable_"):
    raise RuntimeError("SUPABASE_PUBLISHABLE_KEY에는 publishable 키를 넣으세요.")

# title은 Swagger 문서에 표시할 제목입니다. 로그인 기능을 수행하는 옵션은 아닙니다.
app = FastAPI(title="Supabase Auth - 로그인과 JWT 발급")


class LoginRequest(BaseModel):
    # extra="forbid"는 email/password 외의 추가 필드를 거절합니다.
    model_config = ConfigDict(extra="forbid")
    email: EmailStr  # email-validator를 통해 이메일 형식을 검사합니다.
    # 빈 비밀번호만 거절합니다. 로그인 시 새 비밀번호의 강도 정책을 재검사하지 않습니다.
    # SecretStr는 모델의 문자열 표시를 가릴 뿐, 암호화나 해싱을 하지 않습니다.
    password: SecretStr = Field(min_length=1)


class LoginResponse(BaseModel):
    # 토큰을 호출자에게 전달해야 하므로 응답의 토큰 필드는 str로 선언합니다.
    access_token: str       # 보호 API 요청에 사용할 JWT입니다.
    refresh_token: str      # 새 토큰을 받는 데 쓰는 값이며, JWT로 가정하지 않습니다.
    token_type: str         # 일반적으로 bearer입니다.
    expires_in: int         # 발급 시점 기준 access token의 유효기간(초)입니다.
    expires_at: int | None  # 만료 시각의 Unix timestamp이며, SDK에서 없을 수도 있습니다.
    user_id: str            # 주문·메모 등을 이 사용자와 연결할 식별자입니다.
    email: str | None      # Auth가 돌려준 사용자의 이메일입니다.


# 요청 데이터 검증 실패 시 실행할 오류 처리 함수를 FastAPI에 등록합니다.
# 등록은 서버 시작 시, 아래 함수의 호출은 실제 입력 오류가 발생했을 때 이뤄집니다.
@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request: Request, exc: RequestValidationError):
    # _request는 FastAPI가 전달하는 요청 객체입니다. 여기서는 본문을 읽지 않습니다.
    # 오류의 원본 입력(input)을 제외해 비밀번호가 응답에 되돌아가지 않게 합니다.
    errors = [{"loc": error["loc"], "type": error["type"]} for error in exc.errors()]
    return JSONResponse(
        status_code=422,            # JSON 입력 규칙에 맞지 않는 요청입니다.
        content={"detail": errors}, # 오류 위치와 종류만 JSON 본문으로 보냅니다.
    )


# /auth/login에 POST 요청이 오면 login을 호출하도록 등록합니다.
# response_model은 반환할 JSON의 구조를 검증하고 Swagger에 표시합니다.
@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, response : Response):
    # body에는 검증된 요청 모델, response에는 FastAPI가 제공한 응답 객체가 들어옵니다.
    try:
        # timeout=10.0은 통신 단계별 제한입니다. 전체 작업의 총 10초 제한은 아닙니다.
        # with 블록을 나가면 HTTP 연결 자원을 닫습니다.
        with httpx.Client(timeout=10.0) as http_client:
            supabase = create_client(
                supabase_url,  # 로그인할 계정이 등록된 프로젝트의 URL입니다.
                supabase_key,  # 해당 프로젝트의 publishable 키입니다. 사용자 JWT가 아닙니다.
                options=ClientOptions(
                    # SDK 저장소에 세션을 저장하지 않습니다. 객체 메모리에는 존재할 수 있습니다.
                    persist_session=False,
                    # 요청 처리용 클라이언트이므로 백그라운드 토큰 자동 갱신을 끕니다.
                    auto_refresh_token=False,
                    # 위에서 만든 통신 객체를 사용해 타임아웃과 연결 수명을 관리합니다.
                    httpx_client=http_client,
                ),
            )
            # 실제 로그인 요청은 여기서 전송됩니다. 가입이나 계정 생성을 하지 않습니다.
            result = supabase.auth.sign_in_with_password(
                {
                    "email": str(body.email),  # 로그인할 이메일입니다.
                    # Auth에 보낼 때만 원문을 꺼냅니다. 비밀번호를 strip하거나 출력하지 않습니다.
                    "password": body.password.get_secret_value(),
                }
            )
    except AuthApiError as exc:
        # HTTP 상태만 보지 않고 공식 오류 code를 먼저 확인합니다.
        if exc.code == "invalid_credentials":
            # 존재하지 않는 이메일과 틀린 비밀번호를 같은 안내로 처리합니다.
            raise HTTPException(401, "이메일 또는 비밀번호를 확인하세요.") from None
        if exc.code == "email_not_confirmed":
            raise HTTPException(403, "이메일 확인을 완료한 뒤 로그인하세요.") from None
        if exc.status == 429:
            raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도하세요.") from None
        if exc.status >= 500 or exc.status in (401, 403):
            # 키·프로젝트 설정 오류와 서비스 장애를 잘못된 비밀번호로 단정하지 않습니다.
            raise HTTPException(503, "인증 서비스 상태 또는 연결 설정을 확인하세요.") from None
        # HTTPException의 첫 인자는 상태 코드, 두 번째는 detail 응답 문구입니다.
        raise HTTPException(400, "로그인 요청을 처리할 수 없습니다. Auth 설정을 확인하세요.") from None
    except (AuthRetryableError, httpx.HTTPError):
        raise HTTPException(503, "인증 서비스에 연결할 수 없습니다. 잠시 후 다시 시도하세요.") from None

    # 정상적인 비밀번호 로그인에는 사용자와 세션이 모두 있어야 합니다.
    session = result.session
    user = result.user
    if session is None or user is None:
        raise HTTPException(502, "인증 서비스의 로그인 응답을 확인할 수 없습니다.")

    # 토큰이 포함된 성공 응답을 브라우저·중간 캐시에 저장하지 않도록 요청합니다.
    # 토큰이 로그나 화면에서 자동으로 숨겨진다는 뜻은 아닙니다.
    response.headers["Cache-Control"] = "no-store"

    # 각 이름에 맞춰 SDK 결과를 우리 API의 응답 필드로 옮깁니다.
    return LoginResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        token_type=session.token_type,
        expires_in=session.expires_in,
        expires_at=session.expires_at,
        user_id=user.id,
        email=user.email,
    )


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr = Field(min_length=8, max_length=128)


class SignupResponse(BaseModel):
    message: str


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request: Request, exc: RequestValidationError):
    # 원본 입력(input)을 빼서 잘못 입력한 비밀번호도 응답에 되돌려 보내지 않습니다.
    errors = [
        {"loc": error["loc"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.post("/auth/signup", response_model=SignupResponse)
def signup(body: SignupRequest):
    try:
        # 요청마다 클라이언트를 만들고, 통신이 끝나면 연결 자원을 닫습니다.
        with httpx.Client(timeout=10.0) as http_client:
            supabase = create_client(
                supabase_url,
                supabase_key,
                options=ClientOptions(
                    persist_session=False,
                    auto_refresh_token=False,
                    httpx_client=http_client,
                ),
            )
            supabase.auth.sign_up(
                {
                    "email": str(body.email),
                    "password": body.password.get_secret_value(),
                }
            )
    except AuthApiError as exc:
        if exc.status == 429:
            raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도하세요.") from None
        if exc.status >= 500 or exc.status == 401:
            raise HTTPException(503, "인증 서비스 상태 또는 연결 설정을 확인하세요.") from None
        raise HTTPException(400, "가입 요청을 처리할 수 없습니다. 입력과 Auth 설정을 확인하세요.") from None
    except (AuthRetryableError, httpx.HTTPError):
        raise HTTPException(503, "인증 서비스에 연결할 수 없습니다. 잠시 후 다시 시도하세요.") from None

    return SignupResponse(
        message="가입 요청을 처리했습니다. 이메일 확인 설정이 켜져 있다면 받은 메일을 확인하세요."
    )

#Bearer JWT로 현재 사용자 확인