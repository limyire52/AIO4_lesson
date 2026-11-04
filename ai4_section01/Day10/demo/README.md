# community-demo

Python · FastAPI · Uvicorn · SQLite3 기반 소규모 학습·시연용 게시판입니다. **문서 확인일: 2026-10-27**, 로컬 검증 환경은 Windows / Python 3.12.14입니다. 요구사항은 [prompt.md](prompt.md), 확정 구현 계획은 [plan.md](plan.md), 검증 결과는 [docs/verification.md](docs/verification.md)를 참고하세요.

## 구현 기능

- 회원가입·로그인·로그아웃, Argon2id 해시, 서버 세션, CSRF 및 반복 요청 제한
- 로그인 후 환영 안내, 제목만 표시하는 목록·10개 페이징·제목/내용 검색
- 현재 body의 숨김 영역을 사용하는 글 상세·작성·수정·삭제, 글 변경 시 비밀번호 재확인
- 댓글 작성·본인 수정·삭제, 불쾌한 표현 마스킹과 신고
- 관리자 표현 규칙 추가/삭제, 신고 상태·처리 메모 관리
- SQLite 마이그레이션·관리자 생성·초기 규칙 등록·정리·백업·복원 명령

비밀번호 찾기는 화면 목업이며 실제 메일을 발송하지 않습니다. SNS 로그인·실제 비밀번호 재설정·첨부파일·좋아요·대댓글·제재·자동 통보는 포함하지 않습니다.

## 1. 로컬 실행 — Windows CMD(명령 프롬프트)

[Python](https://www.python.org/downloads/) 3.12를 설치하고 프로젝트 폴더에서 실행합니다. 기존 Python이 있다면 `py --list`로 확인하세요. 가상환경을 활성화할 필요 없이 아래처럼 실행할 수 있습니다.

먼저 CMD에서 프로젝트 폴더로 이동합니다. `cd /d`는 드라이브가 달라도 이동합니다.

```bat
cd /d "C:\강사님_Git\ai4_section01\Day10\demo"
```

프로젝트를 다른 위치에 저장했다면 위 경로를 변경하세요. 다음 명령은 같은 CMD에서 한 줄씩 실행합니다.

```bat
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m app.cli migrate
.\.venv\Scripts\python -m app.cli create-admin
.\.venv\Scripts\python -m app.cli seed-filters
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

브라우저에서 [로컬 게시판](http://127.0.0.1:8000)을 엽니다. 관리자 생성 명령은 이메일·닉네임·비밀번호를 직접 입력받습니다. 일반 회원은 화면에서 가입하세요. 비밀번호는 8~128자입니다. `seed-filters`는 관리자가 먼저 있어야 하며 반복 실행해도 동일 규칙을 중복 생성하지 않습니다.

Python 명령이 없다면 Python 설치 후 새 터미널을 여세요. 이미 생성된 가상환경에서 `No module named ...` 오류가 나면 해당 환경의 Python으로 설치했는지 확인합니다. 종료는 서버 터미널에서 `Ctrl+C`입니다.

### CMD에서 WinError 10013이 발생하는 경우

서버 실행 시 발생했다면 포트 접근이 거부된 상태일 수 있습니다. 기존 서버가 실행 중이면 해당 터미널에서 `Ctrl+C`로 종료하고, 우선 다른 포트에서 자동 재시작 옵션 없이 실행하세요.

```bat
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

이 경우 접속 주소는 [http://127.0.0.1:8001](http://127.0.0.1:8001)입니다. 실행되면 같은 명령 끝에 `--reload`를 추가하여 개발할 수 있습니다.

같은 오류가 계속되면 CMD에서 다음 결과와 실제 실행 명령·전체 오류 로그를 확인하세요. `netstat`의 로컬 주소 열에서 해당 포트를 확인합니다. 다른 프로그램을 임의로 종료하거나 Windows 예약 포트를 삭제하지 않습니다.

```bat
netstat -ano -p tcp | findstr :8001
netsh interface ipv4 show excludedportrange protocol=tcp
```

10013만으로 포트 충돌·예약·보안 정책 중 어느 원인인지 확정할 수 없습니다. 패키지 설치 중 발생했다면 서버 포트 문제가 아닌 외부 연결 문제이므로 설치 명령과 오류 전체를 확인해야 합니다. [Microsoft 소켓 오류 설명](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2)

Linux/macOS 로컬에서는 `python3 -m venv .venv` 후 위 명령의 `.\.venv\Scripts\python`을 `.venv/bin/python`으로 바꿉니다. **Windows의 .venv를 Linux 호스트에 업로드하지 않습니다.**

기본 DB는 `data/community.sqlite3`입니다. 최초 마이그레이션은 DB 파일을 생성하고 재실행은 기존 데이터를 유지합니다. 앱이 자동으로 관리자 계정이나 초기 규칙을 만들지는 않습니다. 함께 남아 있는 로컬 시연 DB가 있더라도 배포에는 사용하지 말고 새 DB·새 관리자를 생성하세요.

## 2. 설정

`.env.example`은 설정 참고용이며 자동 로드하지 않습니다. 실행 프로세스의 환경변수를 사용합니다.

| 설정 | 기본값 | 설명 |
|---|---|---|
| DATABASE_PATH | 프로젝트/data/community.sqlite3 | 배포에서는 공개 경로 밖의 영구 절대경로 |
| COOKIE_SECURE | 0 | 로컬 HTTP만 0, 운영 HTTPS는 1 |
| SESSION_SECONDS | 7200 | 세션 절대 만료 시간(초), 새로고침 유지 |
| PUBLIC_ORIGIN | 요청의 기본 출처 | 운영은 정확한 HTTPS 출처, 끝 경로 없이 설정 |
| LIMIT_LOGIN_ACCOUNT / LIMIT_LOGIN_IP | 5 / 30 | 15분당 로그인 검증 예산 |
| LIMIT_RECHECK_ACCOUNT / LIMIT_RECHECK_IP | 5 / 30 | 15분당 글 변경 비밀번호 검증 예산 |
| LIMIT_POST / LIMIT_COMMENT / LIMIT_REPORT | 5 / 10 / 5 | 사용자별 1분당 작성/접수 |
| LIMIT_SIGNUP_IP | 5 | IP별 1분당 가입 요청 |

비밀번호 검증은 동시 추측을 막기 위해 검증 전에 예산을 예약하고 성공 시 해당 예약을 반환합니다. 실패와 진행 중 검증이 제한에 포함되며 영구 계정 잠금은 없습니다. 생성 요청은 유효하지 않은 대상 등으로 실패해도 예산을 소비할 수 있습니다. 429 응답의 `Retry-After` 이후 다시 시도하세요.

로컬 CMD 설정 예시입니다. 프로젝트 폴더에서 서버를 실행하기 전에 입력하세요. `set` 설정은 현재 CMD와 여기서 실행한 프로그램에만 적용됩니다.

```bat
set "DATABASE_PATH=%CD%\data\community.sqlite3"
set "COOKIE_SECURE=0"
set "SESSION_SECONDS=7200"
```

환경변수 설정에는 CMD의 `set`을 사용합니다. `.env.example`을 복사하는 것만으로는 설정이 적용되지 않습니다.

## 3. 테스트

```bat
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -v
.\.venv\Scripts\python -m compileall -q app tests
```

테스트는 임시 DB와 가상 계정을 사용합니다. 실제 DB를 초기화하지 않습니다. 인증·권한·마스킹·검색·페이지·논리 삭제·신고·동시 요청 제한·마이그레이션·백업/복원을 검증합니다. 테스트에서 Starlette의 httpx 사용 중단 예정 경고가 표시될 수 있으나 고정된 현재 조합에서는 실행 가능합니다. `requirements-lock.txt`에는 로컬에서 검증한 전체 의존성(개발용 포함)을 기록했습니다. 운영은 `requirements.txt`만 설치합니다.

## 4. PythonAnywhere 무료 배포

### 배포 전에 확인할 점

FastAPI는 ASGI 앱입니다. **일반 WSGI 설정 파일에 직접 연결하지 말고 PythonAnywhere의 ASGI 베타 CLI 경로를 사용하세요.** 공식 문서는 ASGI 장기 가격이 미정이라고 명시합니다. 계정에서 무료 사용 가능 여부를 먼저 확인하고, 유료 업그레이드를 요구하면 중단하세요. [공식 ASGI 배포 안내](https://help.pythonanywhere.com/pages/ASGICommandLine/)

현재 무료 계정 안내는 웹 앱 1개·워커 1개·디스크 512 MiB·웹 앱 만료 1개월·CPU 제한입니다. 신규 계정에는 매일 예약 작업이 기본 제공된다고 가정하면 안 됩니다. 실제 할당량과 만료 연장 방법은 계정 화면을 확인하세요. [무료 계정 기능](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/)

SQLite는 사용할 수 있지만 호스트는 파일 시스템 성능 때문에 운영용 DB로 권장하지 않습니다. 본 프로젝트는 적은 접속자의 시연용입니다. [지원 DB 안내](https://help.pythonanywhere.com/pages/KindsOfDatabases)

### 4-1. 파일 업로드와 환경 준비

PythonAnywhere 계정에 프로젝트를 `/home/YOURUSERNAME/community-demo`로 업로드합니다. 필요한 것은 `app`, `static`, `migrations`, `data_seed`, `scripts`, `requirements.txt`와 문서입니다. `.venv`, `.uv-cache`, 로컬 DB, 백업, 비밀값은 업로드하지 않습니다. Files 화면에서 업로드하거나, Git 저장소가 있다면 Bash 콘솔에서 clone할 수 있습니다.

이 절의 `bash` 명령은 **로컬 CMD가 아닌 PythonAnywhere 웹사이트의 Bash 콘솔**에서 실행합니다. `YOURUSERNAME`을 본인 계정명으로 바꾸세요. Python 3.12가 계정 시스템 이미지에서 제공되는지 먼저 확인합니다. 제공되지 않으면 현재 설치 가능한 3.12 이상 버전과 의존성 호환성을 확인하고 테스트합니다.

```bash
python3.12 --version
cd /home/YOURUSERNAME/community-demo
python3.12 -m venv /home/YOURUSERNAME/.virtualenvs/community-demo
source /home/YOURUSERNAME/.virtualenvs/community-demo/bin/activate
python -m pip install -r requirements.txt
python -m pip install --upgrade pythonanywhere
```

Account의 API token 화면에서 토큰을 생성합니다. 공식 안내에 따르면 같은 계정의 Bash 콘솔에서 CLI가 사용할 수 있으며, 토큰을 프로젝트나 채팅에 복사할 필요가 없습니다. `pa website --help`로 CLI가 준비됐는지 확인하세요. 설치 실패 시 임의 패키지 버전 변경 대신 Python 버전·디스크 잔여량·설치 오류를 확인합니다.

### 4-2. 최소 ASGI 앱으로 무료 사용 가능 확인

첫 웹 앱을 생성하기 전에 기존 앱/도메인과 무료 할당량을 확인하세요. 다음 명령은 실제 테스트 사이트를 만듭니다. EU 계정은 도메인을 `YOURUSERNAME.eu.pythonanywhere.com`으로 바꿉니다.

```bash
pa website get
pa website create --domain YOURUSERNAME.pythonanywhere.com --command '/home/YOURUSERNAME/.virtualenvs/community-demo/bin/uvicorn --app-dir /home/YOURUSERNAME/community-demo --uds ${DOMAIN_SOCKET} scripts.smoke:app'
```

할당된 HTTPS 주소에서 `ASGI smoke test ok`가 표시되는지 확인합니다. 공식 ASGI는 관리 UI가 제한적이므로 일반 Web 화면에 나타나지 않을 수 있습니다. CLI `get`과 출력된 로그 경로를 기준으로 확인하세요.

무료 앱이 하나라면 smoke 앱과 실제 앱을 동시에 만들지 않습니다. CLI 도움말에서 시작 명령을 변경하는 기능을 지원하는지 먼저 확인하세요. 없다면 **이때 방금 만든 smoke 전용 앱인지 확인한 뒤에만** `pa website delete --domain YOURUSERNAME.pythonanywhere.com`으로 제거하고 다음 실제 앱을 생성합니다. 기존 서비스가 있는 도메인에는 이 삭제 명령을 실행하지 마세요. 플랫폼 사이트 설정 삭제와 SQLite 데이터 파일 삭제는 별개입니다.

### 4-3. 영구 DB 초기화와 실제 앱 생성

```bash
cd /home/YOURUSERNAME/community-demo
source /home/YOURUSERNAME/.virtualenvs/community-demo/bin/activate
mkdir -p /home/YOURUSERNAME/community-data
export DATABASE_PATH=/home/YOURUSERNAME/community-data/community.sqlite3
python -m app.cli migrate
python -m app.cli create-admin
python -m app.cli seed-filters
bash -n scripts/start-pythonanywhere.sh
```

`scripts/start-pythonanywhere.sh`의 프로젝트·가상환경·DB 경로를 본인 배치와 맞춥니다. 사용자명은 `id -un`으로 구합니다. EU 계정이면 `PUBLIC_ORIGIN`을 반드시 EU HTTPS 주소로 수정하세요. 콘솔에서 설정한 `export`만으로 웹 프로세스에 전달된다고 가정하지 않고 시작 스크립트가 운영 설정을 지정합니다.

```bash
pa website create --domain YOURUSERNAME.pythonanywhere.com --command 'bash /home/YOURUSERNAME/community-demo/scripts/start-pythonanywhere.sh'
pa website get --domain YOURUSERNAME.pythonanywhere.com
```

스크립트는 플랫폼이 제공하는 `${DOMAIN_SOCKET}`에 Uvicorn 워커 하나를 연결합니다. `--reload`, 별도 공개 포트, 계속 켜둔 콘솔, 자체 nginx는 필요하지 않습니다. 정적 파일은 앱이 제공하여 ASGI의 정적 매핑 제한을 피합니다. [ASGI 명령과 소켓 설명](https://help.pythonanywhere.com/pages/ASGICommandLine/)

### 4-4. HTTPS·프록시 및 배포 검증

- `/health`가 `{"status":"ok"}`인지 확인한 뒤 가입·로그인·글 작성·댓글·신고·관리자 처리를 확인합니다.
- `COOKIE_SECURE=1`과 정확한 `PUBLIC_ORIGIN`이 적용되어야 합니다. 로그인 후 재시작해도 데이터가 남는지 확인하세요.
- `TRUSTED_PROXY_IPS`는 호스트에서 확인한 신뢰할 프록시 주소/대역/소켓 리터럴만 지정하세요. 기본은 루프백입니다. 앱은 임의 `X-Forwarded-For`를 직접 신뢰하지 않습니다. `*`로 모든 헤더를 신뢰하도록 바꾸지 마세요. Uvicorn의 옵션 의미는 [공식 설정](https://uvicorn.dev/settings/)을 참고하세요.
- Unix 소켓 환경에서 신뢰할 전달 정보가 없으면 IP가 `unknown`으로 합쳐져 여러 방문자가 IP 제한을 공유할 수 있습니다. 계정 환경에서 클라이언트 주소 전달 방식을 확인해야 합니다. PUBLIC_ORIGIN은 프록시 scheme 추측과 별개로 CSRF 출처를 검사합니다.
- API 토큰·세션·비밀번호·관리자 메모가 응답이나 정적 파일에 노출되지 않는지 확인합니다. 계정에서 실제 테스트하기 전에는 배포 성공으로 간주하지 않습니다.

### 4-5. 재배포와 로그

코드를 업데이트하고 가상환경에서 의존성 설치, DB 백업, 마이그레이션을 수행한 뒤 재시작합니다. DB 파일을 새 코드로 덮어쓰지 않습니다.

```bash
cd /home/YOURUSERNAME/community-demo
source /home/YOURUSERNAME/.virtualenvs/community-demo/bin/activate
export DATABASE_PATH=/home/YOURUSERNAME/community-data/community.sqlite3
python -m app.cli backup --output /home/YOURUSERNAME/community-data/before-update.sqlite3
python -m pip install -r requirements.txt
python -m app.cli migrate
pa website reload --domain YOURUSERNAME.pythonanywhere.com
pa website get --domain YOURUSERNAME.pythonanywhere.com
```

백업 파일명은 매번 새 이름을 사용합니다. CLI `get`이 알려주는 `/var/log/...`의 오류·서버·접근 로그를 확인합니다. 403은 출처·CSRF, 429는 요청 제한, 503은 DB 경로·권한·잠금을 먼저 점검하세요. 외부 요청의 403은 무료 계정 allowlist 제한일 수도 있지만 앱 자체는 실행 중 외부 API를 호출하지 않습니다. [외부 접근 제한 안내](https://help.pythonanywhere.com/pages/403ForbiddenError)

## 5. 정리·백업·복원

예약 작업 없이 필요할 때 수동 실행합니다. **로컬 CMD**에서는 프로젝트 폴더에서 다음 명령을 사용합니다. 백업 파일명은 매번 새 이름으로 지정하세요.

```bat
.\.venv\Scripts\python -m app.cli cleanup
.\.venv\Scripts\python -m app.cli backup --output backups\community-20261027.sqlite3
.\.venv\Scripts\python -m app.cli restore --source backups\community-20261027.sqlite3 --output restored\community.sqlite3
```

**PythonAnywhere Bash 콘솔**에서는 가상환경을 활성화하고 운영 `DATABASE_PATH`를 설정한 뒤 다음 명령을 사용합니다.

```bash
python -m app.cli cleanup
python -m app.cli backup --output backups/community-20261027.sqlite3
python -m app.cli restore --source backups/community-20261027.sqlite3 --output restored/community.sqlite3
```

복원은 **새 파일에만** 수행합니다. 새 파일 무결성 확인 후 `DATABASE_PATH`를 복원 경로로 바꾸고 서버를 재시작하세요. 기존 DB에 덮어쓰지 않습니다. 운영은 시작 스크립트의 DB 경로도 바꿔야 합니다. DB·백업은 비공개로 보관하고 무료 디스크 한도에 맞춰 관리하세요. 게시글·댓글은 논리 삭제하며 신고는 보존합니다. 개발 데이터 초기화가 필요하면 새 DB 경로를 지정하고 마이그레이션하세요.

## 6. 구조와 구현 참고

```text
app/main.py          라우트·응답·정적 파일 허용목록
app/models.py        입력 스키마
app/services.py      계정·세션·게시글/댓글 접근·표시 서비스
app/security.py      해시·권한·CSRF·DB 요청 제한
app/filtering.py     Unicode 경계·정규식 timeout·마스킹
app/db.py            연결·트랜잭션·마이그레이션
app/cli.py           초기화·관리자·시드·정리·백업/복원
migrations/          테이블·제약·인덱스 SQL
static/              HTML·CSS·JavaScript
scripts/             배포 시작 스크립트·최소 ASGI 앱
tests/               임시 DB 기반 테스트
```

SQLite 연결마다 FK와 busy timeout을 설정하고, UUID/시각은 TEXT로 저장합니다. WAL을 강제하지 않습니다. 검색은 Python casefold 함수를 통한 소규모 부분 검색이며 대규모 전문 검색 엔진은 없습니다. 필터는 기존 글에도 즉시 적용하고 실행 제한 발생 시 원문 대신 제한 안내를 반환합니다. 초기 목록은 최소 2개이며 포괄적인 욕설 사전이 아닙니다. [출처와 오탐 기준](docs/filter-sources.md)을 참고하세요.

## 7. 확인 범위

로컬 자동 테스트·코드 문법 검사와 브라우저 주요 흐름을 검증했습니다. PythonAnywhere 계정 접속, 실제 ASGI 배포, Linux 의존성 설치 및 Unix 소켓 경로, 계정별 IP 전달, 무료 할당량은 이 환경에서 실증하지 않았습니다. 공식 자료를 확인한 배포 가이드와 실제 배포 완료는 구분합니다.

## 디자인 개선 및 버그 수정 (2026-10-27)

첨부 board.html의 카드·인디고 색상·여백·검색/페이지 구성을 참고해 기존 기능과 API를 유지하며 화면을 개선했습니다. 외부 폰트나 프런트엔드 패키지는 추가하지 않았습니다. 실제 건수와 페이지 번호를 표시하며 카테고리·조회수 등 예시 기능은 추가하지 않았습니다.

- 편집 화면 이탈 시 글 ID·비밀번호 필수 상태를 초기화합니다.
- 오래된 검색·신고 응답이 최신 화면을 덮어쓰지 않도록 검사합니다.
- 로그아웃/세션 만료 시 편집 원문·관리자 신고 내용과 메모를 화면에서 비웁니다.
- 실제 제출 버튼 비활성화와 처리 중 중복 제출 차단을 적용했습니다.
- 본문 내 편집 취소, 검색 결과 없음, 관리자 규칙 유형 선택과 모바일 배치를 보완했습니다.

CMD에서 기존 명령으로 서버를 실행하고 브라우저에서 **Ctrl+F5**로 새 화면을 불러오세요. DB 초기화나 재마이그레이션은 필요하지 않습니다.

Node.js가 설치되어 있으면 아래 프런트엔드 회귀 테스트도 실행할 수 있습니다. Node.js는 앱 실행·배포에는 필요하지 않습니다.

```bat
node --test tests\frontend.test.cjs
```

기존 API 테스트 18건과 프런트 회귀 테스트 5건 통과. 실제 브라우저에서 로그인·글 작성/수정/취소·댓글 수정·검색/초기화·관리자 탭과 390px 모바일 화면을 확인했습니다. [개선 화면](docs/screenshots/redesign-board.png), [모바일](docs/screenshots/redesign-mobile.png), [로그인](docs/screenshots/redesign-login.png).
