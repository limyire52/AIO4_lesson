# 6교시. 원본 저장 후 오래된 캐시를 재사용하지 않기

## 1. 학습목표

- 새 대화 한 턴을 sqlite 트랜잭션으로 저장한다.
- 원본 COMMIT 이후에만 이전 캐시를 삭제한다.
- 최신 원본 ID로 캐시 버전을 나누어 변경 전·후 조회를 구분한다.
- 캐시 HIT에도 남는 sqlite 조회와 적용 범위의 한계를 설명한다.

## 2. 중요 알고리즘 및 코드를 읽을 때 반드시 알아야 할 내용

### 5교시에서 새 메시지가 생기면 무엇이 달라져야 할까

5교시는 읽기 전용 캐시였다. 이제 add가 새 user/assistant 한 턴을 원본에 넣는다. Redis에 저장된 이전 사본을 계속 반환하면 새 메시지가 보이지 않는 문제가 생긴다. 이번 중심 개념은 **원본 변경에 따른 캐시 무효화**다.

쓰기 순서는 `이전 캐시 키 계산 → sqlite 두 행 저장·COMMIT → 이전 Redis 키 삭제`다. 원본 저장이 실패하면 캐시 삭제까지 가지 않는다. 반대로 COMMIT 이후 DEL만 실패했다고 원본까지 취소되지는 않는다. Redis와 sqlite에 걸친 하나의 트랜잭션이 있는 것은 아니다.

### 삭제 실패 때도 이전 캐시를 고르지 않도록 버전 구분

캐시 키에 해당 사용자의 최신 원본 id를 붙인다. 초기 A 원본의 마지막 id가 2라면 `lesson06:history:demo-a:v2`다. 새 대화가 들어가 마지막 id가 6이 되면 다음 읽기는 v6를 찾는다. v2가 남아도 다음 읽기의 대상이 아니다. 정상 DEL은 이전 사본을 빨리 정리하고, 남은 옛 키는 자체 TTL로도 만료된다.

`SELECT COALESCE(MAX(id), 0) ...`에서 MAX는 해당 사용자의 가장 큰 id, COALESCE는 데이터가 없을 때 0을 선택한다. `(owner,)`는 원소 한 개짜리 튜플이며 뒤 쉼표가 필요하다. 버전은 모든 사용자의 공통 숫자가 아니라 owner별 최신 id다.

이 방식은 조회마다 최신 id를 sqlite에서 읽는다. 따라서 HIT가 **DB 접속·모든 SQL을 완전히 생략한다는 뜻은 아니다.** 본문의 최근 이력 여섯 행 조회·변환을 재사용하는 작은 학습용 패턴이다. 동시 쓰기에서 완전한 최신성·처리 순서를 보장한다고 주장하지 않는다.

원본은 append-only다. 기존 메시지 본문을 직접 UPDATE하거나 DELETE하면 MAX(id)만으로 그 변경을 알아낼 수 없다. 이 기능은 제공하지 않으며 원본 DB 파일을 예전 버전으로 교체하는 것도 지원 범위가 아니다. 수정·삭제가 필요한 서비스는 별도의 변경 버전 정책이 필요하다.

### 두 행을 한 턴으로 저장

add의 모의 답변은 `모의 응답: 입력내용`으로 정한다. 이전 문맥을 이용한 생성은 이번 코드의 목표가 아니다. `save_turn` 안의 with conn과 executemany가 user와 assistant 두 행을 같은 트랜잭션에 넣는다. 둘째 저장이 실패해도 첫 행만 남지 않도록 한다. 기본 COMMIT/ROLLBACK 동작과 연결 종료를 구분한다.

이 차시는 Redis 오류를 바깥에서 오류로 처리한다. DEL 실패 전에 `원본 저장 완료`가 보였다면 그 원본은 이미 저장된 것이다. 같은 add를 무조건 반복하면 같은 대화가 한 번 더 추가된다. 조회로 상태를 먼저 확인한다. 7교시에서 이 부분을 명시적인 대체 정책으로 바꾼다.

### sqlite 원본 조회와 JSON 변환을 읽는 방법

`messages`의 id는 저장 순서를 정하는 정수, owner는 가상 사용자 ID, role은 user/assistant, content는 메시지다. PRIMARY KEY는 행 식별자이고 AUTOINCREMENT는 자동 번호가 과거에 사용한 번호를 재사용하지 않도록 한다. role의 CHECK는 두 역할 외 값의 저장을 막는다. 이 예제는 원본 메시지를 추가만 하고 수정·삭제하지 않는다.

`WHERE owner = ?`와 `(owner, MAX_MESSAGES)` 같은 매개변수 바인딩은 값을 SQL 문법과 분리한다. 물음표에 문자열을 직접 이어 붙이지 않는다. `ORDER BY id DESC LIMIT ?`로 최신 여섯 개를 고른 뒤 reversed로 과거→현재 순서로 바꾼다. 원본의 나머지 행을 삭제하는 코드는 아니다. `fetchall()`은 조회 결과 전체를 튜플 목록으로 가져오고, 역할·내용을 사전으로 만든다.

`with conn:`은 정상 쓰기를 COMMIT하고 예외 시 ROLLBACK하는 범위다. 연결 자체를 닫지는 않는다. `closing(sqlite3.connect(...))`이 블록 종료 시 연결을 닫는다. connect의 첫 인자는 파일 경로, timeout=5는 다른 쓰기의 잠금이 풀리기를 기다리는 초이며 기본값도 5다. 정상적인 로컬 파일 경로와 순차 명령 실행을 사용한다. sqlite3는 Python 내장 모듈이라 별도 pip 설치가 없다.

`json.dumps(messages, ensure_ascii=False)`는 메시지 목록을 한 JSON 문자열로 만든다. False는 기본 True와 달리 한글을 문자로 유지한다. `json.loads(raw)`는 이를 Python 목록으로 복원한다. 캐시에는 최근 메시지 목록 전체를 String 하나로 저장한다. 4교시의 List는 메시지 추가를 연습하기 위한 것이었고, 이번에는 원본에서 읽은 조회 결과를 통째로 바꿔 넣는 사본이므로 String을 선택한다. 응답 결과를 재사용하는 LLM 응답 캐시와는 다른 **대화 이력 캐시**다.

### 명령줄 입력과 연결 옵션

add_argument는 입력 규칙을 등록하고 parse_args가 실제 명령줄을 해석해 args 필드를 만든다. 명령 이름을 등록하는 순간 저장·조회가 실행되는 것은 아니다.

| 실제 입력 | args와 실행 흐름 | 결과 |
|---|---|---|
| python main.py add demo-a "추가 문장" | command=add, value=demo-a, text=추가 문장 → save_turn → COMMIT → invalidate | 원본 두 메시지 저장·옛 캐시 삭제 |
| python main.py history demo-a | command=history, value=demo-a, text="" → 버전 계산 → load_history | 새 버전 MISS 또는 HIT |

예를 들어 text를 생략하면 args.text는 빈 문자열이다. 메시지를 넣으면 따옴표 내부 문자열이 들어간다. nargs가 생략을 허용해도 add/chat의 조건부 검사에서 누락·공백은 거절하고, 다른 명령에 불필요한 메시지를 넣어도 거절한다.

command는 choices에 등록한 동작만 받는다. `nargs="?"`는 인자 0개 또는 1개를 받는다는 뜻이며 생략하면 default=""로 빈 문자열을 준다. init은 사용자 인자가 없고 나머지 동작은 사용자나 세션 ID가 필요하므로 코드에서 조건을 따로 검사한다. help는 `--help`에 표시하는 설명이지 필수 조건 검증이 아니다. text가 있는 차시도 메시지가 필요한 명령에서만 공백이 아닌 값을 요구한다. 공백이 포함된 메시지는 CMD 큰따옴표로 묶어 한 인자로 전달한다. 메시지가 -로 시작해 옵션으로 해석되면 ID 뒤에 `--`를 넣어 옵션 해석을 끝낸다.

`load_dotenv(".env", override=False, interpolate=False)`는 현재 작업 폴더의 파일을 읽되 이미 있는 환경변수를 덮어쓰지 않고 `${...}` 치환을 끈다. override의 기본값은 False, interpolate의 기본값은 True이므로 후자는 명시적으로 바꾼다. `os.getenv("KEY", "")`는 해당 환경변수 또는 없을 때의 빈 문자열을 가져온다. 두 역할을 구분한다.

Redis host·port는 외부 설정에서 읽는다. 생략 시 기본 localhost·6379지만 여기서는 필수 검사 후 명시한다. DB는 기본 0이다. `decode_responses=True`는 str 응답을 사용하며 기본 False면 bytes 응답을 받는다. socket_connect_timeout=1은 연결, socket_timeout=1은 소켓 읽기·쓰기에 각각 1초 한도를 둔다. 확인한 redis-py 8.1.0의 기본값은 각각 5초다. 자동 재시도 때문에 전체 실패 표시까지의 시간이 1초를 넘을 수 있다. with 종료 시 이 클라이언트가 소유한 연결 풀을 닫는다. SET의 ex=60은 저장 시점부터 60초이며 생략하면 새 키에 만료가 없다. GET은 만료를 연장하지 않는다.
### 실제 참고한 자료

확인일: 2026-11-02. 아래 문서의 사용 API·동작을 실제 확인하고 자체 예제로 구성했다.

- [Redis cache-aside with redis-py](https://redis.io/docs/latest/develop/use-cases/cache-aside/redis-py/): HIT/MISS, 원본 복원과 쓰기 후 무효화의 책임을 참고했다. 원문의 웹서버·Lua 잠금은 도입하지 않고 단일 main.py와 순차 CLI로 줄였다.
- [Redis session store](https://redis.io/docs/latest/develop/use-cases/session-store/redis-py/): 세션이 원본 이력의 사본과 다른 상태라는 구분을 참고했다. 세션을 쓰는 차시에서만 코드에 적용한다.
- [Python sqlite3 공식 문서](https://docs.python.org/3.12/library/sqlite3.html): 매개변수 바인딩, executemany, 트랜잭션과 연결 종료를 확인했다. [SQLite AUTOINCREMENT](https://www.sqlite.org/autoinc.html)에서 번호 재사용 특성을 확인했다.
- [Python argparse](https://docs.python.org/3.12/library/argparse.html), [Redis SET](https://redis.io/docs/latest/commands/set/), [redis-py Production usage](https://redis.io/docs/latest/develop/clients/redis-py/produsage/): 입력 옵션·만료·예외 처리 범위를 확인했다.
- Redis 제공 공개 튜토리얼 [What is Redis?](https://redis.io/tutorials/what-is-redis/)(2026-09-01): 메모리·영속화·캐시 사용 사례를 설명하는 순서를 참고했다. 기술 제공자의 교육자료라는 근거로 선택했다. 수강생·조회 수치는 확인되지 않아 인기 순위를 주장하지 않는다. 다른 링크의 공개·갱신일은 확인되지 않았다.

## 3. 코드 제공

### 1) 실행 환경과 Redis 준비

현재 차시를 `C:\AI4\redis_course\lesson06`에 둔다. 실제 위치가 다르면 cd 경로만 바꾼다. 모든 실행 명령은 Windows CMD 기준이며 Redis 컨테이너는 하나만 사용한다. Docker Desktop을 켜고 Linux 컨테이너 모드로 준비한다. 최초 설치는 [Docker 공식 Windows 안내](https://docs.docker.com/desktop/setup/install/windows-install/)를 따른다.

먼저 엔진과 컨테이너 상태를 조회한다.

```bat
docker info
docker ps -a --filter name=kdt-redis
```

| 부분 | 의미와 판정 |
|---|---|
| docker info | Docker 엔진 정보 조회. 서버 정보가 나와야 엔진이 준비됨 |
| docker ps | 컨테이너 목록 조회, 상태를 바꾸지 않음 |
| -a | 중지된 항목도 포함, 생략하면 실행 중인 항목만 표시 |
| --filter name=kdt-redis | 이름에 해당 문자열이 포함된 항목만 조회 |

목록의 STATUS가 Up이면 실행 중이다. Exited이면 아래 start로 시작한다. 목록 제목만 나오면 대상이 없는 것이므로 그 아래 최초 생성 명령을 쓴다.

```bat
docker start kdt-redis
```

start는 이미 있는 컨테이너를 시작한다. 생성은 하지 않는다. **기존 컨테이너가 없을 때만** 다음을 실행한다.

```bat
docker run -d --name kdt-redis -p 127.0.0.1:6379:6379 redis:7.4 redis-server --save "" --appendonly no
```

| 부분 | 의미 |
|---|---|
| docker run | 새 컨테이너 생성·실행 |
| -d | 백그라운드 실행 |
| --name kdt-redis | 이후 명령에서 쓸 컨테이너 이름 |
| -p 127.0.0.1:6379:6379 | 내 PC 로컬 주소의 6379를 컨테이너 6379에 연결 |
| redis:7.4 | Redis 7.4 계열 이미지, 없으면 다운로드 |
| redis-server | 컨테이너 내부에서 실행할 서버 프로그램 |
| --save "" | 자동 RDB 스냅샷 저장을 끔. 큰따옴표 안은 빈 문자열 |
| --appendonly no | AOF 디스크 기록을 끔 |

이 로컬 실습은 비밀번호와 디스크 보존을 쓰지 않는다. 컨테이너 중지·재시작 시 Redis 세션·캐시는 보존하지 않지만 PC의 sqlite 파일은 유지된다. 원격 공개 서버용 설정은 아니다.

```bat
docker exec kdt-redis redis-cli PING
docker exec kdt-redis redis-server --version
```

`docker exec`는 실행 중인 컨테이너 안에서 명령을 수행한다. 대상 이름 다음 `redis-cli PING`은 Redis 서버의 응답을 확인하며 PONG이 정상이다. `redis-server --version`은 설치 프로그램 버전만 출력하고 종료하며 새 서버를 시작하지 않는다. ps의 실행 상태, PING의 서버 응답, --version의 설치 버전은 서로 다른 확인이다. 이 PING은 컨테이너 내부 확인이며 PC의 Python 연결은 실습 명령 실행으로 확인한다.

### 2) Python 환경과 파일

CMD에서 현재 차시 폴더로 이동한다. `/d`는 드라이브도 함께 바꾸는 cd 옵션이다.

```bat
cd /d C:\AI4\redis_course\lesson06
python --version
```

버전이 출력되면 Python 자체가 실행되는 것이다. 다음 명령은 새 가상환경이 필요할 때 한 번 수행한다.

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install redis==8.1.0 python-dotenv==1.2.4
```

| 명령의 부분 | 역할 |
|---|---|
| python -m venv .venv | 현재 Python의 venv 모듈로 .venv 폴더에 격리 환경 생성 |
| .venv\Scripts\activate | 현재 CMD에서 해당 환경의 Python·패키지를 사용하도록 활성화 |
| python -m pip install | 현재 Python에 연결된 pip로 패키지 설치 |
| redis==8.1.0 | 실습에서 확인한 Redis 클라이언트 버전 지정, 서버 설치가 아님 |
| python-dotenv==1.2.4 | .env 로딩 패키지 버전 지정 |

이미 C:\AI4의 정상 가상환경을 쓰고 있다면 차시마다 새로 만들 필요는 없다. 그 환경의 Python 경로를 먼저 확인하고 현재 차시로 cd한 뒤 필요한 패키지만 설치한다. 비활성 상태라면 실제 환경 위치인 C:\AI4\.venv\Scripts\activate처럼 활성화 파일의 절대 경로를 사용한다. 현재 차시 폴더에서 만든 .venv와 부모 폴더의 .venv는 다른 환경이다. 위 목록은 직접 의존성 목록이며 모든 간접 의존성까지 고정한 잠금 파일이 아니다. 검증 Python은 3.12.14이며 수업에서 확인한 다른 버전은 아래 확인 절차로 실행 여부를 점검한다.

```bat
python -c "import sys; print(sys.executable)"
```

`-c`는 따옴표 안 Python 코드를 즉시 실행한다. sys.executable은 실제 Python 경로다. 선택한 환경의 경로가 나와야 한다. 차시 안에 만들었다면 해당 차시의 .venv\Scripts\python.exe, 부모 환경을 재사용한다면 C:\AI4\.venv\Scripts\python.exe다. 가상환경 이름 표시만으로 정상이라고 판단하지 않는다.

과거 Miniconda 경로를 찾지 못한다는 오류가 나면 활성화 표시만으로 환경이 정상이라고 판단하지 않는다. deactivate로 나온 뒤 where와 버전 확인을 한다.

```bat
deactivate
where python
python --version
```

deactivate는 현재 가상환경을 종료하고 where는 실행 파일 후보 경로를 조회한다. WindowsApps 경로가 보여도 실제 실행 여부는 `python --version`으로 확인한다. 외부 Python이 정상일 때만 오래된 환경을 백업하고 재생성한다.

```bat
ren .venv .venv_backup
python -m venv .venv
.venv\Scripts\activate
python -m pip install redis==8.1.0 python-dotenv==1.2.4
```

ren은 폴더 이름 변경이며 프로젝트 코드는 삭제하지 않는다. 이미 백업 폴더가 있으면 다른 백업 이름을 쓴다. 재생성 뒤 python --version과 위의 sys.executable 명령으로 실행 버전·경로를 다시 확인한다. 외부 Python도 실패하면 설치·경로 문제부터 해결하고 다음으로 진행한다.

### 3) .env 설정과 배포 파일

```bat
copy .env.example .env
notepad .env
```

copy는 예시 파일을 실제 설정 파일로 복사하고 notepad는 편집기를 연다. 기존 .env가 있으면 덮어쓰지 말고 현재 차시의 키만 확인한다.

```dotenv
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
SQLITE_PATH=chat06.db
```

| 키 | 의미 |
|---|---|
| REDIS_HOST | PC에서 접근할 Redis 주소 |
| REDIS_PORT | Docker에서 PC 쪽으로 공개한 포트 |
| SQLITE_PATH | 현재 폴더 기준 원본 DB 파일 경로. init이 생성하며 다음 실행에도 유지 |

필수값이 빈 값·공백이면 실패한다. 포트는 1~65535 정수여야 한다. 로컬 예시에 비밀번호 항목은 없다. 비밀번호가 필요한 다른 설정에서는 #·$·공백을 작은따옴표로 감싸고 interpolate=False로 원문을 유지할 수 있다. 비밀번호를 무조건 strip하지 않는다.

이미 CMD 환경변수에 같은 키가 있으면 .env보다 우선한다. 파일 값을 시험하려면 현재 CMD에서 다음처럼 해제한다. set의 등호 오른쪽이 비어 있으면 변수를 해제하며, 접속값 자체를 출력할 필요는 없다.

```bat
set REDIS_HOST=
set REDIS_PORT=
set SQLITE_PATH=
```

.env가 없어도 필수 환경변수가 모두 있으면 실행할 수 있다. 설정 파일은 현재 작업 폴더 기준이다. 변경 후 프로그램은 종료하고 다시 실행한다.

| 파일 | 역할 |
|---|---|
| lesson06.md | 설명·전체 코드·실행·예상 결과·프롬프트 |
| main.py | 실행 로직과 SQL을 모두 포함 |
| .env.example | 가짜 로컬 설정 예시 |
| .gitignore | .env·가상환경·캐시·DB 파일을 Git에서 제외 |
| lesson_scope.json | 내부 품질 검증 메타데이터. 실행 파일·접속 설정이 아님 |

실행하면 생기는 chat06.db는 원본 데이터 파일이며 배포 ZIP에는 포함하지 않는다. .gitignore 내용은 다음과 같다. 이미 추적 중인 파일을 자동 해제하는 기능은 아니다.

```gitignore
.env
.venv/
__pycache__/
*.db
*.db-*
```

### main.py 전체 코드

```python
# argparse는 명령 입력, json은 메시지 변환, sqlite3는 파일 기반 원본 저장에 사용한다.
import argparse
import json
import os
import sqlite3
from contextlib import closing  # sqlite 연결을 블록 종료 시 실제로 닫는다.

import redis
from dotenv import load_dotenv

DEMO_USERS = {"demo-a": "민수", "demo-b": "지연"}
CACHE_TTL = 60  # 캐시의 수명(초). 원본 DB의 수명과 다르다.
MAX_MESSAGES = 6  # 원본 전체 중 최근 여섯 메시지만 캐시·문맥에 사용한다.


def read_settings():
    # 현재 폴더의 .env를 읽되 기존 환경변수와 특수문자 원문을 보존한다.
    load_dotenv(".env", override=False, interpolate=False)
    host = os.getenv("REDIS_HOST", "")
    port_text = os.getenv("REDIS_PORT", "")
    db_path = os.getenv("SQLITE_PATH", "")
    if not host.strip() or not port_text.strip() or not db_path.strip():
        raise ValueError("REDIS_HOST, REDIS_PORT, SQLITE_PATH의 필수값을 확인하세요.")
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError("REDIS_PORT는 1~65535 범위의 정수여야 합니다.") from None
    if not 1 <= port <= 65535:
        raise ValueError("REDIS_PORT는 1~65535 범위의 정수여야 합니다.")
    return host, port, db_path


def initialize(conn):
    # SQL은 main.py에 직접 둔다. AUTOINCREMENT는 삭제된 최대 ID의 재사용도 방지한다.
    with conn:  # 정상 종료 시 COMMIT, 쓰기 중 예외 시 ROLLBACK한다. 연결 종료는 하지 않는다.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL
            )
        """)
        if conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0:
            # executemany의 ?에는 각 튜플 값을 바인딩한다. SQL 문자열을 이어 붙이지 않는다.
            conn.executemany(
                "INSERT INTO messages (owner, role, content) VALUES (?, ?, ?)",
                [
                    ("demo-a", "user", "내 이름은 민수"),
                    ("demo-a", "assistant", "모의 응답: 내 이름은 민수"),
                    ("demo-b", "user", "내 이름은 지연"),
                    ("demo-b", "assistant", "모의 응답: 내 이름은 지연"),
                ],
            )
    print("원본 준비 완료: 기존 데이터가 있으면 유지합니다.")


def read_source(conn, owner):
    # owner는 사용자 구분, LIMIT은 최근 개수다. DESC로 최신 항목을 고른다.
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE owner = ? ORDER BY id DESC LIMIT ?",
        (owner, MAX_MESSAGES),
    ).fetchall()
    # 모델에는 과거→현재 순서가 필요하므로 조회 결과를 다시 뒤집는다.
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def decode_history(raw):
    try:
        messages = json.loads(raw)  # JSON 문자열을 Python 목록으로 되돌린다.
    except json.JSONDecodeError:
        raise ValueError("캐시의 JSON 형식을 확인하세요.") from None
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        raise ValueError("캐시의 메시지 목록 형식을 확인하세요.")
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in ("user", "assistant")
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError("캐시의 role/content 형식을 확인하세요.")
    return messages


def cache_key(conn, owner):
    # 원본의 최신 ID를 버전으로 사용한다. 이 작은 SQL 조회는 HIT일 때도 실행한다.
    version = conn.execute(
        "SELECT COALESCE(MAX(id), 0) FROM messages WHERE owner = ?", (owner,),
    ).fetchone()[0]
    return f"lesson06:history:{owner}:v{version}"

def load_history(conn, client, owner):
    key = cache_key(conn, owner)
    raw = client.get(key)
    if raw is not None:  # 빈 목록을 담은 문자열 "[]"도 유효한 HIT다.
        return decode_history(raw), "HIT"
    messages = read_source(conn, owner)
    # ensure_ascii=False는 한글을 읽기 쉬운 문자로 저장한다. ex는 초 단위 만료다.
    client.set(key, json.dumps(messages, ensure_ascii=False), ex=CACHE_TTL)
    return messages, "MISS"

def save_turn(conn, owner, text, reply):
    # 한 턴의 두 메시지를 같은 sqlite 트랜잭션에 넣는다. 둘째 INSERT 실패 시 모두 취소된다.
    with conn:
        conn.executemany(
            "INSERT INTO messages (owner, role, content) VALUES (?, ?, ?)",
            [(owner, "user", text), (owner, "assistant", reply)],
        )
    print("원본 저장 완료: 2개 메시지")


def invalidate(client, key):
    print("이전 캐시 삭제 수:", client.delete(key))  # 원본 COMMIT 이후에만 호출한다.

def show_history(messages, source):
    print("조회 경로:", source)
    if not messages:
        print("대화 이력이 없습니다.")
    for index, message in enumerate(messages, start=1):  # 표시 번호만 1부터 시작한다.
        print(f"{index}. {message['role']}: {message['content']}")

def main():
    parser = argparse.ArgumentParser(description="원본 저장 후 버전으로 캐시 갱신")
    parser.add_argument("command", choices=['init', 'history', 'add', 'evict'], help="실행할 동작")
    # init에는 value가 없으므로 ?로 생략을 허용한다. 명령별 필수 여부는 아래에서 검사한다.
    parser.add_argument("value", nargs="?", default="", help="가상 사용자 ID")
    parser.add_argument("text", nargs="?", default="", help="add에서만 사용하는 메시지")
    args = parser.parse_args()
    if args.command == "init":
        if args.value or args.text:
            raise ValueError("init에는 추가 인자를 넣지 마세요.")
    elif not args.value.strip():
        raise ValueError("이 명령에는 사용자 ID가 필요합니다.")
    if args.command == "add" and not args.text.strip():
        raise ValueError("메시지는 공백이 아닌 문자열이어야 합니다.")
    if args.command != "add" and args.text:
        raise ValueError("메시지는 add 명령에서만 사용하세요.")
    host, port, db_path = read_settings()
    if args.command != "init" and not os.path.isfile(db_path):
        raise ValueError("원본 DB가 없습니다. 현재 폴더와 SQLITE_PATH를 확인하고 init을 실행하세요.")
    # timeout=5는 sqlite 쓰기 잠금 대기 한도(초)다. closing은 연결 종료를 담당한다.
    with closing(sqlite3.connect(db_path, timeout=5)) as conn:
        if args.command == "init":
            initialize(conn)  # Redis가 꺼져 있어도 원본 초기화는 가능하다.
            return
        # 객체 생성 시 연결 성공을 단정하지 않는다. 필요한 명령이 실제 연결을 수행한다.
        with redis.Redis(
            host=host,                 # 환경설정의 Redis 주소
            port=port,                 # PC에 공개한 포트
            decode_responses=True,     # True: str 응답, 기본 False: bytes 응답
            socket_connect_timeout=1,  # 연결 단계 제한(초), 기본 5초 대신 짧게 확인
            socket_timeout=1,          # 소켓 읽기/쓰기 제한(초), 전체 실행시간 제한은 아님
        ) as client:
            if args.value not in DEMO_USERS:
                raise ValueError("demo-a 또는 demo-b를 사용하세요.")
            owner = args.value
            if args.command == "history":
                messages, source = load_history(conn, client, owner)
                show_history(messages, source)
            elif args.command == "evict":
                print("삭제한 캐시 수:", client.delete(cache_key(conn, owner)))
            else:  # add: 캐시가 아니라 원본에 한 턴을 먼저 저장한다.
                old_key = cache_key(conn, owner)
                save_turn(conn, owner, args.text, f"모의 응답: {args.text}")
                invalidate(client, old_key)



if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print("입력/접근/설정 오류:", exc)  # 직접 만든 고정 메시지이며 설정값은 출력하지 않는다.
        raise SystemExit(1)
    except redis.exceptions.RedisError as exc:
        print("Redis 오류:", type(exc).__name__)
        print("서버 상태를 확인하세요. 앞서 원본 저장 완료가 출력됐다면 저장은 반영되었습니다.")
        raise SystemExit(1)
    except sqlite3.Error as exc:
        print("원본 DB 오류:", type(exc).__name__)
        print("DB 경로·권한·init 실행 여부를 확인하세요. 원본 오류는 캐시로 숨기지 않습니다.")
        raise SystemExit(1)
```

### 4) 변경 전 캐시 만들기

```bat
python main.py init
python main.py evict demo-a
python main.py history demo-a
python main.py history demo-a
```

init은 원본 준비, evict는 **현재 버전의 캐시만** 삭제, history는 이력 조회다. 최초 실행·가상 데이터 그대로라면 MISS 다음 HIT가 나오고 민수 이력 두 개가 보인다. 이전 실행에서 이미 대화를 추가했다면 그 원본이 유지되므로 개수는 더 많을 수 있다. DB 파일을 지우지 말고 아래처럼 새 메시지가 보이는지로 검증한다.

### 5) 원본 추가와 무효화

```bat
python main.py add demo-a "Redis 캐시 갱신을 연습합니다"
python main.py history demo-a
python main.py history demo-a
```

| 부분 | 역할 |
|---|---|
| add | 이번 main.py에서 구현한 한 턴 추가 명령, Python 기본 명령이 아님 |
| demo-a | 원본 owner와 캐시 이름을 결정하는 가상 사용자 ID |
| 큰따옴표 안 메시지 | 하나의 text 인자. 공백 때문에 큰따옴표로 묶음 |

정상 add는 `원본 저장 완료: 2개 메시지`, `이전 캐시 삭제 수: 1`을 출력한다. 이미 이전 캐시가 만료됐다면 삭제 수 0도 정상이다. 이후 조회는 새 버전의 MISS 다음 HIT여야 하며 마지막 두 메시지는 다음이다.

```text
user: Redis 캐시 갱신을 연습합니다
assistant: 모의 응답: Redis 캐시 갱신을 연습합니다
```

### 6) 키 버전 관찰과 사용자 분리

```bat
docker exec kdt-redis redis-cli --scan --pattern "lesson06:history:demo-a:*"
python main.py history demo-b
```

redis-cli의 --scan은 SCAN 기반으로 키를 순회하고 --pattern은 표시할 이름 패턴을 제한한다. 별표는 키 끝의 여러 버전 문자열을 뜻한다. 생성·삭제는 하지 않으며, 동시 변경 중 일관된 스냅샷을 보장하는 명령은 아니다. 앞서 PING으로 서버 실행을 확인한 뒤 사용한다. 정상 순차 실행에서는 현재 버전 키가 보이고, 만료됐다면 결과가 없을 수도 있다. 버전 숫자는 실제 원본 상태에 따라 달라진다. B는 지연 이력을 보여주며 A의 새 문장이 섞이면 안 된다.

정리 목적의 evict도 현재 버전 키만 지운다. 모든 Redis 데이터나 원본을 지우는 명령이 아니다. 다음 history로 원본에서 복원된다.

```bat
python main.py evict demo-a
python main.py history demo-a
```

### 오류 확인과 종료·재시작

| 증상 | 확인·복구 |
|---|---|
| 원본 DB 없음 | 현재 폴더와 SQLITE_PATH를 확인하고 python main.py init 실행 |
| no such table에 해당하는 OperationalError | 기존 파일이 다른 실습 DB인지 확인하고 현재 경로에서 init 수행 |
| 입력/접근/설정 오류 | 키 누락·공백·포트·명령별 필수 인자를 확인 |
| Redis ConnectionError | Docker 엔진·컨테이너·PC 공개 포트 확인 |
| Redis ResponseError | 키 자료형이 String인지, 세션과 캐시 키를 혼동하지 않았는지 확인 |
| 원본 DB 오류 | 파일 경로·디렉터리 권한·쓰기 잠금을 확인. Redis 오류로 바꿔 해석하지 않음 |
| 명령 사용 오류 | python main.py --help로 허용 명령과 인자 위치 확인 |

환경 오류는 백업한 .env의 REDIS_PORT를 빈 값·abc·0·65536으로 바꿔 같은 명령을 실행해 확인하고 6379로 복원한다. 파일 우선 검사 전 CMD의 기존 환경변수를 해제한다. SQLITE_PATH 누락·공백도 필수값 오류여야 한다. 없는 DB에서 history를 실행하면 init 안내 후 종료하며 자동으로 다른 경로의 빈 원본을 만들어 성공 처리하지 않는다.

명령 직후 아래를 실행하면 종료 코드를 본다.

```bat
echo %ERRORLEVEL%
```

echo는 CMD 변수 ERRORLEVEL을 표시한다. 정상 완료는 0, 직접 검사한 입력·접근·설정 오류와 처리하지 못한 Redis/원본 오류는 1, argparse의 잘못된 명령·인자 사용은 2다. 장애 대체가 가능한 차시에서 sqlite 결과를 정상 반환하면 0일 수 있으므로 조회 경로와 함께 읽는다.

각 Python 명령은 수행 후 종료한다. 중단은 Ctrl+C다. 실습을 끝낼 때:

```bat
deactivate
docker stop kdt-redis
```

deactivate는 CMD 가상환경 사용을 종료하고 docker stop은 컨테이너를 중지한다. 컨테이너를 삭제하지 않는다. 다시 시작할 때 Docker Desktop을 켜고 docker start kdt-redis, 현재 폴더에서 가상환경 활성화를 수행한다. sqlite 원본은 남지만 Redis의 실습 세션·캐시는 없으므로 세션이 필요한 차시는 새로 발급한다. 기존 DB 파일을 교체하거나 삭제하는 것은 이 실습의 초기화 절차가 아니다. init은 기존 데이터를 유지한다.

### 검증 범위

실제 Redis에서 한 턴 COMMIT과 버전 키 변경, 새 버전 MISS→HIT, 새 메시지 반영, 원본 열 행이 남아도 캐시는 여섯 메시지만 사용하는지, B 이력이 변하지 않는지를 확인했다. sqlite 트리거로 둘째 INSERT 실패를 유도해 두 행 전체의 ROLLBACK을 검사했다. 별도 DEL 오류 주입으로 COMMIT된 원본이 유지되고 오류가 전파되며 다음 버전은 달라지는 것을 확인했다. Redis 중단 시 읽기는 오류 종료함을 확인했다.

공통 검증 환경은 Python 3.12.14, redis-py 8.1.0, python-dotenv 1.2.4, SQLite 3.53.1, 실제 Redis 6.2.14의 로컬 TCP 연결이다. 배포 코드와 같은 main.py를 임시 차시 폴더로 복사하고 python main.py 명령으로 실행했다. 원본 없는 상태, init 반복, 허용되지 않은 명령·인자, 필수 설정 누락·공백·잘못된 포트, .env 없이 환경변수만 제공, 환경변수 우선순위와 합성 특수문자 경로 보존을 확인했다. 실제 .env·DB·세션 값은 배포하지 않는다.

Windows CMD·Docker Desktop·redis:7.4 이미지의 설치·실행과 Python 3.13 환경은 이 검증 환경에서 실행하지 않았다. Docker 명령은 공식 문서와 대조했으며 위 PING과 현재 차시 실행 명령으로 현장에서 확인한다. 코드 실행 검증 서버 버전은 설치 안내의 Redis 7.4와 다르다. 실제 LLM API·동시 요청·분산 트랜잭션·중복 요청의 정확히 한 번 처리는 검증 범위가 아니다. 스킬의 파일 범위 정적 검사와 문서/코드 일치 및 ZIP 검사를 통과했다.

## 4. Vibe 코딩에 유용한 프롬프트

### 원본 저장과 무효화 순서 리뷰

```text
lesson06/main.py와 lesson06.md를 읽고 add가 실행되는 순서를 설명해줘.
sqlite COMMIT이 실패하면 캐시 삭제까지 진행하지 않는지,
COMMIT 후 DEL이 실패해도 원본이 저장된 상태라는 점을 확인해줘.
이전 캐시 키가 남아 있을 때 새 원본 버전의 조회가 이전 사본을 재사용하지 않는지도 검증해줘.
HIT에도 MAX(id) SQL이 실행됨을 숨기지 말고 UPDATE/DELETE 지원으로 과장하지 마.
기존 동작을 바꾸거나 다른 패키지·모듈을 추가하지 마.
.env 원문·실제 접속값·개인 대화는 읽거나 출력·전송하지 마.
실제 실행한 결과와 남은 한계를 구분해줘.
```