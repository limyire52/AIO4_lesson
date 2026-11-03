# Redis로 만료되는 대화 세션 만들기

## 1. 학습목표

- 대화방 ID와 세션 ID의 역할을 구분한다.
- Redis에 세션 ID → 대화방 ID를 저장하고 만료 시간을 함께 지정한다.
- FastAPI에서 세션을 발급·조회하고 남은 TTL이 줄어드는 것을 확인한다.
- 만료(401), 잘못된 입력(422), Redis 장애(503)를 구분하고 다시 발급한다.

## 2. 중요 알고리즘 및 코드를 읽을 때 반드시 알아야 할 내용

### 영구 기록과 임시 연결 정보

2차시의 대화방과 메시지는 Supabase에 남아 있다. 이번에는 현재 어떤 대화방을 사용하는지 나타내는 임시 연결 정보만 Redis에 저장한다. 이번 main.py에는 DB 연결이 없다. 따라서 conversation_id의 UUID 형식은 검사하지만 실제 대화방의 존재 여부는 확인하지 않는다. 2차시에서 발급된 ID를 써도 되고, 아래 합성 UUID로 Redis 동작만 실습해도 된다.

| 값 | 예시·역할 | 저장 위치 |
|---|---|---|
| conversation_id | 영구 대화방의 식별자 | 원본은 Supabase, 이번에는 Redis 값으로 전달 |
| session_id | 세션 발급 때 새로 만든 UUID | API 응답과 Redis 키의 일부 |
| Redis 키 | kdt:hybrid:l03:session:세션ID | 세션별 조회 주소 |
| Redis 값 | 대화방 ID 문자열 | 메시지 내용은 저장하지 않음 |
| TTL | 세션의 남은 생존 시간(초) | Redis가 관리 |

키의 콜론은 Redis가 강제하는 폴더 문법이 아니라 사람이 정한 구분 규칙이다. 이 실습의 세션은 사용자 신원을 검증하는 로그인 기능이 아니다. 임의 대화방 ID로 발급할 수 있으므로 로컬에서 세션 저장 흐름을 배우는 용도로 사용한다.

### 발급과 조회 순서

발급은 JSON 검사 → 새 session_id 생성 → Redis 클라이언트 생성 → SET 값과 EX 만료 지정 → 201 응답 순서다. `client.set(key, value, ex=300)`은 값과 만료를 한 명령으로 지정한다. ex를 생략하면 새 키는 만료 없이 저장된다. 여기서는 항상 지정한다. SET 뒤 별도 EXPIRE를 보내는 두 단계보다 중간 실패 지점이 적다.

조회는 경로 UUID 검사 → GET → TTL → 결과 판정 → 200 또는 오류 순서다. Redis.from_url은 URI로 클라이언트를 구성하며 실제 통신은 명령 실행에서 일어난다. with 블록 종료 시 이 예제가 만든 클라이언트 자원을 정리한다. Redis 서버를 종료하는 것은 아니다.

| 호출·설정 | 의미와 현재 값의 이유 |
|---|---|
| decode_responses=True | 기본 False의 bytes 대신 문자열로 GET 결과를 읽는다. False로 바꾸면 응답값을 직접 디코딩해야 한다. |
| socket_connect_timeout=3 | 연결 수립 대기 제한(초). |
| socket_timeout=3 | 소켓 응답 대기 제한(초). 전체 HTTP 시간이나 재시도 포함 총시간 제한은 아니다. |
| get(key) | 없는 키는 None. 조회만으로 TTL을 늘리지 않는다. |
| ttl(key) | 남은 초. -2는 키 없음, -1은 만료 설정 없음이다. |

GET과 TTL은 별도 명령이라 그 사이 만료될 수 있다. GET에 값이 있었더라도 TTL이 -2면 만료로 처리한다. TTL이 0이면 곧 만료될 수 있는 상태다. 응답을 읽는 동안에도 시간은 흐른다. 이 두 명령은 원자적 스냅샷을 보장하지 않는다.

@app.post/get은 경로 등록이며 요청이 들어왔을 때 FastAPI가 함수를 호출한다. @app.exception_handler(RedisError)는 Redis 오류 시 호출할 처리기 등록이다. 모든 Python 예외를 처리하지는 않는다. 통신 실패 503과 정상 연결 상태에서 찾을 수 없는 세션 401을 구분한다. SESSION_TTL_SECONDS 누락 등 설정 오류는 서버 시작 전에 발생한다.

### Wikidocs 검색과 코드 반영

확인일: 2026-11-03. `site:wikidocs.net Redis 세션 set ex ttl Python`으로 검색하고 아래 본문과 코드를 확인했다.

| 자료 | 참고 패턴 | 반영·변경 이유 |
|---|---|---|
| [초!간단 DB 연동 — Redis 캐시 기초](https://wikidocs.net/428905) | Python Redis 연결, 문자열 응답, 만료 저장과 GET·TTL 관찰 | connect_redis와 세션 발급·조회에 반영. 원문의 조회 결과 캐시를 대화방 ID 연결 정보로 바꾸고, setex 패턴은 SET의 ex 인자로 재구성했다. 여러 모듈 대신 main.py와 REDIS_URL을 사용한다. |

자료의 표시 수정일은 2026-09-13이며 원문 실행 패키지 버전은 확인하지 못했다. 원문 코드를 길게 복제하지 않고 세션 예제로 재구성했다. 동작은 [Redis SET](https://redis.io/docs/latest/commands/set/), [TTL](https://redis.io/docs/latest/commands/ttl/), [redis-py 연결](https://redis.readthedocs.io/en/stable/connections.html) 공식 문서로 대조했다.

## 3. 코드 제공

### ① 실행 폴더와 Python 확인

ZIP을 풀어 현재 차시 폴더를 `C:\AI4\hybrid_backend\lesson03`에 둔다. 다른 위치에 풀었다면 경로만 실제 위치로 바꾼다. 명령은 Windows CMD에서 실행한다. 이전 차시 Uvicorn이 8000 포트를 사용 중이면 그 터미널에서 Ctrl+C로 종료한다.

```bat
cd /d C:\AI4\hybrid_backend\lesson03
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
python -m pip install fastapi==0.162.0 uvicorn==0.54.0 redis==8.1.0 python-dotenv==1.2.4
```

`python -m pip`는 현재 Python의 설치 도구 실행, install은 설치, ==는 버전 지정이다. fastapi는 API와 Swagger, uvicorn은 서버, redis는 Python Redis 클라이언트(서버 자체는 아님), python-dotenv는 .env 로딩을 담당한다.  이 버전은 제작 환경에서 사용한 직접 의존성 목록이며 전체 하위 의존성 잠금 파일은 아니다.

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
REDIS_URL='redis://127.0.0.1:6379/0'
SESSION_TTL_SECONDS=300
```

REDIS_URL은 Python이 접근하는 Redis 주소다. /0은 논리 DB 0번이다. 로컬 예제에는 비밀번호가 없다.

load_dotenv는 현재 작업 폴더의 .env를 환경변수에 올리고 os.getenv는 값을 읽는다. override=False는 기존 프로세스 환경변수를 우선하며 interpolate=False는 ${...} 치환을 막는다. .env가 없어도 필수 환경변수가 있으면 실행 가능하다. 로딩 여부는 접속 성공 판정이 아니다. REDIS_URL에는 쿼리 옵션을 추가하지 않는다. URL 쿼리 옵션이 Python에서 지정한 연결 옵션보다 우선할 수 있기 때문이다.

SESSION_TTL_SECONDS는 문자열로 읽어 양의 정수로 변환한다. 300은 발급 후 300초라는 뜻이다. 누락·공백·abc·0·음수는 시작 시 거절한다. .env 수정 후에는 Uvicorn을 Ctrl+C로 종료하고 재시작한다. 기존 Redis 키의 만료 시간은 설정 수정만으로 바뀌지 않는다.

`.gitignore`는 다음과 같다. 실제 접속값과 가상환경을 Git에 포함하지 않는다.

```gitignore
.env
.venv/
__pycache__/
*.pyc
```

배포 파일은 lesson03.md, main.py, .env.example, .gitignore, lesson_scope.json이다. lesson_scope.json은 내부 품질 검증 메타데이터로 접속 설정이나 실행 파일이 아니다. 다른 차시의 Python 파일이나 SQL 파일을 복사하지 않는다.

### ④ main.py 전체 코드

```python
"""3교시: Redis에 만료되는 대화 세션을 발급하고 조회한다."""
import os
from uuid import UUID, uuid4  # 대화방 ID 검사와 세션 ID 생성에 사용한다.

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from redis import Redis, RedisError

# 현재 폴더의 .env를 읽되 기존 환경변수와 ${...} 원문을 보존한다.
load_dotenv(".env", override=False, interpolate=False)
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
```

### ⑤ 서버 실행과 세션 발급

현재 lesson03 CMD에서 실행한다. 이 차시는 테이블 초기화가 없으므로 python main.py를 먼저 실행할 필요가 없다.

```bat
python -m uvicorn main:app --port 8000
```

-m uvicorn은 서버 모듈 실행, main:app은 main.py의 app 객체, --port 8000은 접속 포트다. 기본 127.0.0.1에서 실행한다. Application startup complete 안내 후 다음 주소에 접속한다.

```text
http://127.0.0.1:8000/docs
```

POST /sessions → Try it out → 아래 JSON 입력 → Execute한다. 아래 UUID는 Redis만 실습하기 위한 합성 대화방 ID다.

```json
{"conversation_id":"11111111-1111-4111-8111-111111111111"}
```

201 응답 예시 형태는 아래와 같다. session_id는 실제로 반환된 값을 써야 한다.

```json
{"session_id":"발급된_UUID_전체","expires_in":300}
```

session_id 값의 따옴표 안 내용만 전체 복사한다. conversation_id와 혼동하지 않는다. expires_in은 발급 시 설정한 시간이며 남은 시간 실측값은 아니다. POST를 반복하면 별도 세션이 생기며 이전 키는 자신의 TTL에 따라 만료된다.

### ⑥ 조회와 만료 관찰

GET /sessions/{session_id} → Try it out → session_id 칸에 방금 발급된 UUID 전체 → Execute한다. 중괄호·따옴표 없이 붙여 넣는다. 200 응답에는 session_id, conversation_id, ttl이 있다. conversation_id가 방금 보낸 값인지, ttl이 300 이하의 남은 초인지 본다. 몇 초 뒤 다시 Execute하면 TTL이 줄어든다. 조회는 연장 동작이 아니다.

빠르게 만료를 관찰하려면 .env의 SESSION_TTL_SECONDS를 30으로 수정하고 서버를 Ctrl+C로 종료한 뒤 같은 Uvicorn 명령으로 재시작한다. POST /sessions를 다시 실행하고 새 session_id를 사용한다. 30초가 지난 뒤 GET하면 401과 `세션이 없거나 만료되었습니다.`가 예상된다. 설명을 읽고 입력하는 시간에도 만료 시계가 흐른다.

만료 후에는 POST /sessions로 재발급하고 GET 입력값도 새 ID로 바꾼다. 이전 ID에 다시 요청해도 살아나지 않는다. 실습 후 SESSION_TTL_SECONDS=300으로 되돌리고 서버를 재시작한다. 새로 발급한 세션부터 300초 설정을 사용한다.

### ⑦ Redis에서 실제 값 확인

서버는 계속 실행한 채 두 번째 Windows CMD를 연다. 아래 SESSION_ID_FULL 자리에는 응답 session_id 전체를 넣는다. 실제 예를 들어 aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa가 발급됐다면 `set SESSION_ID=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`처럼 쓴다. 이 예시 ID 자체는 실제 발급값이 아니다.

```bat
set SESSION_ID=SESSION_ID_FULL
docker exec kdt-hybrid-redis redis-cli GET kdt:hybrid:l03:session:%SESSION_ID%
docker exec kdt-hybrid-redis redis-cli TTL kdt:hybrid:l03:session:%SESSION_ID%
```

CMD의 set은 현재 CMD에 변수를 만든다. `=` 주변 공백 없이 입력한다. %SESSION_ID%는 이 CMD가 변수 값으로 치환한다. 새 CMD에서는 다시 설정해야 한다. Redis의 SET 명령과는 별개다. docker exec와 redis-cli는 앞서 설명한 대상 컨테이너에서 Redis 명령을 실행한다. GET은 값 조회, TTL은 남은 초 조회이며 데이터를 바꾸지 않는다. GET은 대화방 UUID를, TTL은 남은 초를 반환해야 한다. 키가 없거나 만료됐다면 GET은 (nil), TTL은 -2다.

이 확인 전에 만료됐으면 세션을 재발급하고 CMD 변수도 갱신한다. 서버만 재시작해도 Redis 프로세스가 유지되고 TTL이 남아 있다면 세션은 조회 가능하다. 반면 앞서 영속화를 끈 Redis 컨테이너를 중지·시작하면 세션이 복원되지 않는다.

### 실패 입력·복구와 검증 범위

| 입력·상태 | 예상 결과 | 재개 방법 |
|---|---|---|
| POST 본문 conversation_id에 abc | 422 | UUID 형식으로 수정 |
| GET 경로 session_id에 abc | 422 | 실제 발급 UUID 전체 사용 |
| 형식은 맞지만 발급하지 않은 세션 UUID | 401 | POST로 발급하고 새 ID 사용 |
| 만료된 ID | 401 | 새로 발급하고 Swagger·CMD 변수 갱신 |
| Redis 연결 실패 | 503 | 컨테이너 실행·포트·REDIS_URL 확인 |
| TTL이 -1인 비정상 세션 키 | 503 | 이 코드의 SET EX로 새 세션 발급 |

필수 설정 누락·공백, TTL이 양의 정수가 아닌 값이면 서버가 시작되지 않는다. 현재 폴더와 .env 키를 확인하고 재시작한다. REDIS_URL은 redis:// 또는 TLS용 rediss://로 시작해야 하며 URI 비밀번호의 예약문자는 percent-encoding한다. 실제 URI·비밀번호를 프롬프트에 넣지 않는다.

기존 가상환경이 과거 Python/Conda 경로를 찾지 못하면 deactivate → where python → python --version으로 외부 Python부터 확인한다. 정상이라면 `ren .venv .venv_backup`으로 백업하고(이름이 있으면 다른 백업명 사용), `python -m venv .venv` → 활성화 → 실제 경로 확인 → 패키지 재설치를 진행한다. where는 실행 후보 조회, ren은 이름 변경이다. 외부 Python도 실패하면 설치·경로 문제부터 해결한다.

제작 환경 Python 3.12에서 FastAPI 테스트 클라이언트와 로컬 Redis 6.2.14로 발급·조회·실제 만료·TTL 미설정·422·연결 실패를 검사했다. 클라이언트는 redis-py 8.1.0이다. Windows CMD·Docker Desktop의 실제 실행 및 Docker Redis 7.4 자체는 여기서 검증하지 못했으며 위 명령과 요청으로 확인한다.

## 4. Vibe 코딩에 유용한 프롬프트

### 세션과 TTL 흐름 읽기

```text
lesson03/main.py를 읽고 POST /sessions에
{"conversation_id":"11111111-1111-4111-8111-111111111111"}을 보냈을 때
session_id, Redis 키, 값, ex가 어떻게 만들어지는지 설명해줘.
GET /sessions/{session_id}의 GET·TTL 순서와 -1·-2·0의 처리를 연결해줘.
조회로 TTL이 늘어나는지, 실제 대화방 존재를 검사하는지 코드로 확인해줘.
코드는 수정하지 말고 .env의 실제 값과 자격증명은 읽거나 출력하지 마.
```

### 만료 동작 검토하기

```text
lesson03/main.py의 고정 TTL 세션 동작을 검사해줘.
정상 발급 201, 조회 200, 만료 후 401, 잘못된 UUID 422,
Redis 연결 실패 503을 확인해줘. GET과 TTL 사이 만료 가능성도 살펴줘.
Supabase 연결·메시지 저장·자동 연장은 추가하지 마.
.env의 실제 값은 읽거나 출력하지 말고 합성 설정으로 검증해줘.
실행한 검사와 실행하지 못한 검사를 구분하고 오류가 있으면 최소 수정해줘.
```