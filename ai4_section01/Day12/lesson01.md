# FastAPI 라우터로 Supabase에 사용자 등록하고 조회하기

## 학습 흐름

| 차시 | 핵심 질문 | 실습과 확인 결과 |
| --- | --- | --- |
| 1 | HTTP 요청은 어떻게 SQL 실행으로 이어질까? | APIRouter로 POST·GET을 등록하고 Supabase에 사용자 저장·조회 |
| 2 | 잘못된 요청은 어디에서 막을까? | Pydantic 요청·응답 모델, 누락·공백·형식 오류와 422 응답 비교 |
| 3 | 원하는 사용자만 어떻게 찾을까? | 경로 매개변수로 ID 단건 SELECT, 존재하지 않는 ID의 404 처리 |
| 4 | 중복 등록은 왜 생길까? | 이메일 UNIQUE 제약, 중복 INSERT와 409 응답, 실패 후 정상 요청 확인 |
| 5 | 검색 결과가 많으면 어떻게 나눌까? | 검색어·limit·offset 쿼리 매개변수, 매개변수 SQL과 안정적인 정렬 |
| 6 | 사용자와 대화 이력을 어떻게 연결할까? | 대화 이력 테이블, 외래 키, 사용자별 대화 INSERT·SELECT |
| 7 | 저장 응답이 성공인데 왜 데이터가 없을까? | 트랜잭션 commit·rollback, 의도한 저장 누락을 Codex로 추적 |
| 8 | 여러 요청을 이어서 보내도 올바르게 동작할까? | 등록→단건→검색→대화 조회 REST 시나리오, 회귀 확인과 AI 코드 리뷰 |

각 차시는 해당 폴더의 `main.py`로 실행한다. 이번에는 `lesson01.md`를 읽고 같은 폴더의 `main.py`를 실행한다. 설명 중 SQL은 모두 `main.py`에 직접 들어 있다.

## 오늘의 질문과 목표

**Swagger에서 Execute를 누르면, 어느 시점에 Supabase에 데이터가 저장될까?**

실습을 마치면 다음을 직접 확인할 수 있다.

- `APIRouter`에 등록한 POST·GET 경로를 FastAPI 앱에 연결한다.
- JSON 요청 본문의 `name`, `email`을 INSERT 문에 전달한다.
- 저장한 행을 SELECT로 읽어 JSON 배열로 돌려준다.
- HTTP 성공 상태와 데이터의 정확성을 함께 검사한다.

Python 함수·딕셔너리·튜플·`with`, 기본적인 `INSERT`와 `SELECT`를 사용한다. `name`과 `email`은 실습용 가상 값으로 입력한다.

## 활동 순서

설치, Supabase 프로젝트 준비, 접속 정보 확인은 아래 준비 절차에서 먼저 끝낸다.

| 시간 | 활동 | 확인할 것 |
| --- | --- | --- |
| 0~5분 | 요청 흐름 예상 | GET과 POST의 차이 |
| 5~15분 | 라우터·모델·SQL 코드 읽기 | 등록과 실제 호출 구분 |
| 15~28분 | 서버 실행, POST 후 GET | 201·200과 저장 데이터 일치 |
| 28~40분 | 값이 뒤바뀌는 오류 재현, Codex 분석 | JSON→모델→SQL 값의 순서 |
| 40~47분 | 최소 수정 후 재실행 | 새 요청의 값이 올바르게 저장되는지 |
| 47~50분 | 확인 질문과 결과 기록 | 원인·수정·실행 근거 설명 |

## 1. 오늘 만들 요청 흐름

카페에서 주문 창구와 주방의 역할은 다르다. 요청 경로를 보고 담당 함수를 고르는 부분이 라우터이고, 데이터를 실제로 저장하는 부분이 데이터베이스이다.

이번 요청은 **Swagger → FastAPI 라우터 → Python 함수 → psycopg → Supabase PostgreSQL → JSON 응답** 순서로 움직인다.

| 구분 | 역할 | 이번 실습 |
| --- | --- | --- |
| REST API | HTTP 메서드와 주소로 데이터 작업을 요청하는 인터페이스 | `POST /users`, `GET /users` |
| FastAPI | HTTP 요청을 받아 Python 함수를 실행 | `app = FastAPI(...)` |
| APIRouter | 관련 요청 경로를 묶어 앱에 연결 | `router`, `app.include_router(router)` |
| Pydantic 모델 | 요청 JSON의 필드와 기본 조건 검사 | `UserCreate` |
| psycopg | Python에서 PostgreSQL에 접속하고 SQL 실행 | `psycopg.connect`, `conn.execute` |
| Supabase | 실습 데이터를 보관하는 PostgreSQL 제공 | `kdt_api01.users` |

이번 REST API의 주소는 로컬 FastAPI 주소이다. Supabase가 자동 제공하는 `/rest/v1/...` Data API와는 다른 인터페이스이다. FastAPI는 Supabase의 PostgreSQL에 직접 SQL을 전달한다. 따라서 Supabase API 키는 사용하지 않으며, DB 접속 비밀번호를 실행 중에만 입력한다.

## 2. 실행 전 준비

### 2-1. Supabase에서 접속 항목 확인

1. Supabase에 로그인하고 실습용 프로젝트를 연다. 프로젝트가 일시 중지되어 있으면 먼저 다시 시작한다.
2. 프로젝트의 **Connect**에서 PostgreSQL 연결 방법을 확인한다.
3. 연결 방식으로 **Session pooler**를 선택한다. Windows의 일반적인 IPv4 환경에서 연결할 수 있는 방식이며, 이 실습에서는 포트 `5432`를 사용한다.
4. 표시된 연결 항목 중 **Host**, **User**, **Database**, **Port**를 확인한다. 코드에서는 Database가 `postgres`, Port가 `5432`인 기본 구성을 사용한다.
5. Host와 User는 화면에 표시된 값을 그대로 사용한다. Host는 대체로 `aws-...pooler.supabase.com` 형태이고 User는 `postgres.프로젝트참조값` 형태이다. 지역·숫자·프로젝트참조값을 예시에서 추측하지 않는다.
6. 프로젝트를 만들 때 정한 **Database password**를 준비한다. Supabase 로그인 비밀번호와 다를 수 있다. 모르면 프로젝트의 데이터베이스 설정에서 재설정한다.

`https://...supabase.co`는 프로젝트 API 주소이므로 Host 입력란에 넣지 않는다. Host에는 프로토콜·포트·슬래시 없이 호스트명만 넣는다. User에도 비밀번호나 전체 연결 URL을 붙이지 않는다. Connect 화면에서 Transaction pooler의 `6543`을 선택하지 않도록 확인한다.

비밀번호를 `main.py`, 교안, Git에 적지 않는다. 실행 시 `getpass()`로 입력하면 터미널에 글자가 표시되지 않는다. 표시가 없어도 입력되고 있으므로 입력을 마친 뒤 Enter를 누른다.

이 실습은 무료 Supabase 프로젝트에서 수행할 수 있다. 실행 환경에서 Supabase로 연결할 수 있는 네트워크와 프로젝트 DB 접속 권한은 필요하다.

### 2-2. Windows CMD에서 환경 만들기

아래는 `C:\AI4` 안에 실습 폴더를 만드는 예시이다. 기존에 같은 폴더가 있으면 새로 만들지 말고 그 위치로 이동한다.

```bat
cd /d C:\AI4
mkdir fastapi_supabase
cd fastapi_supabase
python --version
python -m venv .venv
.venv\Scripts\activate
python -m pip install fastapi==0.162.0 uvicorn==0.54.0 "psycopg[binary]==3.3.6" pydantic==2.14.1
mkdir lesson01
cd lesson01
```

Python 3.12를 기준으로 설명한다. 버전이 다르면 먼저 확인한다. `python -m venv`는 패키지를 분리하는 가상환경을 만들고, `activate`는 현재 터미널에서 그 환경을 사용하도록 바꾼다. `psycopg[binary]`는 PostgreSQL 연결에 필요한 바이너리를 함께 설치하는 옵션이다. 위 목록은 확인에 사용한 직접 의존성 버전이며, 모든 하위 의존성을 고정한 잠금 파일은 아니다.

PowerShell에서는 활성화 명령이 `.venv\Scripts\Activate.ps1`이고, macOS/Linux에서는 `source .venv/bin/activate`이다. 나머지 실행 명령의 `python`은 동일하다.

다운로드한 `main.py`를 이 `lesson01` 폴더에 둔다. 직접 작성할 때는 아래 전체 코드를 `main.py`에 저장한다. `main.py.txt`가 되지 않도록 파일 확장자도 확인한다.

| 파일 | 목적 | 사용 방법 |
| --- | --- | --- |
| `lesson01.md` | 개념, 전체 코드, 실행, 오류 수정 안내 | 이 문서를 순서대로 읽는다. |
| `main.py` | 테이블 준비와 POST·GET 처리 | `python main.py`로 실행한다. |
| `lesson_scope.json` | 배포 품질 검사용 파일·경로 명세 | 실행에 사용하지 않는 내부 검증 메타데이터이다. |

## 3. 전체 main.py

아래 코드는 정상 동작을 먼저 확인하는 코드이다. 오류 활동에서는 지정한 한 줄만 바꾼다.

```python
from getpass import getpass

import psycopg
import uvicorn
from fastapi import APIRouter, FastAPI, Request
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field


app = FastAPI(title="사용자 등록·조회 실습")
router = APIRouter(tags=["users"])


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=1, max_length=100)


def initialize_database(db_config):
    with psycopg.connect(**db_config) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS kdt_api01;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kdt_api01.users (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL
            );
        """)


def get_connection(request: Request):
    return psycopg.connect(
        **request.app.state.db_config,
        row_factory=dict_row,
    )


@router.post("/users", status_code=201)
def create_user(user: UserCreate, request: Request):
    with get_connection(request) as conn:
        row = conn.execute(
            """
            INSERT INTO kdt_api01.users (name, email)
            VALUES (%s, %s)
            RETURNING id, name, email;
            """,
            (user.name, user.email),
        ).fetchone()
    return row


@router.get("/users")
def list_users(request: Request):
    with get_connection(request) as conn:
        rows = conn.execute("""
            SELECT id, name, email
            FROM kdt_api01.users
            ORDER BY id;
        """).fetchall()
    return rows


app.include_router(router)


if __name__ == "__main__":
    db_config = {
        "host": input("Session pooler의 Host: ").strip(),
        "port": 5432,
        "dbname": "postgres",
        "user": input("Session pooler의 User: ").strip(),
        "password": getpass("Database password: "),
        "sslmode": "require",
        "connect_timeout": 10,
    }
    initialize_database(db_config)
    app.state.db_config = db_config
    print("DB 준비 완료. http://127.0.0.1:8000/docs 에 접속하세요.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

## 4. 코드를 요청 흐름에 따라 읽기

### 4-1. 앱을 만들고 라우터를 연결한다

`app`은 HTTP 요청을 받는 앱이다. `router`에는 사용자 등록·조회 경로를 모아 둔다. 식당 전체를 앱에 비유하면 라우터는 특정 주문을 담당하는 창구이다.

`@router.post("/users", status_code=201)`은 **POST /users 요청이 들어올 때 create_user를 실행한다는 등록**이다. 이 줄을 읽는 순간 INSERT가 실행되는 것은 아니다. `@router.get("/users")`도 조회 함수를 등록한다.

`app.include_router(router)`는 등록한 경로를 앱에 연결한다. 함수를 작성했더라도 이 연결이 없으면 앱의 `/users` 요청으로 호출할 수 없다. 여기에는 prefix를 지정하지 않았으므로 최종 주소는 그대로 `/users`이다.

이번에는 라우터도 같은 파일에 둔다. 라우터라는 개념이 반드시 별도 Python 파일을 요구하는 것은 아니다.

### 4-2. UserCreate가 요청 JSON을 받는다

다음 JSON을 POST로 보내면 FastAPI는 `UserCreate`로 검사한 후 `user`에 전달한다.

```json
{"name": "홍길동", "email": "hong01@example.com"}
```

- `name: str`, `email: str`: 두 값을 문자열로 받는다. 기본값이 없으므로 두 필드는 필수이다.
- `min_length=1`: 빈 문자열을 막는다.
- `max_length`: 지나치게 긴 입력을 막는다.
- `str_strip_whitespace=True`: 문자열 앞뒤 공백을 제거한다. 공백만 보낸 이름도 제거 후 길이가 0이 되어 거절된다.
- `extra="forbid"`: 정의하지 않은 필드를 추가하면 거절한다.

검사를 통과하지 못하면 일반적으로 **422** 응답이 나오며 함수 본문의 INSERT는 실행되지 않는다. 이번 `email`은 비어 있지 않은 문자열까지만 검사한다. `abc`도 통과하며, 이메일 형식 검사와 이메일 중복 제한은 아직 없다. 같은 값을 두 번 POST하면 행이 두 개 추가된다.

`request: Request`는 JSON 필드가 아니다. FastAPI가 현재 HTTP 요청 객체를 주입한다. 이 객체로 앱 안에 보관한 DB 접속 설정을 읽는다.

### 4-3. 서버를 실행하기 전에 테이블을 준비한다

`if __name__ == "__main__":` 아래 코드는 `python main.py`로 직접 실행할 때 동작한다.

실행 순서는 **Host·User·비밀번호 입력 → initialize_database 호출 → 앱에 접속 설정 보관 → 서버 시작**이다. `initialize_database`는 프레임워크 자동 콜백이 아니라 이 순서에서 직접 호출하는 일반 함수이다.

`CREATE SCHEMA IF NOT EXISTS kdt_api01`은 실습 테이블을 모아 둘 공간을 만든다. 스키마는 같은 DB 안에서 표를 묶는 서랍에 비유할 수 있다. `kdt_api01.users`는 그 서랍 안의 `users` 테이블이다.

| 열 | 의미 |
| --- | --- |
| `id` | PostgreSQL이 자동 생성하는 정수 식별자이며 기본 키이다. |
| `name` | 이름을 저장하며 NULL을 허용하지 않는다. |
| `email` | 이메일 문자열을 저장하며 NULL을 허용하지 않는다. |

`IF NOT EXISTS`는 같은 이름이 있으면 새로 만들지 않는다는 뜻이다. 기존 데이터를 지우거나 기존 테이블의 열 구성을 고치지는 않는다. 이전에 다른 열 구성으로 같은 테이블을 만들었다면 새 실습 프로젝트를 사용하거나 구성을 확인한다.

Supabase의 기본 Data API 노출 대상에 이 사용자 정의 스키마를 추가하지 않는다. 이 수업은 DB 소유자 접속으로 SQL을 실행한다. 앱 자체에는 사용자 인증이 없으므로 서버는 `127.0.0.1`에서만 실행하고 가상 데이터만 사용한다. 외부 배포용 권한·인증 설계는 이 코드에 포함되어 있지 않다.

### 4-4. POST 요청이 오면 INSERT를 실행한다

`get_connection(request)`는 연결 설정을 읽고 **새 DB 연결**을 만든다. 연결 하나를 모든 요청에서 공유하지 않는다. `row_factory=dict_row`는 조회 결과를 `{"id": ..., "name": ..., "email": ...}` 형태의 딕셔너리로 받게 한다.

INSERT 문에서 열과 값은 **순서로 대응**한다.

| SQL 열 | 전달 값 |
| --- | --- |
| 첫 번째 `name` | `user.name` |
| 두 번째 `email` | `user.email` |

`%s`는 값이 들어갈 자리 표시자이다. `%s` 안에 직접 따옴표를 붙이지 않는다. 값은 SQL 문자열에 f-string으로 섞지 않고 `(user.name, user.email)` 튜플로 따로 전달한다. 실제 문자열 처리와 인코딩은 드라이버가 담당한다.

`RETURNING id, name, email`은 방금 추가한 행을 돌려달라는 PostgreSQL 구문이다. `fetchone()`은 그 한 행을 가져온다. Python 딕셔너리를 반환하면 FastAPI가 HTTP JSON 응답으로 보낸다.

**with 블록을 정상적으로 벗어날 때 psycopg 연결 컨텍스트가 commit하고 연결을 닫는다.** 예외가 발생하면 rollback하고 닫는다. 따라서 `return row`를 블록 밖에 두어 commit이 끝난 후 응답값을 반환한다. `conn.execute()`만 호출하면 언제나 영구 저장된다고 이해하면 안 된다.

### 4-5. GET 요청이 오면 SELECT를 실행한다

`list_users()`는 이름·이메일·ID를 조회하고 `fetchall()`로 여러 행을 리스트에 담는다. `ORDER BY id`는 ID 오름차순으로 결과를 정렬한다. 테이블에 아무 행도 없으면 오류가 아니라 빈 배열 `[]`을 반환한다.

HTTP GET과 SQL SELECT는 같은 언어의 명령이 아니다. 브라우저가 GET을 보내고, 그 요청을 받은 Python 함수가 SELECT를 실행하도록 연결해 둔 것이다.

DB 호출이 동기 방식이므로 경로 함수도 `def`로 작성했다. 이번 실습은 `async def`로 바꾸는 활동을 포함하지 않는다.

## 5. 서버를 실행한다

`main.py`가 있는 `lesson01` 폴더에서 실행한다.

```bat
python main.py
```

Connect 화면에서 확인한 정보를 묻는 순서대로 입력한다.

```text
Session pooler의 Host: <Connect 화면의 실제 Host>
Session pooler의 User: <Connect 화면의 실제 User>
Database password:
DB 준비 완료. http://127.0.0.1:8000/docs 에 접속하세요.
```

꺾쇠 괄호와 예시 문장을 그대로 입력하지 않는다. DB 연결이 성공한 뒤 Uvicorn의 `Application startup complete` 또는 서버 실행 로그를 확인한다. 그 후 브라우저에서 [Swagger](http://127.0.0.1:8000/docs)를 연다. `/docs`와 `/openapi.json`은 FastAPI가 자동 제공하는 문서 경로이며 직접 만든 업무 경로는 아니다.

**이번 코드의 실행 명령은 `python main.py`이다.** `python -m uvicorn main:app`으로 실행하면 직접 실행 블록이 실행되지 않아 테이블 준비와 `app.state.db_config` 설정이 빠진다. `--reload`도 사용하지 않는다. 코드를 수정하면 Ctrl+C로 종료한 뒤 같은 명령을 다시 실행하고 접속 정보를 입력한다. 서버 프로세스는 하나만 사용한다.

| 서버 | 주소·포트 | 역할 |
| --- | --- | --- |
| 터미널 A의 FastAPI | `127.0.0.1:8000` | REST 요청 처리 |
| Supabase Session pooler | 확인한 Host의 `5432` | 원격 PostgreSQL 접속 |

FastAPI의 `8000`과 데이터베이스의 `5432`는 다른 역할의 포트이다.

## 6. POST로 저장하고 GET으로 읽는다

### 6-1. 먼저 조회한다

Swagger에서 **GET /users → Try it out → Execute**를 누른다.

새 실습 테이블이라면 상태 **200**, 본문 **`[]`**이 예상된다. 이전에 등록한 데이터가 있으면 그 목록이 나온다. GET은 실행 횟수가 늘어나도 새 행을 만들지 않는다.

브라우저 주소창에 `http://127.0.0.1:8000/users`를 열어도 같은 GET 조회가 된다.

### 6-2. 사용자 한 명을 등록한다

Swagger에서 **POST /users → Try it out**을 누르고 Request body를 바꾼다.

```json
{
  "name": "홍길동",
  "email": "hong01@example.com"
}
```

Execute를 누르면 상태 **201**과 다음 형태를 예상한다.

```json
{
  "id": 1,
  "name": "홍길동",
  "email": "hong01@example.com"
}
```

`id`는 예시이다. 기존 행, 삭제 이력, 실패한 INSERT가 있으면 1부터 연속하지 않을 수 있다. 이름·이메일이 요청과 같은지가 우선 확인 대상이다.

### 6-3. 다시 조회한다

Swagger에서 **GET /users → Try it out → Execute**를 다시 누른다. 목록에 방금 등록한 사용자와 같은 `id`, `name`, `email`이 들어 있어야 한다.

```json
[
  {
    "id": 1,
    "name": "홍길동",
    "email": "hong01@example.com"
  }
]
```

브라우저 주소창은 보통 GET을 보내므로 주소를 입력하는 것만으로 POST 등록을 실행할 수 없다. POST에는 Swagger를 사용한다.

### 6-4. 서버를 다시 시작해도 남아 있는지 확인한다

1. 터미널 A에서 Ctrl+C를 눌러 종료한다.
2. `python main.py`를 다시 실행하고 같은 프로젝트 접속 정보를 넣는다.
3. GET /users를 실행한다.
4. 앞에서 등록한 데이터가 여전히 나오는지 확인한다.

Python 리스트에 임시로 보관한 값이 아니라 원격 DB에 저장한 값이므로 정상 commit된 행은 서버를 다시 시작해도 남는다.

### 6-5. 잘못된 요청을 비교한다

POST 본문에서 이름을 공백만 보내 본다.

```json
{"name": "   ", "email": "invalid-name@example.com"}
```

**422** 응답이 예상된다. GET을 다시 실행해 이 이메일의 행이 새로 생기지 않았는지 확인한다. 필수 `email`을 빼거나 `age` 같은 필드를 추가해도 422를 확인할 수 있다. 검증 오류의 세부 메시지 문구보다 상태 코드와 저장 여부를 관찰한다.

## 7. 의도한 오류: 성공 응답인데 이름과 이메일이 뒤바뀐다

### 7-1. 실행 전에 예상한다

정상 코드의 SQL은 열 순서가 `(name, email)`이다. 값만 뒤집으면 자료형이 둘 다 문자열이므로 문법 오류 없이 저장될 수 있다. HTTP 201만 보면 문제를 놓칠 수 있다.

터미널에서 Ctrl+C로 서버를 종료한 뒤 `create_user()`의 다음 줄만 바꾼다.

정상 코드:

```python
(user.name, user.email),
```

오류 재현 코드:

```python
(user.email, user.name),
```

SQL 열 이름이나 Pydantic 모델은 변경하지 않는다. `python main.py`로 다시 실행한다.

### 7-2. 다른 값으로 재현한다

POST /users로 다음 값을 보낸다.

```json
{"name": "김하늘", "email": "bug01@example.com"}
```

오류를 넣은 상태에서는 **201**이지만 다음처럼 값이 뒤바뀐 응답이 예상된다.

```json
{"id": 2, "name": "bug01@example.com", "email": "김하늘"}
```

ID는 달라도 된다. GET /users를 실행해 실제 저장된 목록에서도 뒤바뀌었는지 본다. POST 응답 표시만 바뀐 것인지, DB에 저장할 때부터 바뀐 것인지 구분하는 근거이다.

| 비교 지점 | 기대 | 오류 상태 |
| --- | --- | --- |
| POST 상태 | 201 | 201 |
| 응답의 name | 김하늘 | bug01@example.com |
| 응답의 email | bug01@example.com | 김하늘 |
| GET으로 재조회 | 요청한 의미대로 저장 | 뒤바뀐 값이 저장되어 있음 |

### 7-3. Codex에 원인 분석을 요청한다

파일을 수정하기 전에 **어디에서 값이 바뀌는지** 추적하게 한다. 접속 비밀번호, 실제 프로젝트 식별자, 실제 개인 정보를 프롬프트나 로그에 넣지 않는다.

```text
lesson01/main.py를 읽고 원인을 분석해줘. 아직 수정하지 마.
실행 명령은 해당 폴더에서 python main.py이고,
FastAPI 한 프로세스를 127.0.0.1:8000에서 실행한다.
DB는 Supabase PostgreSQL이며 접속 정보는 실행할 때 직접 입력한다.

Swagger POST /users에 다음 JSON을 보냈다.
{"name":"김하늘","email":"bug01@example.com"}
기대: 201이며 name은 김하늘, email은 bug01@example.com.
실제: 201이지만 name과 email이 뒤바뀐다. GET /users에서도 같다.

JSON → UserCreate → create_user → INSERT 열 순서 → %s에 전달한
튜플 순서 → RETURNING → GET 재조회 흐름을 코드 근거로 추적해줘.
두 필드가 같은 문자열 자료형일 때 검증이 놓치는 조건도 설명해줘.
직접 실행한 사실과 코드에서 추론한 내용을 구분해줘.
DB 접근이 없으면 실제 Supabase 실행 검증을 했다고 쓰지 마.
```

읽을 파일과 재현 값을 지정하면 관련 없는 코드로 범위가 퍼지는 것을 줄일 수 있다. 기대와 실제를 함께 주면 단순히 201 상태를 유지하는 수정을 정답으로 착각하지 않는다.

### 7-4. 최소 수정을 요청한다

```text
분석한 원인을 lesson01/main.py 안에서 최소 수정해줘.
POST /users의 SQL 열과 전달 값의 순서가 일치하도록 고쳐줘.
GET /users, 요청 필드, 201·200 응답, DB 연결 방식은 유지해줘.
API 경로·패키지·파일을 추가하거나 SQL을 다른 파일로 분리하지 마.
응답 딕셔너리에서 키만 바꿔 증상을 숨기지 마.

수정 후 새 값 {"name":"이바다","email":"fixed01@example.com"}로
POST 201과 GET 200의 값 일치를 확인해줘.
공백 이름 POST는 422이며 새 행이 추가되지 않아야 한다.
접속할 수 없다면 내가 실행할 순서를 적고 미검증 범위를 밝혀줘.
```

응답 키만 바꾸는 편법을 막는 이유는 DB에 이미 잘못 저장된 값을 그대로 두고 화면만 정상처럼 보이게 할 수 있기 때문이다.

### 7-5. 변경 결과를 검토한다

```text
수정한 줄이 INSERT의 열·값 대응을 어떻게 바로잡는지 설명해줘.
정상 POST, GET 재조회, 공백 이름 실패를 확인한 근거를 보여줘.
미사용 코드나 다음 차시 기능, 별도 SQL 파일이 추가되지 않았는지 확인해줘.
수정 전에 잘못 저장한 행이 자동으로 복구되는지도 구분해서 설명해줘.
실제로 실행하지 못한 검증은 별도로 밝혀줘.
```

## 8. 수정 정답과 재확인

수정 정답은 다음 한 줄이다.

```python
(user.name, user.email),
```

SQL 첫 번째 열인 `name`에는 첫 번째 값 `user.name`을, 두 번째 열인 `email`에는 두 번째 값 `user.email`을 전달한다.

서버를 종료하고 `python main.py`로 다시 시작한다. 다음 새 값을 POST로 등록한다.

```json
{"name": "이바다", "email": "fixed01@example.com"}
```

201 응답과 GET 목록에서 이름이 `이바다`, 이메일이 `fixed01@example.com`인지 확인한다. 이어 공백 이름 POST가 422인지 재확인한다.

**코드를 고쳐도 이전에 잘못 저장된 행이 자동 복구되지는 않는다.** 오류 활동에서 만든 행은 비교 근거로 남겨 두고 새 이메일로 수정 결과를 판단한다. 새로고침이나 재시작이 저장 데이터를 고치는 작업은 아니다.

## 9. 막히는 지점 확인

| 증상 | 먼저 확인할 것 |
| --- | --- |
| `ModuleNotFoundError` | 가상환경 활성화와 설치를 같은 Python에서 했는지 `python -m pip show fastapi psycopg`로 확인한다. |
| Host 이름을 찾을 수 없음 | API URL을 넣지 않았는지, Session pooler Host를 그대로 복사했는지 확인한다. |
| 비밀번호 인증 실패 | Supabase 로그인 비밀번호가 아니라 Database password인지, User에 프로젝트참조값이 있는지 확인한다. |
| 연결 시간 초과 | 프로젝트 일시 중지 여부, 인터넷, 방화벽의 DB 접속 허용 여부와 Host·5432를 확인한다. |
| 스키마 생성 권한 없음 | Connect 화면의 프로젝트 DB 소유자 접속 항목을 사용했는지 확인한다. |
| `db_config` 관련 오류 | `python -m uvicorn`으로 실행하지 않았는지 확인하고 `python main.py`로 실행한다. |
| 주소 사용 중 오류 | 8000을 쓰는 이전 서버를 Ctrl+C로 종료한다. DB 준비 로그만으로 HTTP 서버 시작이 완료된 것은 아니다. |
| `/` 주소에서 404 | 이번 경로는 `/users`와 자동 문서 `/docs`이다. 루트 경로는 등록하지 않았다. |
| GET 결과가 빈 배열 | 같은 프로젝트에 POST했는지, POST가 실제 201이었는지 확인한다. |
| POST를 두 번 누르니 행이 두 개 | 이번 테이블에는 이메일 UNIQUE 제한이 없으므로 각 POST가 새로운 행을 만든다. |
| 테이블 열이 예상과 다름 | `IF NOT EXISTS`가 기존 열을 바꾸지 않으므로 같은 이름의 이전 테이블 구성을 확인한다. |

접속 설정 오류는 서버가 시작되기 전에 터미널 예외로 나타날 수 있다. 실행 중 DB 오류가 발생하면 이번 기본 코드에서는 500이 될 수 있다. 422는 요청 모델 검사 실패이고, 500은 서버 처리 중 오류이므로 같은 원인으로 보지 않는다. 예외를 무조건 빈 배열로 숨기지 않는다.

## 10. 확인 질문

1. `@router.post`를 작성하는 순간 DB에 INSERT가 실행되는가?
2. GET과 POST가 같은 `/users` 주소를 사용해도 되는 이유는 무엇인가?
3. `%s` 두 개에 전달할 값을 뒤집었는데도 201이 나온 이유는 무엇인가?
4. 서버를 다시 시작했는데 데이터가 남아 있는 이유는 무엇인가?
5. `app.include_router(router)`와 `conn.execute()`는 각각 무엇을 연결하거나 실행하는가?

### 답과 해설

1. 경로를 등록하며, 실제 POST 요청이 도착해야 함수가 호출되고 INSERT가 실행된다.
2. 경로뿐 아니라 HTTP 메서드도 요청을 구분한다. POST는 등록, GET은 조회를 담당하도록 정했다.
3. 두 열과 두 값이 모두 문자열이라 DB가 의미상의 뒤바뀜을 자동으로 알 수 없기 때문이다. 상태 코드와 실제 값을 함께 검사해야 한다.
4. with 연결 컨텍스트가 정상 종료되며 commit한 데이터는 원격 PostgreSQL에 저장되기 때문이다.
5. include_router는 라우터의 경로를 앱에 연결하고, execute는 DB 연결을 통해 SQL을 실행한다.

## 11. 실습 결과 기록

다음 내용을 접속 정보 없이 기록한다.

- 정상 POST 요청 JSON, 201 응답, GET 조회 결과.
- 공백 이름 요청의 422 결과와 행이 추가되지 않은 근거.
- 오류 재현 시 SQL 열과 튜플 값의 대응 설명.
- 수정한 한 줄과 새 데이터로 재확인한 결과.

| 확인 항목 | 완료 기준 |
| --- | --- |
| 라우터 이해 | 등록·앱 연결·HTTP 호출을 구분한다. |
| SQL 연동 | INSERT 후 GET에서 같은 행을 찾는다. |
| 입력 검사 | 422 요청은 새 행을 만들지 않는다. |
| 오류 수정 | 상태뿐 아니라 실제 저장 값의 의미를 확인한다. |

다음에는 요청·응답 모델을 구체화해 잘못된 입력과 불필요한 응답 필드를 다루는 방법을 익힌다.

## 12. 실행 확인 범위

이 자료의 로컬 확인에서는 FastAPI TestClient와 DB 대역을 사용해 정상 POST·GET, 요청 검증 실패, 매개변수 순서 오류와 수정 결과를 확인했다. DB 대역은 SQL 값 전달을 관찰하기 위한 가짜 연결이며 실제 PostgreSQL이 아니다. 실제 Supabase 접속, SQL 구문 실행, commit·rollback, 네트워크, Windows CMD 실행은 이 환경에서 확인하지 못했다. 직접 확인할 때는 위 `python main.py` 실행과 Swagger 실습 순서를 따른다.

파일·API 범위 정적 검사와 수동 검토를 별도로 수행했다. 실제 Supabase에서의 성공을 보장하는 검사로 해석하지 않는다.

## 참고 문서

- [FastAPI: APIRouter와 include_router](https://fastapi.tiangolo.com/tutorial/bigger-applications/) — 라우터 등록과 앱 연결
- [Supabase: PostgreSQL 연결](https://supabase.com/docs/guides/database/connecting-to-postgres) — Session pooler와 연결 방식
- [Supabase: 사용자 정의 스키마](https://supabase.com/docs/guides/api/using-custom-schemas) — Data API에 스키마를 노출하는 별도 설정
- [Psycopg: 기본 사용법](https://www.psycopg.org/psycopg3/docs/basic/usage.html) — SQL 매개변수와 연결 컨텍스트의 트랜잭션 처리