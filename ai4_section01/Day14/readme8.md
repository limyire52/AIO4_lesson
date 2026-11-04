# 8교시. 세션·sqlite 원본·Redis 캐시를 연결한 대화 데모

## 1. 학습목표

- 세션 검증부터 문맥 조회·응답 생성·원본 저장까지 연결한다.
- 캐시 삭제 뒤에도 원본에서 복원한 문맥으로 응답하는지 확인한다.
- 사용자별 이력 분리와 로그아웃 후 원본 유지 정책을 검증한다.
- Redis 중단 때 세션 검증을 우회하지 않는지 확인한다.

## 2. 중요 알고리즘 및 코드를 읽을 때 반드시 알아야 할 내용

### 7교시에서 나눠 확인한 책임을 실제 호출 순서로 연결

이번 중심 개념은 통합 호출 흐름의 검증이다. 새로운 프레임워크 없이 익숙한 CLI와 함수들을 연결한다. create 외의 history/chat/evict/logout은 먼저 Redis 세션을 조회해 owner를 찾는다. 사용자가 임의 owner를 인자로 보내 대화에 접근하는 경로는 제공하지 않는다.

| 단계 | 사용 상태 | 실패 시 의미 |
|---|---|---|
| require_session | Redis 세션 ID→owner | 확인 불가·만료이면 접근 거절 |
| load_history | sqlite 최신 버전→Redis 캐시, 없으면 원본 | 인증을 통과한 이후 캐시 실패만 원본 대체 |
| make_demo_reply | 이전 이력·새 입력 | 규칙 기반 모의 응답 |
| save_turn | sqlite에 두 메시지 COMMIT | 실패하면 저장 오류 |
| invalidate | 이전 버전 Redis 캐시 삭제 | 실패해도 새 버전 키로 이전 사본과 분리 |

서버가 처음부터 꺼져 있으면 세션 검증에서 끝나므로 BYPASS까지 도달하지 않는다. 7교시의 인증 없는 로컬 원본 조회와 구분한다. 세션 검증에 성공한 뒤 캐시 명령만 실패한 경우에만 원본 대체가 가능하다. “캐시 장애 대체를 구현했으니 Redis가 꺼져도 로그인 대화가 된다”고 해석하지 않는다.

### 대화 수명과 세션 수명은 다르게 설계

4교시는 세션 ID마다 임시 대화를 만들었다. 이번에는 영구 원본을 익히기 위해 **가상 사용자별 한 개의 대화**를 유지한다. 세션은 300초 고정 만료이고, 새 세션으로 같은 사용자에 접속해도 그 사용자의 원본 대화를 다시 읽는다. 로그아웃은 세션 키만 지우며 원본·이력 캐시는 유지한다. 다른 사용자의 키는 공유하지 않는다. 대화별 다중 스레드는 이번 범위에 없다.

init은 A의 이름 민수와 B의 이름 지연을 포함한 가상 첫 턴을 준비한다. 기존 데이터가 있으면 유지한다. 이름을 다시 말하는 새 user 메시지가 있으면 최근 선언부터 찾는다. 계정 표시 이름과 대화에서 말한 이름은 서로 다른 출처다.

### Redis를 지워도 문맥을 복원할 수 있는지 확인

LLM 역할의 함수에는 load_history가 반환한 메시지 목록을 넘긴다. evict로 캐시만 지운 뒤 `내 이름이 뭐야?`를 실행해도 sqlite 원본에서 최근 선언을 복원하면 이름을 찾는다. 단, 최근 여섯 메시지에서 이미 잘린 정보까지 찾는 것은 아니다. 원본 전체는 남아도 문맥 조회 범위가 최근 여섯 개로 제한되어 있다는 점을 구분한다.

실제 모델 API는 호출하지 않는다. make_demo_reply는 정확히 일치하는 질문과 `내 이름은 ` 접두사를 확인하는 규칙 기반 함수다. 자연어 이해 성능·API 비용·모델 토큰 수를 검증하는 코드가 아니다. 실제 LLM 연동은 공급자별 메시지 형식·API 키·네트워크 오류 처리를 추가로 확인해야 한다.

### 통합 검증의 범위

정상 대화·캐시 복원·사용자 분리·로그아웃·원본 재접속을 순차 실행한다. 버전 키는 추가 전용 원본에서 쓰며 UPDATE/DELETE/DB 파일 교체를 감지하지 않는다. 동시 채팅에서 여러 요청이 같은 문맥으로 응답하는 문제나 중복 요청 방지는 구현하지 않는다. 프로그램이 시작할 때마다 별도 sqlite·Redis 연결을 만들고 끝나면 닫는다. 모든 SQL·함수는 main.py 하나에 있으며 다른 교시 파일을 가져오지 않는다.

### sqlite 원본 조회와 JSON 변환을 읽는 방법

`messages`의 id는 저장 순서를 정하는 정수, owner는 가상 사용자 ID, role은 user/assistant, content는 메시지다. PRIMARY KEY는 행 식별자이고 AUTOINCREMENT는 자동 번호가 과거에 사용한 번호를 재사용하지 않도록 한다. role의 CHECK는 두 역할 외 값의 저장을 막는다. 이 예제는 원본 메시지를 추가만 하고 수정·삭제하지 않는다.

`WHERE owner = ?`와 `(owner, MAX_MESSAGES)` 같은 매개변수 바인딩은 값을 SQL 문법과 분리한다. 물음표에 문자열을 직접 이어 붙이지 않는다. `ORDER BY id DESC LIMIT ?`로 최신 여섯 개를 고른 뒤 reversed로 과거→현재 순서로 바꾼다. 원본의 나머지 행을 삭제하는 코드는 아니다. `fetchall()`은 조회 결과 전체를 튜플 목록으로 가져오고, 역할·내용을 사전으로 만든다.

`with conn:`은 정상 쓰기를 COMMIT하고 예외 시 ROLLBACK하는 범위다. 연결 자체를 닫지는 않는다. `closing(sqlite3.connect(...))`이 블록 종료 시 연결을 닫는다. connect의 첫 인자는 파일 경로, timeout=5는 다른 쓰기의 잠금이 풀리기를 기다리는 초이며 기본값도 5다. 정상적인 로컬 파일 경로와 순차 명령 실행을 사용한다. sqlite3는 Python 내장 모듈이라 별도 pip 설치가 없다.

`json.dumps(messages, ensure_ascii=False)`는 메시지 목록을 한 JSON 문자열로 만든다. False는 기본 True와 달리 한글을 문자로 유지한다. `json.loads(raw)`는 이를 Python 목록으로 복원한다. 캐시에는 최근 메시지 목록 전체를 String 하나로 저장한다. 4교시의 List는 메시지 추가를 연습하기 위한 것이었고, 이번에는 원본에서 읽은 조회 결과를 통째로 바꿔 넣는 사본이므로 String을 선택한다. 응답 결과를 재사용하는 LLM 응답 캐시와는 다른 **대화 이력 캐시**다.

### 명령줄 입력과 연결 옵션

add_argument는 입력 규칙을 등록하고 parse_args가 실제 명령줄을 해석해 args 필드를 만든다. 명령 이름을 등록하는 순간 저장·조회가 실행되는 것은 아니다.

| 실제 입력 | args와 실행 흐름 | 결과 |
|---|---|---|
| python main.py chat sid_DEMO "내 이름은 은우" | command=chat, value=sid_DEMO, text=내 이름은 은우 → require_session → load_history → make_demo_reply → save_turn → invalidate | 문맥 사용·원본 저장·옛 캐시 정리 |
| python main.py history sid_DEMO | command=history, value=sid_DEMO, text="" → require_session → load_history → show_history | 해당 사용자 이력 |

sid_DEMO는 설명용 합성값이다. 실제 실행에는 create가 출력한 전체 세션 ID를 넣어야 하며 demo-a 문자열이나 합성값을 세션 ID로 사용하면 거절된다.

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

현재 차시를 `C:\AI4\redis_course\lesson08`에 둔다. 실제 위치가 다르면 cd 경로만 바꾼다. 모든 실행 명령은 Windows CMD 기준이며 Redis 컨테이너는 하나만 사용한다. Docker Desktop을 켜고 Linux 컨테이너 모드로 준비한다. 최초 설치는 [Docker 공식 Windows 안내](https://docs.docker.com/desktop/setup/install/windows-install/)를 따른다.

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
cd /d C:\AI4\redis_course\lesson08
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
SQLITE_PATH=chat08.db
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
| lesson08.md | 설명·전체 코드·실행·예상 결과·프롬프트 |
| main.py | 실행 로직과 SQL을 모두 포함 |
| .env.example | 가짜 로컬 설정 예시 |
| .gitignore | .env·가상환경·캐시·DB 파일을 Git에서 제외 |
| lesson_scope.json | 내부 품질 검증 메타데이터. 실행 파일·접속 설정이 아님 |

실행하면 생기는 chat08.db는 원본 데이터 파일이며 배포 ZIP에는 포함하지 않는다. .gitignore 내용은 다음과 같다. 이미 추적 중인 파일을 자동 해제하는 기능은 아니다.

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
    return f"lesson08:history:{owner}:v{version}"

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
    client.set(f"lesson08:session:{session_id}", owner, ex=SESSION_TTL)
    print("SESSION_ID:", session_id)  # 가상 로컬 실습에서 다음 명령에 전달하기 위한 출력
    print("세션 사용자:", DEMO_USERS[owner])


def require_session(client, session_id):
    try:
        owner = client.get(f"lesson08:session:{session_id}")
    except redis.exceptions.RedisError:
        # 세션을 확인할 수 없는데 캐시 조회처럼 성공으로 대체해서는 안 된다.
        raise PermissionError("세션 확인 불가: Redis 장애이므로 접근을 거절합니다.") from None
    if owner not in DEMO_USERS:
        raise PermissionError("세션이 없거나 만료되어 접근을 거절합니다.")
    return owner

def make_demo_reply(messages, text):
    # 실제 LLM이 아닌 모의 함수다. 원본에서 복원한 문맥도 전달되는지 확인한다.
    if text == "내 이름이 뭐야?":
        for message in reversed(messages):
            if message["role"] == "user" and message["content"].startswith("내 이름은 "):
                return "기록에서 찾은 이름: " + message["content"].removeprefix("내 이름은 ")
        return "최근 이력에서 이름을 찾지 못했습니다."
    return f"모의 응답: {text}"

def main():
    parser = argparse.ArgumentParser(description="세션·원본·캐시·모의 응답 통합 대화")
    parser.add_argument("command", choices=['init', 'create', 'chat', 'history', 'evict', 'logout'], help="실행할 동작")
    # init에는 value가 없으므로 ?로 생략을 허용한다. 명령별 필수 여부는 아래에서 검사한다.
    parser.add_argument("value", nargs="?", default="", help="가상 사용자 또는 세션 ID")
    parser.add_argument("text", nargs="?", default="", help="chat에서만 사용하는 메시지")
    args = parser.parse_args()
    if args.command == "init":
        if args.value or args.text:
            raise ValueError("init에는 추가 인자를 넣지 마세요.")
    elif not args.value.strip():
        raise ValueError("이 명령에는 사용자 또는 세션 ID가 필요합니다.")
    if args.command == "chat" and not args.text.strip():
        raise ValueError("메시지는 공백이 아닌 문자열이어야 합니다.")
    if args.command != "chat" and args.text:
        raise ValueError("메시지는 chat 명령에서만 사용하세요.")
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
            owner = require_session(client, args.value)  # Redis 장애 시 여기서 거절한다.
            if args.command == "logout":
                print("삭제한 세션 수:", client.delete(f"lesson08:session:{args.value}"))
                return  # sqlite 원본과 사용자 대화 캐시는 유지한다.
            if args.command == "evict":
                print("삭제한 캐시 수:", client.delete(cache_key(conn, owner)))
                return
            messages, source = load_history(conn, client, owner)
            if args.command == "history":
                show_history(messages, source)
                return
            # chat: 인증된 사용자의 이전 이력과 새 입력으로 응답을 만든다.
            reply = make_demo_reply(messages, args.text)
            old_key = cache_key(conn, owner)
            save_turn(conn, owner, args.text, reply)
            invalidate(client, old_key)
            print("문맥 조회 경로:", source)
            print("이전 메시지 수:", len(messages))
            print("모의 응답 결과:", reply)



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

### 4) 세션 생성과 변수 설정

```bat
python main.py init
python main.py create demo-a
set CHAT_8A=방금_발급된_A의_SESSION_ID_전체
python main.py create demo-b
set CHAT_8B=방금_발급된_B의_SESSION_ID_전체
```

init은 원본 준비, create는 가상 사용자에 대한 세션 발급이다. set 오른쪽 자리표시자를 실제 발급값으로 바꾼다. set은 현재 CMD 변수에 저장하고 %변수명%은 그 문자열로 치환한다. 등호 양옆 공백은 넣지 않는다. 예를 들어 실제 출력값이 sid_abc라면 `set CHAT_8A=sid_abc`처럼 쓴다. 새 CMD에는 변수가 자동 전달되지 않는다.

### 5) 문맥을 쓰는 대화

```bat
python main.py chat %CHAT_8A% "내 이름은 은우"
python main.py chat %CHAT_8A% "내 이름이 뭐야?"
python main.py history %CHAT_8A%
```

| 부분 | 의미 |
|---|---|
| chat | main.py의 대화 처리 명령. Python 기본 명령이 아님 |
| %CHAT_8A% | 세션 ID이며 demo-a 문자열을 직접 넣는 자리가 아님 |
| 큰따옴표 메시지 | 공백을 포함한 하나의 text 인자 |
| history | 유효한 세션 사용자의 최근 이력 조회 |

첫 chat은 모의 응답으로 선언을 저장한다. 두 번째 chat은 `모의 응답 결과: 기록에서 찾은 이름: 은우`가 정상이다. 실제 계정 demo-a의 표시 이름은 민수지만 응답은 이전 user 메시지의 은우를 찾아야 한다. 각 chat은 원본에 두 메시지를 COMMIT하고 이전 캐시를 무효화한다. 따라서 직전 chat 뒤 첫 history는 현재 버전의 MISS, 곧바로 반복 history는 HIT가 일반적이다.

### 6) 캐시만 지운 뒤 이름 다시 찾기

```bat
python main.py evict %CHAT_8A%
python main.py chat %CHAT_8A% "내 이름이 뭐야?"
```

evict는 세션을 먼저 검증하고 해당 사용자의 현재 캐시 키만 지운다. 삭제 수는 존재 여부에 따라 0 또는 1이다. 다음 chat은 `문맥 조회 경로: MISS`이며 원본에서 복원한 이름 은우를 답해야 한다. 초기 가상 데이터 그대로 위 순서를 실행했다면 최근 여섯 메시지 안에 은우 선언이 있어야 한다. 다른 대화를 많이 했다면 다시 이름을 선언한 뒤 검사한다.

### 7) 사용자 분리와 로그아웃 후 원본 유지

```bat
python main.py chat %CHAT_8B% "내 이름이 뭐야?"
python main.py history %CHAT_8B%
python main.py logout %CHAT_8A%
python main.py history %CHAT_8A%
```

B는 초기 원본의 지연을 답해야 하며 A의 은우 선언이 섞이면 안 된다. logout은 A 세션만 지워 삭제 수 1이 정상이다. A의 다음 history는 접근 거절과 종료 코드 1이다. sqlite 대화는 삭제하지 않았으므로 새 A 세션으로 다시 읽을 수 있다.

```bat
python main.py create demo-a
set CHAT_8A=새로_발급된_A의_SESSION_ID_전체
python main.py history %CHAT_8A%
```

새 세션의 history에 앞서 남긴 A 이력이 보여야 한다. 이름 선언이 조회 범위 밖이더라도 최근 대화 자체는 원본에 저장되어 있어야 한다. init을 다시 실행해도 기존 기록을 초기 샘플로 덮어쓰지 않는다.

### 8) 서버 중단 시 접근 거절과 복원

```bat
docker stop kdt-redis
python main.py chat %CHAT_8A% "이 입력은 저장되면 안 됩니다"
echo %ERRORLEVEL%
docker start kdt-redis
docker exec kdt-redis redis-cli PING
python main.py create demo-a
set CHAT_8A=복구_후_새로_발급된_SESSION_ID_전체
python main.py history %CHAT_8A%
```

stop은 컨테이너 중지, start는 기존 컨테이너 시작, PING의 PONG은 Redis 응답 복구 기준이다. 중단 중 chat은 세션 확인 단계에서 거절되어 원본에 새 입력이 저장되지 않아야 한다. 원본 저장 후 캐시 오류가 난 경우와 구분한다. 복구 후 이전 세션은 사라져 새로 발급한다. history는 Redis 캐시가 없어도 sqlite 원본에서 복원되며, 중단 중 거절된 문장은 없어야 한다.

이력 캐시 손상만 확인하려면 정상 history로 캐시를 만든 뒤 아래 조회에서 현재 버전 키를 찾아 해당 캐시만 broken 문자열로 덮어쓴다. 세션 키를 손상시키면 접근 거절 검사로 바뀐다.

```bat
docker exec kdt-redis redis-cli --scan --pattern "lesson08:history:demo-a:*"
docker exec kdt-redis redis-cli SET 실제_현재_캐시_키 broken EX 60
python main.py history %CHAT_8A%
```

--scan은 키 순회, --pattern은 이름 패턴이다. 결과는 변경되는 ID·버전에 따라 달라진다. SET은 지정 캐시만 변경하고 EX 60은 60초 만료다. 유효한 세션을 확인한 뒤 캐시 형식 오류가 원본 복원으로 처리되어야 한다.

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

실제 Redis·sqlite·모의 응답 함수로 이름 선언→문맥 응답, evict 뒤 원본에서 이름 복원, B 사용자 분리, 로그아웃 거절, 같은 사용자의 새 세션에서 원본 유지까지 검사했다. Redis 중단 시 chat이 세션 검증에서 거절되고 원본 행이 늘지 않는지, 재시작 뒤 새 세션으로 원본을 읽는지 확인했다. EXPIRE 1의 가속 세션 만료도 검사했다. 세션 GET은 성공하고 캐시 GET만 실패하는 상황, SET/DEL 단독 실패와 원본 오류·트랜잭션 ROLLBACK은 별도 오류 주입으로 확인했다. 세션 300초 전체 대기나 실제 LLM 호출 검사는 하지 않았다.

공통 검증 환경은 Python 3.12.14, redis-py 8.1.0, python-dotenv 1.2.4, SQLite 3.53.1, 실제 Redis 6.2.14의 로컬 TCP 연결이다. 배포 코드와 같은 main.py를 임시 차시 폴더로 복사하고 python main.py 명령으로 실행했다. 원본 없는 상태, init 반복, 허용되지 않은 명령·인자, 필수 설정 누락·공백·잘못된 포트, .env 없이 환경변수만 제공, 환경변수 우선순위와 합성 특수문자 경로 보존을 확인했다. 실제 .env·DB·세션 값은 배포하지 않는다.

Windows CMD·Docker Desktop·redis:7.4 이미지의 설치·실행과 Python 3.13 환경은 이 검증 환경에서 실행하지 않았다. Docker 명령은 공식 문서와 대조했으며 위 PING과 현재 차시 실행 명령으로 현장에서 확인한다. 코드 실행 검증 서버 버전은 설치 안내의 Redis 7.4와 다르다. 실제 LLM API·동시 요청·분산 트랜잭션·중복 요청의 정확히 한 번 처리는 검증 범위가 아니다. 스킬의 파일 범위 정적 검사와 문서/코드 일치 및 ZIP 검사를 통과했다.

## 4. Vibe 코딩에 유용한 프롬프트

### 통합 대화의 완료 조건 확인

```text
lesson08/main.py와 lesson08.md를 읽고 합성 A/B 세션으로 통합 검증해줘.
A가 '내 이름은 은우'라고 말한 뒤 이름 질문에 은우를 찾고,
evict 뒤에도 sqlite에서 복원한 이력으로 같은 답이 나오는지 확인해줘.
B는 B 원본의 지연을 찾고 A의 은우 이력이 섞이지 않아야 해.
로그아웃 후 기존 ID는 거절되고 같은 사용자의 새 세션에서는 원본 대화가 유지되어야 해.
Redis가 처음부터 중단된 chat은 세션 검증에서 거절되어 원본 행 수가 늘면 안 돼.
최근 6개 메시지 밖 정보는 복원할 수 있다고 과장하지 마.
실제 LLM 호출이 아닌 모의 함수이며 동시성·중복 요청은 미구현임을 밝혀줘.
코드 변경·추가 패키지 없이 검사하고 .env·접속값·세션 ID·개인 대화는 출력·전송하지 마.
수행한 검증과 실행하지 못한 환경을 구분해줘.
```