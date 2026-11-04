# 7교시. Redis 장애에서 캐시는 대체하고 세션 검증은 거절하기

## 1. 학습목표

- 이력 캐시 장애와 원본 DB 장애를 구분한다.
- 캐시 읽기·쓰기 실패 시 sqlite 결과를 사용한다.
- 원본 COMMIT 이후 캐시 삭제 실패를 저장 실패와 구분한다.
- 세션 저장소가 응답하지 않으면 접근을 거절한다.

## 2. 중요 알고리즘 및 코드를 읽을 때 반드시 알아야 할 내용

### 6교시의 예외 종료를 정책으로 바꾸기

캐시와 원본은 같은 책임이 아니다. 캐시는 다시 만들 사본이므로 읽지 못해도 원본이 정상이면 결과를 반환할 수 있다. 세션은 현재 접근을 허용할 근거이므로 읽지 못했는데 임의로 유효하다고 대체하면 안 된다. 이번 중심 개념은 이 책임에 따른 장애 처리 정책이다.

| 상황 | 처리·표시 | 종료 |
|---|---|---|
| 캐시 읽기 실패 | sqlite 결과, BYPASS | 원본 정상이면 0 |
| 캐시 없음 | 원본 조회·캐시 저장, MISS | 0 |
| 캐시 저장만 실패 | 원본 결과, MISS_WRITE_FAILED | 0 |
| 캐시 JSON/스키마 손상 | 원본으로 교체 후 MISS | 원본 정상이면 0 |
| 원본 DB 오류 | 원본 DB 오류 표시, 캐시로 숨기지 않음 | 1 |
| 세션 조회 실패·없음·만료 | 접근 거절 | 1 |

HIT는 Redis 사본을 썼다는 뜻이고 BYPASS는 Redis를 읽지 못해 원본을 썼다는 뜻이다. 주어진 상황에서 실패한 읽기를 무한히 반복하거나 딕셔너리를 가짜 세션으로 만들어 통과시키지 않는다. 잘못된 캐시 원문·세션 ID·접속값을 예외 출력에 넣지 않는다.

### 읽기 명령과 세션 검사 명령을 분리해 비교

이번 history/add는 5~6교시처럼 가상 사용자 ID를 직접 넣는 **신뢰된 로컬 실습용 원본 접근**이다. 웹에서 인증 없이 허용할 API가 아니다. 별도 create/session 명령으로 같은 Redis 장애 때 세션 검증은 거절되는지 비교한다. 세션이 꺼져도 사용자 인증을 우회해 history를 실행하도록 만든 공개 서비스라는 뜻이 아니다. 8교시에서는 history/chat 앞에 세션 검증을 실제로 연결한다.

세션은 `lesson07:session:ID`에 사용자 ID를 String으로 저장하고 ex=300을 함께 준다. secrets의 32는 난수 바이트 수이며 sid_ 접두사로 CLI 옵션 오인을 피한다. 조회는 TTL을 연장하지 않는다. create는 가상 사용자 선택이며 실제 비밀번호 로그인 인증이 아니다.

### 원본 저장이 성공한 뒤 DEL이 실패하면

6교시의 버전 키를 계속 사용한다. add가 COMMIT되면 다음 조회의 버전이 바뀌므로 이전 키 삭제가 실패해도 그 옛 키를 다시 선택하지 않는다. 삭제 실패는 경고로 표시하고 원본 저장 성공을 보존한다. 옛 키가 남으면 원래 TTL까지 메모리를 차지할 수 있다.

이 설계는 모든 예외를 삼키는 것이 아니다. sqlite 오류는 전파하고 세션 오류는 접근 거절한다. 사용자가 같은 add를 반복 실행하면 새 턴이 추가되므로 정확히 한 번 저장을 보장하지 않는다. 동시 생성·쓰기·분산 트랜잭션도 구현하지 않는다.

### sqlite 원본 조회와 JSON 변환을 읽는 방법

`messages`의 id는 저장 순서를 정하는 정수, owner는 가상 사용자 ID, role은 user/assistant, content는 메시지다. PRIMARY KEY는 행 식별자이고 AUTOINCREMENT는 자동 번호가 과거에 사용한 번호를 재사용하지 않도록 한다. role의 CHECK는 두 역할 외 값의 저장을 막는다. 이 예제는 원본 메시지를 추가만 하고 수정·삭제하지 않는다.

`WHERE owner = ?`와 `(owner, MAX_MESSAGES)` 같은 매개변수 바인딩은 값을 SQL 문법과 분리한다. 물음표에 문자열을 직접 이어 붙이지 않는다. `ORDER BY id DESC LIMIT ?`로 최신 여섯 개를 고른 뒤 reversed로 과거→현재 순서로 바꾼다. 원본의 나머지 행을 삭제하는 코드는 아니다. `fetchall()`은 조회 결과 전체를 튜플 목록으로 가져오고, 역할·내용을 사전으로 만든다.

`with conn:`은 정상 쓰기를 COMMIT하고 예외 시 ROLLBACK하는 범위다. 연결 자체를 닫지는 않는다. `closing(sqlite3.connect(...))`이 블록 종료 시 연결을 닫는다. connect의 첫 인자는 파일 경로, timeout=5는 다른 쓰기의 잠금이 풀리기를 기다리는 초이며 기본값도 5다. 정상적인 로컬 파일 경로와 순차 명령 실행을 사용한다. sqlite3는 Python 내장 모듈이라 별도 pip 설치가 없다.

`json.dumps(messages, ensure_ascii=False)`는 메시지 목록을 한 JSON 문자열로 만든다. False는 기본 True와 달리 한글을 문자로 유지한다. `json.loads(raw)`는 이를 Python 목록으로 복원한다. 캐시에는 최근 메시지 목록 전체를 String 하나로 저장한다. 4교시의 List는 메시지 추가를 연습하기 위한 것이었고, 이번에는 원본에서 읽은 조회 결과를 통째로 바꿔 넣는 사본이므로 String을 선택한다. 응답 결과를 재사용하는 LLM 응답 캐시와는 다른 **대화 이력 캐시**다.

### 명령줄 입력과 연결 옵션

add_argument는 입력 규칙을 등록하고 parse_args가 실제 명령줄을 해석해 args 필드를 만든다. 명령 이름을 등록하는 순간 저장·조회가 실행되는 것은 아니다.

| 실제 입력 | args와 실행 흐름 | 결과 |
|---|---|---|
| python main.py history demo-a | command=history, value=demo-a, text="" → load_history → 캐시 실패 시 read_source | sqlite BYPASS 가능 |
| python main.py session sid_DEMO | command=session, value=sid_DEMO → require_session → Redis GET | 유효 세션만 사용자 표시 |

sid_DEMO는 해석을 설명하는 합성값이며 실제 실행에는 create가 발급한 전체 ID를 넣는다. 두 명령은 책임 비교를 위해 분리된 로컬 실습이며 인증된 웹 API가 아니다.

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

현재 차시를 `C:\AI4\redis_course\lesson07`에 둔다. 실제 위치가 다르면 cd 경로만 바꾼다. 모든 실행 명령은 Windows CMD 기준이며 Redis 컨테이너는 하나만 사용한다. Docker Desktop을 켜고 Linux 컨테이너 모드로 준비한다. 최초 설치는 [Docker 공식 Windows 안내](https://docs.docker.com/desktop/setup/install/windows-install/)를 따른다.

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
cd /d C:\AI4\redis_course\lesson07
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
SQLITE_PATH=chat07.db
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
| lesson07.md | 설명·전체 코드·실행·예상 결과·프롬프트 |
| main.py | 실행 로직과 SQL을 모두 포함 |
| .env.example | 가짜 로컬 설정 예시 |
| .gitignore | .env·가상환경·캐시·DB 파일을 Git에서 제외 |
| lesson_scope.json | 내부 품질 검증 메타데이터. 실행 파일·접속 설정이 아님 |

실행하면 생기는 chat07.db는 원본 데이터 파일이며 배포 ZIP에는 포함하지 않는다. .gitignore 내용은 다음과 같다. 이미 추적 중인 파일을 자동 해제하는 기능은 아니다.

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
import secrets  # 가상 세션 ID를 생성한다.

import redis
from dotenv import load_dotenv

DEMO_USERS = {"demo-a": "민수", "demo-b": "지연"}
CACHE_TTL = 60  # 캐시의 수명(초). 원본 DB의 수명과 다르다.
MAX_MESSAGES = 6  # 원본 전체 중 최근 여섯 메시지만 캐시·문맥에 사용한다.
SESSION_TTL = 300  # 세션은 생성 후 5분 고정 만료다.


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
    return f"lesson07:history:{owner}:v{version}"

def load_history(conn, client, owner):
    key = cache_key(conn, owner)
    try:
        raw = client.get(key)
    except redis.exceptions.RedisError as exc:
        # 이력 캐시는 사본이다. 읽지 못하면 원본으로 대체하되 원본 오류는 숨기지 않는다.
        print("캐시 읽기 실패:", type(exc).__name__, "→ sqlite 원본 사용")
        return read_source(conn, owner), "BYPASS"
    if raw is not None:
        try:
            return decode_history(raw), "HIT"
        except ValueError:
            print("캐시 형식 오류 → sqlite 원본으로 교체")
    messages = read_source(conn, owner)
    try:
        # 캐시 저장 실패와 원본 조회 실패를 구분한다. JSON 한글은 그대로 유지한다.
        client.set(key, json.dumps(messages, ensure_ascii=False), ex=CACHE_TTL)
    except redis.exceptions.RedisError as exc:
        print("캐시 저장 실패:", type(exc).__name__, "→ 원본 조회 결과 반환")
        return messages, "MISS_WRITE_FAILED"
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
    try:
        print("이전 캐시 삭제 수:", client.delete(key))
    except redis.exceptions.RedisError as exc:
        # 원본 저장은 이미 성공했다. 새 버전 키를 사용하므로 이전 캐시를 재사용하지 않는다.
        print("이전 캐시 삭제 실패:", type(exc).__name__, "→ 새 버전 키로 구분")

def show_history(messages, source):
    print("조회 경로:", source)
    if not messages:
        print("대화 이력이 없습니다.")
    for index, message in enumerate(messages, start=1):  # 표시 번호만 1부터 시작한다.
        print(f"{index}. {message['role']}: {message['content']}")

def create_session(client, owner):
    if owner not in DEMO_USERS:
        raise ValueError("create에는 demo-a 또는 demo-b를 사용하세요.")
    # sid_는 난수가 -로 시작해 CLI 옵션으로 오인되는 것을 방지한다. 32는 난수 바이트 수다.
    session_id = "sid_" + secrets.token_urlsafe(32)
    client.set(f"lesson07:session:{session_id}", owner, ex=SESSION_TTL)
    print("SESSION_ID:", session_id)  # 가상 로컬 실습에서 다음 명령에 전달하기 위한 출력
    print("세션 사용자:", DEMO_USERS[owner])


def require_session(client, session_id):
    try:
        owner = client.get(f"lesson07:session:{session_id}")
    except redis.exceptions.RedisError:
        # 세션을 확인할 수 없는데 캐시 조회처럼 성공으로 대체해서는 안 된다.
        raise PermissionError("세션 확인 불가: Redis 장애이므로 접근을 거절합니다.") from None
    if owner not in DEMO_USERS:
        raise PermissionError("세션이 없거나 만료되어 접근을 거절합니다.")
    return owner

def main():
    parser = argparse.ArgumentParser(description="캐시 장애 대체와 세션 접근 거절")
    parser.add_argument("command", choices=['init', 'history', 'add', 'evict', 'create', 'session'], help="실행할 동작")
    # init에는 value가 없으므로 ?로 생략을 허용한다. 명령별 필수 여부는 아래에서 검사한다.
    parser.add_argument("value", nargs="?", default="", help="가상 사용자 또는 세션 ID")
    parser.add_argument("text", nargs="?", default="", help="add에서만 사용하는 메시지")
    args = parser.parse_args()
    if args.command == "init":
        if args.value or args.text:
            raise ValueError("init에는 추가 인자를 넣지 마세요.")
    elif not args.value.strip():
        raise ValueError("이 명령에는 사용자 또는 세션 ID가 필요합니다.")
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
            if args.command == "create":
                create_session(client, args.value)
                return
            if args.command == "session":
                owner = require_session(client, args.value)
                print("세션 사용자:", DEMO_USERS[owner])
                return
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
    except (ValueError, PermissionError) as exc:
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

### 세션 만료 시 재개 방법

세션은 생성 후 300초 고정이며 설명을 읽고 입력하는 중에도 시간이 흐른다. 조회·대화로 연장되지 않는다. 올바른 ID를 넣었는데 만료됐다면 create로 같은 가상 사용자의 새 세션을 만들고 현재 CMD 변수도 새 발급값으로 갱신한 뒤 해당 단계부터 다시 실행한다. 이전 ID의 일부만 고치지 않는다. 8교시는 사용자별 sqlite 원본이 유지되므로 새 세션에서도 같은 사용자의 최근 대화를 복원한다. 서버가 꺼졌다면 start와 PING을 먼저 확인한다.

### 4) 정상 상태 기준 만들기

```bat
python main.py init
python main.py evict demo-a
python main.py history demo-a
python main.py create demo-a
set SID_7=방금_출력된_SESSION_ID_전체
python main.py session %SID_7%
```

init·evict·history의 뜻은 원본 준비·현재 캐시 삭제·이력 조회다. create는 가상 A 세션을 만들고 SESSION_ID를 출력한다. 자리표시자 문구를 그대로 입력하지 말고 실제 발급값으로 바꾼다.

| 부분 | 의미 |
|---|---|
| set SID_7=실제발급값 | 현재 CMD 변수에 ID 보관. 등호 양옆 공백 없음 |
| %SID_7% | CMD가 변수의 실제 문자열로 치환 |
| session | main.py에 구현한 세션 검사 명령 |

session 결과 `세션 사용자: 민수`가 정상이다. 4교시의 세션 ID는 접두사가 달라 사용할 수 없다. 새 CMD를 열면 SID_7도 다시 설정해야 하며 .env에 저장되는 값이 아니다.

### 5) 서버 중단: 이력 조회와 세션 검사 비교

```bat
docker stop kdt-redis
python main.py history demo-a
python main.py session %SID_7%
echo %ERRORLEVEL%
```

docker stop은 해당 컨테이너를 중지하고 삭제하지 않는다. SQLite는 PC의 파일이라 계속 읽을 수 있다. history는 캐시 읽기 실패 안내 다음 `조회 경로: BYPASS`와 민수의 원본을 반환한다. session은 `세션 확인 불가: Redis 장애이므로 접근을 거절합니다.`를 표시하고 종료 코드 1이다. ERRORLEVEL은 바로 앞 명령의 종료 코드다.

### 6) 중단 중 원본 쓰기와 복구

```bat
python main.py add demo-a "Redis 중단 중에도 원본에 기록"
python main.py history demo-a
docker start kdt-redis
docker exec kdt-redis redis-cli PING
python main.py history demo-a
```

add는 원본 저장 완료 후 이전 캐시 삭제 실패 경고가 나온다. 다음 history는 BYPASS로 새 문장과 모의 응답을 보여준다. start는 기존 컨테이너 재시작, 이어 PONG이 서버 복구 기준이다. Redis 실습 데이터는 재시작으로 없으므로 복구 후 첫 history는 새 버전의 MISS다. sqlite에서 읽은 새 문장이 남아 있어야 한다.

이전 SID_7은 재시작으로 복원되지 않는다. 세션은 다시 만들어 변수도 갱신한다.

```bat
python main.py session %SID_7%
python main.py create demo-a
set SID_7=새로_발급된_SESSION_ID_전체
python main.py session %SID_7%
```

첫 session은 없는 세션 접근 거절, 새 발급 후에는 민수 조회가 정상이다.

### 7) 손상된 캐시 복구

먼저 현재 캐시 키를 조회한다.

```bat
docker exec kdt-redis redis-cli --scan --pattern "lesson07:history:demo-a:*"
```

--scan은 키 순회, --pattern은 조회 패턴이며 데이터 변경은 없다. 결과의 현재 버전 키를 아래 자리표시자 대신 넣는다. 여러 옛 키가 남아 있다면 최신 원본 ID에 해당하는 키를 고른다. 모호하면 evict 후 history로 현재 캐시를 만든 뒤 다시 조회한다.

```bat
docker exec kdt-redis redis-cli SET 실제_현재_캐시_키 broken EX 60
python main.py history demo-a
```

이 SET은 지정한 **실습용 캐시 한 개만** broken 문자열로 덮고 60초 만료를 준다. JSON이 아니므로 형식 오류 안내 후 sqlite 원본으로 교체한다. 다음 history는 HIT다. 다른 원본·세션 키나 다른 사람의 데이터에는 적용하지 않는다. 이 검사는 Redis 연결 오류와 데이터 형식 오류를 구분하기 위한 것이다.

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

실제 서버 중단에서 history BYPASS, session 접근 거절, 중단 중 add의 원본 COMMIT·캐시 삭제 경고·최신 원본 조회를 실행했다. 서버 재시작 뒤 원본은 유지되고 이전 세션은 복원되지 않음을 확인했다. 실제 Redis에 잘못된 JSON·스키마·키 자료형을 넣어 원본 대체를 검사했고 EXPIRE 1로 세션 만료를 가속 검사했다. 별도 오류 주입으로 SET만 실패할 때 원본 반환, DEL 실패 후 옛 캐시가 남아도 새 버전 선택, 원본 오류 전파, 둘째 INSERT 실패 시 한 턴 ROLLBACK을 확인했다. 세션 300초 전체 대기 검사는 하지 않았다.

공통 검증 환경은 Python 3.12.14, redis-py 8.1.0, python-dotenv 1.2.4, SQLite 3.53.1, 실제 Redis 6.2.14의 로컬 TCP 연결이다. 배포 코드와 같은 main.py를 임시 차시 폴더로 복사하고 python main.py 명령으로 실행했다. 원본 없는 상태, init 반복, 허용되지 않은 명령·인자, 필수 설정 누락·공백·잘못된 포트, .env 없이 환경변수만 제공, 환경변수 우선순위와 합성 특수문자 경로 보존을 확인했다. 실제 .env·DB·세션 값은 배포하지 않는다.

Windows CMD·Docker Desktop·redis:7.4 이미지의 설치·실행과 Python 3.13 환경은 이 검증 환경에서 실행하지 않았다. Docker 명령은 공식 문서와 대조했으며 위 PING과 현재 차시 실행 명령으로 현장에서 확인한다. 코드 실행 검증 서버 버전은 설치 안내의 Redis 7.4와 다르다. 실제 LLM API·동시 요청·분산 트랜잭션·중복 요청의 정확히 한 번 처리는 검증 범위가 아니다. 스킬의 파일 범위 정적 검사와 문서/코드 일치 및 ZIP 검사를 통과했다.

## 4. Vibe 코딩에 유용한 프롬프트

### 장애별 결과를 분리해 검증

```text
lesson07/main.py와 lesson07.md를 읽고 신뢰된 로컬 실습용 명령으로 검증해줘.
Redis 중단 시 history는 sqlite BYPASS, session은 접근 거절인지 확인해줘.
중단 중 add가 원본에 두 행을 저장하고 캐시 삭제 실패를 경고하는지도 확인해줘.
캐시 GET 성공 뒤 SET만 실패하는 경우는 별도 오류 주입으로 구분하고,
원본 sqlite 실패를 정상 캐시 결과로 숨기지 않는지 검사해줘.
세션 조회 실패를 가짜 로그인으로 대체하지 마. 실제 웹 인증이라고 주장하지 마.
기존 main.py를 수정하지 말고 .env·실제 계정·접속값·세션 ID 원문은 출력·전송하지 마.
합성 데이터만 사용하며 실제 네트워크 검사와 오류 주입 검사를 구분해줘.
```