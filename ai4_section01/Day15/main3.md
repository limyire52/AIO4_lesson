# 세션을 통해 메시지 저장·조회 API 연결하기

## 1. 학습목표

- Supabase의 영구 기록과 Redis의 임시 연결 정보를 하나의 요청에서 사용한다.
- 실제 대화방에 세션을 발급하고 X-Session-Id 헤더로 메시지를 저장·조회한다.
- 세션이 가리키는 대화방만 조회되는지 확인한다.
- 세션 만료 후에도 메시지는 DB에 남으며 새 세션으로 다시 조회됨을 확인한다.

## 2. 중요 알고리즘 및 코드를 읽을 때 반드시 알아야 할 내용

### 2차시와 3차시를 연결하는 지점

2차시에는 URL의 conversation_id로 DB를 조회했다. 3차시에는 Redis에 session_id → conversation_id를 저장했다. 이번에는 메시지 요청의 X-Session-Id 헤더를 읽어 Redis에서 대화방 ID를 찾고, 그 ID로 Supabase에 접근한다. 메시지 요청 본문에는 conversation_id를 받지 않는다.

| 요청 | 입력 | 수행 작업 | 정상 응답 |
|---|---|---|---|
| POST /conversations | title 본문 | DB 대화방 생성 | 201 |
| GET /conversations | 없음 | DB 대화방 목록 | 200 |
| POST /sessions | conversation_id 본문 | DB 존재 확인 후 Redis SET EX | 201 |
| POST /messages | X-Session-Id 헤더, content 본문 | Redis 세션 조회 후 DB 메시지 저장 | 201 |
| GET /messages | X-Session-Id 헤더 | Redis 세션 조회 후 DB 기록 조회 | 200 |

대화방 생성·목록은 새 세션의 연결 대상을 만들고 찾기 위해 유지한다. 메시지 저장·조회는 헤더 방식으로 통일한다. 3차시의 세션 조회 API와 대화방 ID 직접 메시지 API는 이번 실행 파일에 넣지 않는다. 모든 SQL과 실행 로직은 main.py 안에 있다.

### 메시지 요청 한 번을 따라가기

1. FastAPI가 메시지 본문과 헤더를 읽는다. 본문이 잘못되면 422다.
2. resolve_conversation이 헤더 존재와 UUID 형식을 확인한다. 없거나 틀리면 401이다.
3. Redis에서 kdt:hybrid:l04:session:세션ID를 GET한다. 없으면 401이다.
4. 저장된 대화방 ID를 UUID로 해석한다. 저장 형식 이상이면 503이다.
5. DB에서 해당 대화방을 찾는다. 없으면 404다.
6. POST는 메시지를 INSERT하고 commit 후 201, GET은 목록을 200으로 응답한다.

세션을 찾지 못한 요청은 메시지 함수의 DB 접근까지 가지 않는다. 이 코드의 세션 유효성 판정 시점은 Redis GET 시점이다. 통과한 뒤 DB 작업 중 만료되더라도 이미 진행 중인 요청을 취소하지 않는다. TTL 연장도 하지 않는다.

### Header와 두 종류 ID

`x_session_id: str | None = Header(default=None)`에서 Header는 쿼리 문자열이 아닌 HTTP 헤더를 읽게 한다. 기본 밑줄→하이픈 변환으로 x_session_id가 X-Session-Id에 연결된다. 헤더 이름은 대소문자를 구분하지 않는다. default=None은 헤더 누락 시 None으로 받고 함수에서 401을 정하기 위해 사용한다. Header를 생략하면 같은 방식으로 헤더를 읽지 않는다.

대화방 ID는 POST /sessions의 본문에 넣는다. 응답 session_id는 POST·GET /messages의 헤더에 넣는다. 두 값 모두 UUID라 형식만 보면 비슷하지만 용도가 다르다. session_id를 대화방 생성 결과 id와 바꿔 쓰면 정상 조회가 되지 않는다.

3차시 키는 l03, 이번 키는 l04로 구분한다. 3차시에는 DB에 없는 임의 ID도 세션 값으로 저장했으므로 그 세션을 이번 차시에서 재사용하지 않는다. 같은 Redis 서버를 재사용해도 POST /sessions에서 새로 발급한다.

### 저장 책임과 실패 범위

Supabase에는 대화방·메시지 원본을 보관한다. Redis에는 대화방 ID 연결과 TTL만 둔다. 세션 만료가 DB DELETE를 실행하지 않으므로 기록이 남는다. 같은 대화방에 새 세션을 발급하면 기존 메시지를 읽을 수 있다.

DB와 Redis는 자동으로 하나의 트랜잭션이 되지 않는다. POST /sessions는 DB 확인 후 Redis에 저장하고, 메시지는 Redis 확인 후 DB에 저장한다. DB 저장 성공 후 응답을 못 받았다고 POST를 재전송하면 현재 코드는 메시지가 중복될 수 있다. 이번 차시는 단순한 정상·실패 흐름까지 다룬다.

로그인·소유권 검증은 없다. 누구나 대화방 ID를 알고 세션을 발급할 수 있어 실제 사용자 접근 제어로 사용할 수는 없다. 기본 루프백 주소에서 실습한다. 여기서 401은 학습 예제의 세션 누락·무효 정책이다.

### 주요 SQL과 연결 옵션

| 기능 | 현재 동작 |
|---|---|
| 전용 kdt_hybrid 스키마 | 2차시와 같은 테이블을 사용해 기존 기록을 이어 읽는다. |
| IF NOT EXISTS | 기존 객체 생성 건너뛰기. 열 구조 자동 갱신은 하지 않는다. |
| PRIMARY KEY / REFERENCES | 행 식별 및 메시지의 대화방 참조 관계 보장. |
| %s와 별도 값 튜플 | 사용자 입력을 SQL 문자열에 직접 합치지 않는다. 값 하나면 (value,)로 쓴다. |
| RETURNING / fetchone | INSERT한 행을 즉시 읽는다. conn.execute는 커서를 반환한다. |
| dict_row / fetchall | 열 이름 딕셔너리의 목록을 읽는다. 메시지가 없으면 []다. |
| ORDER BY id | 결과를 메시지 ID 오름차순으로 조회. 엄밀한 동시 완료 시각 순서 보장은 아니다. |

with connect_db 블록은 정상 종료 시 commit, 예외 시 rollback 후 연결을 닫는다. connect_timeout=5는 연결 수립 제한(초)이고 SQL 전체 실행 제한은 아니다. sslmode=require는 DB 연결에 TLS를 요구한다. row_factory=dict_row는 기본 튜플 대신 딕셔너리 결과를 지정한다.

Redis의 decode_responses=True는 기본 bytes 대신 문자열을 반환한다. socket_connect_timeout=3은 연결 수립, socket_timeout=3은 소켓 응답 대기 제한이다. 두 옵션은 재시도 포함 전체 HTTP 시간을 3초로 제한하는 뜻이 아니다. with 종료 시 해당 클라이언트 자원을 정리한다. SET의 ex는 발급 시부터 흐르는 고정 TTL이며 생략 시 새 키에 만료가 붙지 않는다. 이번 코드로 생성한 세션 키를 외부에서 수정하지 않는다.

ConversationCreate와 MessageCreate는 ConfigDict로 미정의 필드를 금지하고 양끝 공백을 제거한 뒤 Field로 title 1~100자, content 1~1000자를 검사한다. SessionCreate는 UUID 형식 검사 후 DB 존재 여부도 확인한다. 경로·오류 처리기 데코레이터는 등록이며 실제 요청·해당 드라이버 예외가 발생할 때 FastAPI가 호출한다. 동기 드라이버는 일반 def 함수에서 사용한다.

### Wikidocs 검색과 코드 반영

확인일: 2026-11-03. `site:wikidocs.net FastAPI Header 헤더`, `site:wikidocs.net Redis 세션 set ex ttl Python`으로 검색해 본문과 실제 코드를 확인했다. SQL 관련 자료는 2차시에서 확인한 패턴을 유지한다.

| 자료 | 참고한 패턴 | 반영 위치와 변경 이유 |
|---|---|---|
| [실전 TODO 앱 — 헤더 파라미터 사용하기](https://wikidocs.net/280171) | Header(default=None), 사용자 정의 헤더 수신 | 메시지 API의 X-Session-Id에 적용. 예제 헤더 이름을 세션 ID로 바꾸고 별도 api_client.py 대신 Swagger로 전송한다. |
| [초!간단 DB 연동 — Redis 캐시 기초](https://wikidocs.net/428905) | Redis 조회와 만료 저장 | connect_redis·create_session·resolve_conversation에 적용. 응답 캐시 대신 세션 연결값만 보관하며 SQL 결과는 DB에서 읽는다. |
| [함께해요 파이썬 생태계 — PostgreSQL 파이썬 어댑터](https://wikidocs.net/226761) | 매개변수 SQL, 연결과 결과 읽기 | DB 생성·저장·조회에 적용. 원문의 비동기 패턴은 동기 API로 재구성하고 SQL을 main.py에 둔다. |

Redis 자료의 표시 수정일은 2026-09-13, PostgreSQL 자료는 2026-10-05다. 헤더 자료의 수정일과 원문 실행 패키지 버전은 별도 확인하지 못했다. 기술 동작은 [FastAPI 헤더 공식 문서](https://fastapi.tiangolo.com/tutorial/header-params/), [Psycopg 기본 사용법](https://www.psycopg.org/psycopg3/docs/basic/usage.html), [Supabase DB 연결](https://supabase.com/docs/guides/database/connecting-to-postgres), [Redis SET](https://redis.io/docs/latest/commands/set/), [redis-py 연결](https://redis.readthedocs.io/en/stable/connections.html)과 대조했다.

## 3. 코드 제공

### ① 실행 폴더와 Python 확인

ZIP을 풀어 현재 차시 폴더를 `C:\AI4\hybrid_backend\lesson04`에 둔다. 다른 위치에 풀었다면 경로만 실제 위치로 바꾼다. 명령은 Windows CMD에서 실행한다. 이전 차시 Uvicorn이 8000 포트를 사용 중이면 그 터미널에서 Ctrl+C로 종료한다.

```bat
cd /d C:\AI4\hybrid_backend\lesson04
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

배포 파일은 lesson04.md, main.py, .env.example, .gitignore, lesson_scope.json이다. lesson_scope.json은 내부 품질 검증 메타데이터로 접속 설정이나 실행 파일이 아니다. 다른 차시의 Python 파일이나 SQL 파일을 복사하지 않는다.

### ④ main.py 전체 코드

```python
"""4교시: Redis 세션을 확인한 뒤 Supabase에 메시지를 저장·조회한다."""
import os  # .env에서 로드된 환경변수를 조회한다.
from uuid import UUID, uuid4  # UUID는 입력 검사, uuid4는 새 대화방 ID 생성에 쓴다.

import psycopg  # PostgreSQL 동기 드라이버다.
from psycopg.rows import dict_row  # 컬럼 이름을 키로 하는 딕셔너리 행을 받는다.
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
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
            f"kdt:hybrid:l04:session:{session_id}",  # 3차시의 임의 ID 세션과 분리한다.
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
        raw = client.get(f"kdt:hybrid:l04:session:{session_id}")
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


# 초기화는 명시적으로 실행한다. Uvicorn import 시 DB를 변경하지 않는다.
if __name__ == "__main__":
    try:
        init_db()
    except psycopg.Error:
        raise SystemExit("DB 준비 실패: 접속 설정과 스키마 생성 권한을 확인하세요.") from None
```

### ⑤ 테이블 준비와 서버 실행

같은 lesson04 CMD에서 실행한다. 2차시 DB를 재사용해도 첫 명령은 다시 실행할 수 있다.

```bat
python main.py
python -m uvicorn main:app --port 8000
```

python main.py는 __main__ 분기로 init_db를 실행하고 종료한다. 예상 출력은 테이블 준비 완료다. 기존 테이블과 기록을 지우지 않는다. Uvicorn으로 import할 때는 init_db가 실행되지 않아 준비 명령이 별도로 필요하다. -m uvicorn은 서버 모듈 실행, main:app은 main.py의 app 객체, --port 8000은 서버 포트다. 기본 127.0.0.1 주소에서 실행한다. Application startup complete 후 다음 주소를 연다.

```text
http://127.0.0.1:8000/docs
```

### ⑥ 대화방 A 생성과 세션 발급

POST /conversations → Try it out → 아래 본문 → Execute한다.

```json
{"title":"통합 상담 A"}
```

201 응답의 id 전체를 복사한다. 다음 POST /sessions → Try it out의 본문에 복사한 값을 넣고 Execute한다.

```json
{"conversation_id":"방금_응답의_id_전체로_교체"}
```

따옴표 안 자리표시자는 실제 UUID로 반드시 교체한다. 예를 들어 생성 응답 id가 11111111-1111-4111-8111-111111111111이라면 그 문자열을 넣는다. 이는 형식 예시이고 실제 발급값을 사용해야 한다. 응답은 201이며 session_id와 expires_in을 포함한다. 이번에는 session_id 전체를 별도로 복사한다.

GET /conversations → Try it out → Execute하면 DB의 대화방 목록을 읽는다. 2차시 기록도 같은 DB·스키마를 사용했다면 목록에 함께 보인다. 재실행 중 대화방 ID를 잊었을 때 title과 id를 확인하는 용도다.

### ⑦ 헤더로 메시지 저장·조회

POST /messages → Try it out을 누른다. Parameters의 x-session-id 입력 칸에 방금 발급된 session_id 전체를 넣는다. 따옴표 없이 값만 붙여 넣는다. Request body는 다음과 같다.

```json
{"content":"내 이름은 민수"}
```

Execute 후 201 응답의 conversation_id가 A의 id인지 확인한다. 같은 세션 헤더로 다음 메시지도 보낸다.

```json
{"content":"이번에는 Redis 세션으로 대화방을 찾고 있어요."}
```

GET /messages → Try it out → x-session-id 칸에 같은 세션 ID → Execute한다. 200 배열에 두 메시지가 보여야 한다. GET과 POST의 헤더 입력 칸은 각각 채워야 한다. 본문에 conversation_id를 추가하면 extra=forbid에 따라 422가 된다.

POST /conversations에서 {"title":"통합 상담 B"}를 보내 B를 생성하고, POST /sessions에서 B의 id로 세션을 발급한다. GET /messages 헤더를 B의 세션 ID로 바꾸면 []가 예상된다. A의 세션으로 다시 조회하면 A의 두 메시지가 보인다. 헤더 변경이 어느 대화방을 조회할지 바꾸는 것이다.

### ⑧ 만료와 기록 보존 확인

빠른 관찰을 위해 .env의 SESSION_TTL_SECONDS를 30으로 바꾸고 Ctrl+C 후 같은 Uvicorn 명령으로 재시작한다. GET /conversations로 앞서 만든 A의 id를 확인한다. 새 대화방을 만들 필요는 없다.

1. POST /sessions 본문에 A의 id를 넣어 새 세션을 발급한다.
2. GET /messages의 헤더를 새 session_id로 갱신하고 기존 두 메시지를 확인한다.
3. 발급 후 30초가 충분히 지난 뒤 같은 헤더로 GET /messages를 실행한다. 401이 예상된다.
4. A의 같은 id로 POST /sessions를 다시 실행한다.
5. GET /messages 헤더를 새 session_id로 바꾸면 두 메시지가 다시 보인다.

설명을 읽는 동안에도 시간이 흐른다. 너무 빨리 만료되면 300초로 복원해 서버 재시작 후 재발급한다. .env 수정만으로 기존 세션의 TTL이 늘어나지 않는다. 서버 재시작은 DB 기록을 삭제하지 않는다. Redis 프로세스가 유지되고 TTL이 남으면 기존 세션도 유지될 수 있다.

### ⑨ 두 저장소의 값 확인

Redis 값을 직접 보려면 두 번째 CMD에서 세션 ID 전체로 변수를 설정한다. SESSION_ID_FULL은 실제 session_id로 바꾼다.

```bat
set SESSION_ID=SESSION_ID_FULL
docker exec kdt-hybrid-redis redis-cli GET kdt:hybrid:l04:session:%SESSION_ID%
docker exec kdt-hybrid-redis redis-cli TTL kdt:hybrid:l04:session:%SESSION_ID%
```

set은 현재 CMD 변수 설정이고 %SESSION_ID%는 그 값의 치환이다. `=` 주변 공백 없이 입력한다. 새 CMD에서는 다시 설정한다. Redis SET과는 다른 명령이다. GET 값은 메시지 본문이 아닌 대화방 UUID여야 한다. TTL은 남은 초, -2는 없는 키다. 만료됐다면 API에서 재발급한 뒤 변수도 갱신한다. 조회 명령은 데이터를 바꾸지 않는다.

### 실패 요청과 복구

| 시도 | 예상 결과 | 확인할 점 |
|---|---|---|
| POST /sessions에 존재하지 않는 00000000-0000-0000-0000-000000000000 사용 | 404 | 실제 대화방 id로 발급한다. |
| POST /sessions의 conversation_id에 abc | 422 | UUID 형식으로 고친다. |
| GET /messages 헤더 비우기 | 401 | 새 세션 ID 전체를 헤더에 넣는다. |
| GET /messages 헤더에 abc 또는 미발급 UUID | 401 | 형식 오류와 미발급·만료를 각각 거절한다. |
| POST /messages의 content에 공백만 입력 | 422 | 최소 1자 본문으로 수정한다. |
| Redis 또는 DB 처리 오류 | 503 | 드라이버 오류 종류별 안내를 보고 해당 저장소를 확인한다. |

Redis를 중지하면 새 메시지 요청은 세션 확인 단계에서 503이 될 수 있으며 DB를 사용한 우회 저장을 하지 않는다. 일반적인 세션 만료는 401이다. DB 저장 요청이 실패·타임아웃했다는 이유만으로 저장이 전혀 안 됐다고 단정하지 않는다. 응답 전달 실패와 DB 반영은 구분해야 한다.

설정 누락은 서버 시작 단계에서 키 이름으로 안내한다. DB 준비 실패는 Session pooler URI·DB 비밀번호·프로젝트 실행 상태·스키마 생성 권한을 확인한다. 테이블이 없으면 python main.py 후 서버를 다시 실행한다. 원본 비밀번호·URI를 질문이나 프롬프트에 붙이지 않는다.

가상환경이 과거 Python 경로를 찾지 못하면 deactivate → where python → python --version으로 정상 외부 Python부터 확인한다. 정상이라면 `ren .venv .venv_backup`으로 백업하고(이름이 있으면 다른 이름), 새 가상환경 생성·활성화·sys.executable 확인·패키지 재설치를 진행한다. where는 실행 후보 조회, ren은 이름 변경이다. 외부 Python도 실패하면 그 문제부터 해결한다.

### 검증 범위

제작 환경 Python 3.12에서 FastAPI 테스트 클라이언트, 로컬 Redis 6.2.14, PGlite(PostgreSQL WASM 엔진)와 psycopg 연결 대역으로 발급→헤더 저장→조회·방 분리·실제 만료·기록 보존·오류 변환을 검사했다. 원격 Supabase의 TLS·계정 권한, Windows CMD·Docker Desktop, Docker Redis 7.4의 직접 실행은 검증하지 못했다. 실제 서비스 연결과 프로세스 재시작 보존은 위 절차로 확인한다.

## 4. Vibe 코딩에 유용한 프롬프트

### 헤더부터 DB까지 추적하기

```text
lesson04/main.py에서 POST /messages의 호출 흐름을 설명해줘.
X-Session-Id 헤더와 {"content":"내 이름은 민수"} 본문을 보냈다고 가정하고
Header → resolve_conversation → Redis GET → DB SELECT·INSERT → commit → 응답을
실제 함수와 SQL에 연결해줘. 대화방 ID와 세션 ID도 구분해줘.
헤더가 없을 때, 만료됐을 때 DB에 접근하는지도 코드로 확인해줘.
코드는 수정하지 말고 .env의 실제 값과 자격증명은 읽거나 출력하지 마.
```

### 통합 동작 검증하기

```text
lesson04/main.py를 검토하고 A와 B 대화방에 각각 세션을 발급해
헤더별 메시지가 섞이지 않는지 검사해줘.
A에 두 메시지를 저장한 뒤 세션 만료 시 401,
A의 같은 대화방 ID로 새 세션 발급 후 기존 기록 200을 확인해줘.
누락·잘못된 헤더 401, 공백 본문 422, 없는 대화방 발급 404,
저장소 오류 503도 확인해줘. 만료된 요청이 DB에 저장되지 않는지 점검해줘.
자동 연장·로그인·중복 방지·다중 모듈은 추가하지 마.
.env의 실제 값은 읽거나 출력하지 말고 합성 설정을 사용해줘.
연결 대역 검사와 원격 Supabase 실측을 구분하고 오류는 최소 수정해줘.
```