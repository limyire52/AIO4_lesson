# 새 세션에서 이전 대화 이어가기

## 1. 학습목표

- 기존 대화방 ID로 새 세션을 발급하며 최근 기록을 함께 조회한다.
- 최근 N개를 선택한 뒤 시간 흐름에 맞는 순서로 돌려준다.
- 만료·종료 뒤에도 DB 원본에서 대화를 이어간다.

## 2. 중요 알고리즘 및 코드를 읽을 때 반드시 알아야 할 내용

### 최근 기록을 읽고 새 세션으로 이어가기

5차시에서는 종료·만료 후 연결 정보가 사라져도 메시지 원본은 DB에 남았다. 이번 새 중심 개념은 영구 기록을 바탕으로 대화 문맥을 다시 가져오는 것이다. POST /conversations/{conversation_id}/resume은 DB 확인 → 최근 N개 메시지 SELECT → 순서 반전 → 새 Redis 세션 발급 → 이력과 세션 ID 응답 순서로 동작한다.

기존 세션 ID를 되살리지 않는다. 같은 대화방에 새로운 세션 ID를 만든다. 기존에 유효한 다른 세션은 자동 종료하지 않으며 자신의 TTL 동안 유지된다. DB를 읽은 뒤 Redis 발급에 실패하면 503이고 기록은 그대로다. 재요청해도 메시지 원본을 추가하지 않지만 세션 발급이 여러 번 일어날 수 있다.

### LIMIT과 결과 순서

`limit: int = Query(default=10, ge=1, le=50)`은 URL의 ?limit=2 값을 정수로 읽는다. 생략하면 10개, 0·51·문자열 abc는 422다. ge는 최솟값 포함, le는 최댓값 포함이다. 상한을 둬 한 번에 읽는 기록량을 제한한다.

id가 1, 2, 3일 때 ORDER BY id DESC LIMIT 2는 3, 2를 선택한다. Python의 rows.reverse()가 선택된 목록을 2, 3으로 바꾼다. 먼저 ASC LIMIT 2를 하면 1, 2가 돼 오래된 두 개를 고르게 된다. 여기서 순서는 메시지 ID 순이며 동시 요청의 엄밀한 완료 시각 순서라는 보장은 없다. 반환한 최근 N개는 전체 이력이 아니다. 생성형 AI 호출은 하지 않고 사람이 읽을 기록을 복원한다.
### 유지하는 구조와 코드 읽기 순서

FastAPI가 요청을 검사하고 Redis가 현재 세션의 대화방 ID를 돌려주면 psycopg가 Supabase PostgreSQL을 읽고 쓴다. 메시지 원본은 DB에만 두며 Redis 키는 차시별 l06 접두어로 구분한다. 이전 차시 세션 ID는 재사용하지 말고 이 차시 API에서 새로 발급한다. 같은 DB의 kdt_hybrid 스키마와 원본 기록은 계속 사용할 수 있다.

일반 def 경로에서 동기 드라이버를 호출한다. @app.get/post/delete는 경로 등록이며 요청이 와야 함수가 실행된다. 예외 처리기 데코레이터도 등록이고 해당 드라이버 예외가 발생할 때 FastAPI가 호출한다. RedisError와 psycopg.Error는 503으로 변환하며 접속 URI나 예외 원문을 응답에 싣지 않는다. 401·404·409·422는 각 함수와 입력 검사에서 정한다.

| 구문·옵션 | 코드에서의 역할 |
|---|---|
| Header(default=None) | X-Session-Id 헤더를 읽으며 누락 시 None이다. 밑줄을 하이픈으로 바꾸는 기본 규칙을 사용한다. |
| ConfigDict(extra="forbid", str_strip_whitespace=True) | 본문의 미정의 필드를 거절하고 문자열 양끝 공백 제거 후 길이를 검사한다. |
| Field(min_length=1, max_length=100/1000) | 제목 1~100자, 메시지 1~1000자 제한. 공백만 있는 입력을 거절한다. |
| psycopg.connect의 connect_timeout=5 | DB 연결 수립 대기 제한(초). SQL 실행 시간 제한은 아니다. |
| sslmode="require", row_factory=dict_row | DB TLS를 요구하고 기본 튜플 대신 열 이름 딕셔너리로 행을 읽는다. |
| Redis.from_url의 decode_responses=True | 기본 False의 bytes 대신 문자열 결과를 얻는다. |
| socket_connect_timeout=3 / socket_timeout=3 | Redis 연결 수립/소켓 응답 대기 제한(초). 재시도 포함 전체 HTTP 시간을 뜻하지 않는다. |
| client.set(..., ex=SESSION_TTL_SECONDS) | 값과 만료를 한 명령으로 저장한다. ex를 생략하면 새 키에 만료가 붙지 않는다. |
| conn.execute(SQL, 값 튜플) | 커서를 만들어 SQL을 보내고 반환한다. %s에 별도 값을 바인딩한다. |
| fetchone / fetchall | 한 행 또는 목록 읽기. 한 행이 없으면 None, 목록이 없으면 []다. |

연결의 with 블록은 정상 종료 시 commit, 예외 시 rollback 후 DB 연결을 닫는다. Redis의 with는 클라이언트 자원을 정리하며 서버 자체를 종료하지 않는다. 값 한 개를 SQL에 전달할 때 (value,)의 쉼표가 필요하다. SQL은 main.py 안에 직접 작성하고 사용자 입력을 f-string SQL로 합치지 않는다. CREATE ... IF NOT EXISTS는 기존 객체의 구조를 자동 수정하지 않는다.

세션 유효성의 판단 시점은 Redis GET이다. 통과한 뒤 DB 처리 중 만료되더라도 진행 중인 요청을 자동 취소하지 않는다. GET과 TTL이 별도 명령이면 중간에 만료될 수 있어 -2를 다시 검사한다. TTL -1은 만료 미설정, 0은 곧 만료될 수 있는 상태다. 실습 외부에서 키를 임의 변경하지 않는다.

로그인·대화방 소유권 검증은 없다. 대화방 ID를 아는 사람이 새 세션을 발급할 수 있으므로 사용자 인증을 구현한 예제로 해석하지 않는다. 기본 루프백 주소에서 실습한다. DB와 Redis 사이의 작업은 자동으로 하나의 트랜잭션이 되지 않는다.

### Wikidocs 검색·본문/코드 확인과 공식 문서 대조

확인일: 2026-11-03.

검색어: `site:wikidocs.net FastAPI 대화 이력 limit order by`.

| 실제 확인한 자료 | 참고 패턴 | 현재 반영과 변경 이유 |
|---|---|---|
| [정말 빠른 FastAPI — 쿼리 파라미터 값 얻기](https://wikidocs.net/162711) | limit 정수 입력과 기본값 | resume_conversation의 limit에 반영. 메모리 슬라이스를 매개변수 SQL LIMIT로 바꾸고 Query로 허용 범위를 둔다. |
| [초!간단 DB 연동 — Redis 캐시 기초](https://wikidocs.net/428905) | Redis GET·만료 저장 | 새 세션 발급에 유지. 메시지 원본을 Redis에 캐싱하지 않고 DB에서 최근 기록을 읽는다. |

DB 호출은 [Psycopg 기본 사용법](https://www.psycopg.org/psycopg3/docs/basic/usage.html), 입력 범위는 [FastAPI 쿼리 검증](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/), SQL 선택은 [PostgreSQL SELECT](https://www.postgresql.org/docs/current/sql-select.html)로 대조했다.

별도로 명시하지 않은 자료 수정일·원문 패키지 버전은 확인하지 못했다. 필요한 패턴을 자체 상담 예제로 재구성했으며 인기·최신 여부를 추정하지 않는다.

## 3. 코드 제공

### ① 실행 폴더와 Python 확인

ZIP을 풀어 현재 차시 폴더를 `C:\AI4\hybrid_backend\lesson06`에 둔다. 다른 위치에 풀었다면 경로만 실제 위치로 바꾼다. 명령은 Windows CMD에서 실행한다. 이전 차시 Uvicorn이 8000 포트를 사용 중이면 그 터미널에서 Ctrl+C로 종료한다.

```bat
cd /d C:\AI4\hybrid_backend\lesson06
python --version
python -c "import sys; print(sys.executable)"
```

`cd /d`는 드라이브와 폴더를 함께 바꾸며 `--version`은 Python 버전을 조회한다. Python 3.10 이상을 사용한다. `-c`는 뒤의 Python 코드를 실행하고 sys.executable은 실제 실행 파일 경로다. 정상 가상환경을 이미 활성화했다면 재사용한다. 표시되는 (.venv)만으로 정상 여부를 판단하지 않는다.

새 가상환경이 필요한 경우 현재 차시 폴더에서 다음을 실행한다.

```bat
python -m venv .venv
.venv\Scripts\activate
python -c "import sys; print(sys.executable)"
```

`-m venv`는 현재 Python으로 가상환경을 만들고 .venv는 저장 폴더다. activate는 현재 CMD의 실행 경로를 바꾼다. 새 환경을 만들었다면 마지막 출력이 현재 차시의 `.venv\Scripts\python.exe`여야 한다. 가상환경을 복사하거나 이동해서 사용하지 않는다.

```bat
python -m pip install fastapi==0.162.0 uvicorn==0.54.0 "psycopg[binary]==3.3.6" redis==8.1.0 python-dotenv==1.2.4
```

`python -m pip`는 현재 Python의 설치 도구 실행, install은 설치, ==는 버전 지정이다. fastapi는 API와 Swagger, uvicorn은 서버, redis는 Python Redis 클라이언트(서버 자체는 아님), python-dotenv는 .env 로딩을 담당한다. psycopg[binary]는 PostgreSQL 드라이버와 사전 빌드 바이너리를 설치하며 따옴표는 대괄호 포함 항목을 묶는다. 이 버전은 제작 환경에서 사용한 직접 의존성 목록이며 전체 하위 의존성 잠금 파일은 아니다.

### ② Redis 준비

Docker Desktop을 실행한다. 1차시에서 만든 `kdt-hybrid-redis`가 있다면 새로 만들지 말고 다음 명령으로 시작한다.

```bat
docker start kdt-hybrid-redis
docker ps --filter name=kdt-hybrid-redis
docker exec kdt-hybrid-redis redis-cli PING
```

start는 기존 컨테이너 시작, ps는 실행 목록 조회, --filter name=...는 이름 필터다. STATUS가 Up이고 PORTS에 `127.0.0.1:6379->6379/tcp`가 있어야 한다. exec는 실행 중 컨테이너 안에서 명령을 수행하며 kdt-hybrid-redis는 대상 이름, redis-cli는 Redis 명령 도구, PING은 서버 응답 점검이다. 정상 응답은 PONG이다. 이는 컨테이너 내부 통신 확인이며 Python에서의 연결까지 검증하지는 않는다. 모든 명령은 호스트 CMD에 입력한다.

컨테이너가 아예 없고 PC 6379 포트가 비어 있을 때만 아래 명령으로 생성한다. 다른 수업 Redis가 해당 포트를 사용 중이면 기존 서버를 재사용하고 .env의 주소를 맞춘다.

```bat
docker run -d --name kdt-hybrid-redis -p 127.0.0.1:6379:6379 redis:7.4 redis-server --save "" --appendonly no
```

run은 새 컨테이너 생성·시작, -d는 백그라운드, --name은 이름 지정이다. -p는 PC의 127.0.0.1:6379를 컨테이너 6379로 연결한다. redis:7.4는 7.4 계열 이미지이며 세부 패치는 달라질 수 있다. redis-server는 내부 실행 프로그램, --save ""는 빈 문자열을 전달해 주기적 RDB 저장을 끄고 --appendonly no는 AOF 기록을 끈다. 이 설정의 전용 컨테이너는 Redis 프로세스를 재시작하면 세션을 복원하지 않는다. 모든 Redis의 일반 성질로 해석하지 않는다. 생성 시 긴 컨테이너 ID가 나오며 이름이 이미 있으면 run을 반복하지 않는다.

### ③ .env 설정

```bat
copy .env.example .env
notepad .env
```

copy는 예시 설정 복사, notepad는 편집기 실행이다. 기존 .env가 있으면 덮어쓰지 말고 필요한 키를 확인한다. 내용은 다음과 같다.

```dotenv
SUPABASE_DB_URL='postgresql://postgres.PROJECT_REF:ENCODED_PASSWORD@POOLER_HOST:5432/postgres'
REDIS_URL='redis://127.0.0.1:6379/0'
SESSION_TTL_SECONDS=300
```

REDIS_URL은 Python이 접근하는 Redis 주소다. /0은 논리 DB 0번이다. 로컬 예제에는 비밀번호가 없다.

Supabase 프로젝트 → Connect → Session pooler에서 URI를 복사해 SUPABASE_DB_URL에 넣는다. 호스트·사용자·포트는 본인 화면을 사용하며 DB 비밀번호를 채운다. 위 값은 가짜 예시다. API 키나 프로젝트 URL을 DB URI 대신 쓰지 않는다. 비밀번호의 URI 예약문자는 percent-encoding한다(#은 %23, 공백은 %20). .env의 작은따옴표는 URI 인코딩을 대신하지 않는다. 비밀번호 원문을 무조건 strip하지 않는다.

load_dotenv는 현재 작업 폴더의 .env를 환경변수에 올리고 os.getenv는 값을 읽는다. override=False는 기존 프로세스 환경변수를 우선하며 interpolate=False는 ${...} 치환을 막는다. .env가 없어도 필수 환경변수가 있으면 실행 가능하다. 로딩 여부는 접속 성공 판정이 아니다. REDIS_URL에는 쿼리 옵션을 추가하지 않는다. URL 쿼리 옵션이 Python에서 지정한 연결 옵션보다 우선할 수 있기 때문이다.

SESSION_TTL_SECONDS는 문자열로 읽어 양의 정수로 변환한다. 300은 발급 후 300초라는 뜻이다. 누락·공백·abc·0·음수는 시작 시 거절한다. .env 수정 후에는 Uvicorn을 Ctrl+C로 종료하고 재시작한다. 기존 Redis 키의 만료 시간은 설정 수정만으로 바뀌지 않는다.

`.gitignore`는 다음과 같다. 실제 접속값과 가상환경을 Git에 포함하지 않는다.

```gitignore
.env
.venv/
__pycache__/
*.pyc
```

배포 파일은 lesson06.md, main.py, .env.example, .gitignore, lesson_scope.json이다. lesson_scope.json은 내부 품질 검증 메타데이터로 접속 설정이나 실행 파일이 아니다. 다른 차시의 Python 파일이나 SQL 파일을 복사하지 않는다.

### ④ main.py 전체 코드

```python
"""6교시: 하이브리드 대화 백엔드 실습."""
import os  # .env에서 로드된 환경변수를 조회한다.
from uuid import UUID, uuid4  # UUID는 입력 검사, uuid4는 새 대화방 ID 생성에 쓴다.

import psycopg  # PostgreSQL 동기 드라이버다.
from psycopg.rows import dict_row  # 컬럼 이름을 키로 하는 딕셔너리 행을 받는다.
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Query
from redis import Redis, RedisError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

# 현재 작업 폴더에서 로드한다. 기존 환경변수를 우선하고 ${...}는 치환하지 않는다.
load_dotenv(".env", override=False, interpolate=False)
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
            CREATE TABLE IF NOT EXISTS kdt_hybrid.conversations (
                id UUID PRIMARY KEY,
                title VARCHAR(100) NOT NULL CHECK (length(trim(title)) > 0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kdt_hybrid.messages (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                conversation_id UUID NOT NULL
                    REFERENCES kdt_hybrid.conversations(id),
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
            """INSERT INTO kdt_hybrid.conversations (id, title)
               VALUES (%s, %s) RETURNING id, title, created_at""",
            (conversation_id, body.title),  # %s 자리에 바인딩할 값. 문자열로 합치지 않는다.
        ).fetchone()  # RETURNING이 돌려준 새 행 하나를 읽는다.
    return row  # with 종료로 commit한 뒤 FastAPI가 UUID/시간을 JSON으로 변환한다.


@app.get("/conversations")
def list_conversations():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM kdt_hybrid.conversations ORDER BY created_at, id"
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
            "SELECT id FROM kdt_hybrid.conversations WHERE id = %s", (body.conversation_id,)
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
    session_id = str(uuid4())
    with connect_redis() as client:
        client.set(
            f"kdt:hybrid:l06:session:{session_id}",  # 3차시의 임의 ID 세션과 분리한다.
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
        raw = client.get(f"kdt:hybrid:l06:session:{session_id}")
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
            "SELECT id FROM kdt_hybrid.conversations WHERE id = %s", (conversation_id,)
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
            "SELECT id FROM kdt_hybrid.conversations WHERE id = %s", (conversation_id,)
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
        ttl = client.ttl(f"kdt:hybrid:l06:session:{UUID(x_session_id)}")
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
            "SELECT id FROM kdt_hybrid.conversations WHERE id = %s", (conversation_id,)
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
    with connect_redis() as client:
        renewed = client.expire(
            f"kdt:hybrid:l06:session:{UUID(x_session_id)}",
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
        removed = client.delete(f"kdt:hybrid:l06:session:{UUID(x_session_id)}")
    if not removed:
        raise HTTPException(status_code=401, detail="세션이 만료되었습니다.")
    return {"ended": True}


# 기존 대화방에 새 세션을 발급하며 최근 기록도 함께 읽는다.
@app.post("/conversations/{conversation_id}/resume", status_code=201)
def resume_conversation(
    conversation_id: UUID,
    limit: int = Query(default=10, ge=1, le=50),  # 최근 메시지 개수, 1~50으로 제한한다.
):
    with connect_db() as conn:
        found = conn.execute(
            "SELECT id FROM kdt_hybrid.conversations WHERE id = %s", (conversation_id,)
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="대화방을 찾을 수 없습니다.")
        rows = conn.execute(
            """SELECT id, conversation_id, content, created_at
               FROM kdt_hybrid.messages WHERE conversation_id = %s
               ORDER BY id DESC LIMIT %s""",
            (conversation_id, limit),  # 먼저 최근 N개를 고른다.
        ).fetchall()
    rows.reverse()  # 고른 N개만 오래된 것부터 표시한다. 모든 이력이란 뜻은 아니다.
    session_id = str(uuid4())
    with connect_redis() as client:
        client.set(
            f"kdt:hybrid:l06:session:{session_id}",
            str(conversation_id),
            ex=SESSION_TTL_SECONDS,  # 복원할 때도 반드시 만료를 함께 지정한다.
        )
    return {"session_id": session_id, "expires_in": SESSION_TTL_SECONDS,
            "conversation_id": str(conversation_id), "messages": rows}


# 초기화는 명시적으로 실행한다. Uvicorn import 시 DB를 변경하지 않는다.
if __name__ == "__main__":
    try:
        init_db()
    except psycopg.Error:
        raise SystemExit("DB 준비 실패: 접속 설정과 스키마 생성 권한을 확인하세요.") from None
```

### ⑤ DB 준비·서버 실행

현재 lesson06 CMD에서 실행한다.

```bat
python main.py
python -m uvicorn main:app --port 8000
```

첫 명령은 DB 스키마와 테이블을 준비하고 종료하며 정상 예상 출력은 `테이블 준비 완료`다. 기존 기록을 삭제하지 않는다. `-m uvicorn`은 서버 모듈 실행, main:app은 main.py의 app 객체, --port 8000은 접속 포트다. 기본 127.0.0.1에서 실행한다. 서버는 한 프로세스로 실행하며 해당 CMD를 점유한다. Application startup complete 안내 후 다음 주소를 연다.

```text
http://127.0.0.1:8000/docs
```

Uvicorn의 import는 __main__ 분기를 실행하지 않으므로 DB 준비 명령을 먼저 수행한다. 종료는 서버 CMD의 Ctrl+C, 재시작은 같은 Uvicorn 명령이다. 설정 변경 시에도 이 순서로 재시작한다.

### ⑥ 공통 시작: 대화방 생성·목록·세션 발급

POST /conversations → Try it out → 아래 JSON → Execute한다.

```json
{"title":"상담-06"}
```

201 응답의 id 전체를 복사한다. GET /conversations → Try it out → Execute로 같은 제목과 id를 찾을 수 있다. 재실행 시 같은 제목의 방도 새 ID로 추가된다. 기존 방을 이어 쓰려면 목록에서 원래 ID를 찾는다.

POST /sessions → Try it out → 아래 본문의 따옴표 안을 실제 대화방 id 전체로 교체 → Execute한다.

```json
{"conversation_id":"실제_대화방_UUID_전체"}
```

자리표시자는 그대로 입력하지 않는다. 예를 들어 id가 11111111-1111-4111-8111-111111111111이라면 그 값으로 바꾼다. 이는 합성 형식 예시이며 실제 응답값을 사용한다. 201 응답에서 이번에는 session_id 전체를 복사한다. expires_in은 발급 시 설정값이며 남은 시간 실측은 아니다.

GET /session → Try it out → x-session-id 칸에 session_id 전체를 따옴표 없이 입력 → Execute한다. 200 응답의 conversation_id와 ttl을 확인한다. 각 API의 헤더 입력 칸은 별도로 채운다. 대화방 id와 session_id를 바꿔 쓰지 않는다. 읽고 입력하는 동안에도 TTL은 줄어든다.

### ⑦ 메시지 저장·조회 기본 확인

POST /messages → Try it out → x-session-id에 현재 세션 ID → 다음 본문 → Execute한다.

```json
{"content":"첫 번째 기록"}
```

201 응답의 id·conversation_id·content를 확인한다.

GET /messages → Try it out → x-session-id에 같은 세션 ID → Execute하면 200 배열에 방금 메시지가 보여야 한다. 별도 대화방 B를 만들고 B에 세션을 발급해 GET /messages를 호출하면 새 방은 []다. A의 세션으로 돌아오면 A 기록이 유지돼야 한다.
### ⑧ 최근 두 메시지를 복원하기

현재 세션 헤더로 POST /messages를 두 번 더 실행해 {"content":"두 번째 기록"}, {"content":"세 번째 기록"}을 차례로 저장한다. GET /messages에 세 기록이 있는지 확인한다.

DELETE /session → Try it out → 현재 헤더 → Execute한다. 200 뒤 이전 헤더로 GET /messages를 하면 401이다.

POST /conversations/{conversation_id}/resume → Try it out → 경로 conversation_id에 A의 대화방 id → limit에 2 → Execute한다. 이 요청은 세션 헤더가 필요 없다. 201 응답의 messages에 두 번째·세 번째 기록 순서로 나오는지 확인한다. messages 길이는 최대 limit이며 기존 기록이 두 개보다 적으면 더 적게 나온다.

응답 session_id 전체를 새로 복사해 GET /messages 헤더에 넣는다. 이 API는 전체 기록 목록을 반환하므로 세 메시지가 모두 보여야 한다. resume의 최근 두 개와 전체 조회 결과를 혼동하지 않는다.

limit을 0, 51, abc로 바꾸면 각각 422다. 존재하지 않는 00000000-0000-0000-0000-000000000000 대화방은 404다. 메시지가 없는 새 대화방을 복원하면 201과 messages=[]가 정상이다.

연장 동작도 유지된다. POST /session/renew에 새 헤더를 넣어 200을 확인하고 GET /session에서 남은 시간을 확인한다. 만료 재현은 TTL을 15로 바꾸고 서버 재시작 → 새 발급 → 15초 이상 대기 → 이전 헤더 401 → 같은 대화방 resume 순이다. 끝나면 TTL을 300으로 되돌리고 서버를 재시작한다.
### Redis 직접 확인과 실행 복구

두 번째 CMD에서 SESSION_ID_FULL 자리에 실제 session_id 전체를 넣는다.

```bat
set SESSION_ID=SESSION_ID_FULL
docker exec kdt-hybrid-redis redis-cli GET kdt:hybrid:l06:session:%SESSION_ID%
docker exec kdt-hybrid-redis redis-cli TTL kdt:hybrid:l06:session:%SESSION_ID%
```

CMD set은 현재 CMD 변수를 만들며 = 주변에 공백을 두지 않는다. %SESSION_ID%는 이 CMD가 값을 치환한다. 새 CMD에서는 다시 설정한다. Redis SET과는 다른 명령이다. GET 결과는 대화방 UUID, TTL은 남은 초다. 종료·만료 후에는 (nil)과 -2가 예상된다. 새 세션 발급 후에는 Swagger 헤더와 CMD 변수도 새 값으로 갱신한다. 조회 명령은 키를 바꾸지 않는다.

| 오류·상태 | 확인·재개 |
|---|---|
| 서버 시작 때 필수 설정 누락 | 현재 lesson06 폴더와 .env 키·빈 값 확인 후 재시작 |
| DB 준비 실패·API 503 | Supabase 프로젝트 실행, Session pooler 주소·DB 비밀번호·DDL 권한, 초기화 실행 확인 |
| Redis 503 | Docker Desktop·컨테이너 실행·포트·REDIS_URL 확인 |
| 세션 401 | 재발급 또는 복원한 응답의 session_id 전체로 헤더·CMD 변수 변경 |
| 본문 422 | 필수 키·UUID·공백·길이·미정의 필드 확인 |
| 대화방 404 | GET /conversations에서 실제 ID 확인 |

가상환경이 과거 Python/Conda 경로를 찾지 못하면 deactivate → where python → python --version으로 외부 Python부터 확인한다. 정상이라면 `ren .venv .venv_backup`으로 백업한다(이름이 있으면 다른 백업명). `python -m venv .venv` → 활성화 → sys.executable 확인 → 패키지 재설치 순으로 복구한다. where는 실행 후보 조회, ren은 폴더 이름 변경이다. 외부 Python도 실패하면 설치·경로 문제부터 해결한다. 실제 URI·비밀번호는 오류 질문이나 프롬프트에 넣지 않는다.

Redis 프로세스가 유지되고 TTL이 남아 있으면 API 서버 재시작 후에도 세션을 사용할 수 있다. 위 준비에서 영속화를 끈 Redis 컨테이너를 중지·시작하면 세션은 복원되지 않지만 DB 기록은 남는다. 서버 종료·세션 종료·DB 원본 삭제는 서로 다른 작업이다.

### 검증 범위

FastAPI 테스트 클라이언트와 로컬 Redis, PGlite(PostgreSQL WASM 엔진) 및 psycopg 연결 대역으로 정상·실패 요청과 SQL 동작을 검사했다.

실제 Supabase의 TLS·계정 권한, Windows CMD·Docker Desktop, 원격 PostgreSQL 동시 요청은 직접 검증하지 못했다. 위 실습 절차로 본인 환경의 연결·재시작 보존을 확인한다. 모의 연결 검사나 PostgreSQL WASM 검사만으로 원격 Supabase 성공을 주장하지 않는다.

## 4. Vibe 코딩에 유용한 프롬프트

### 복원 순서와 개수 검토

```text
lesson06/main.py를 읽어줘.
기록이 1,2,3일 때 resume?limit=2가 2,3 순으로 반환하는지 검사해줘. 종료·만료 후 같은 대화방에 새 세션을 만들고 이전 기록을 읽는 흐름을 추적해줘. limit=0/51/abc는 422, 없는 방은 404여야 해. LLM 호출·메모리 원본 저장·중복 방지는 추가하지 마.
SQL과 실행 로직을 main.py 하나에 유지하고 오류가 있으면 최소 수정해줘.
.env의 실제 값·비밀번호·키는 읽거나 출력하지 말고 합성 설정으로 검사해줘.
수정 시 문서의 전체 코드도 동일하게 갱신하고, 실행한 검사와 미검증을 구분해줘.
```