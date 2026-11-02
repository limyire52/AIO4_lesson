# 1차시 — SQLite DB 파일을 만들고 사용자 한 명 저장하기

**핵심 질문: 화면에서 조회한 사용자가 프로그램을 다시 실행하면 왜 사라질까?**

## 오늘 할 일

- Python으로 practice.db 파일을 열고 users 테이블을 만든다.
- 사용자 이름을 넣고 SQL로 조회한다.
- 같은 연결의 결과와 연결을 닫은 뒤 다시 조회한 결과를 비교한다.
- 저장을 확정하는 commit의 위치를 고쳐 사용자 데이터가 남도록 한다.

사용하는 Python 문법은 함수·import·리스트·튜플·try/finally다.
try/finally는 성공하거나 오류가 나도 연결 종료를 실행하기 위해 사용한다.
결과물은 수정한 main.py와 수정 전후 검사 출력, 저장이 누락된 이유 설명이다.

## 활동 순서

| 시간 | 활동 | 남길 기록 |
| --- | --- | --- |
| 0~5분 | 리스트와 DB 파일 차이·저장 결과 예상 | 예상 한 문장 |
| 5~15분 | 파일·표·행·열과 핵심 코드 읽기 | 실행 흐름 메모 |
| 15~28분 | DB 파일 생성·저장 누락 재현 | 연결 안/재연결 결과 |
| 28~40분 | Codex 분석·최소 수정 | 수정 한 줄·원인 |
| 40~47분 | 같은 검사로 재실행·비교 | 여섯 검사 결과 |
| 47~50분 | 질문·제출 | 최종 설명 |

Python 설치와 아래 실행 준비는 활동 전에 마친다.

## 실행 준비 — Windows CMD

Python 3.12 이상을 사용한다. 아래 명령은 압축을 C:\kdt\KDT_SQLITE에 풀었을 때다.
실제 압축 해제 위치에 맞게 경로를 바꾼다.

```bat
cd /d C:\kdt\KDT_SQLITE\lesson_01
py -3.12 -m venv .venv
.venv\Scripts\activate
python -c "import sqlite3; print('SQLite', sqlite3.sqlite_version)"
```

sqlite3는 표준 라이브러리이므로 pip install이 필요 없다.
계정·API 키·DB 서버·DB 관리 프로그램도 필요 없다.
PowerShell 활성화는 `.\.venv\Scripts\Activate.ps1`이다. 실행 정책으로 막히면 CMD를 사용한다.
macOS/Linux는 `python3 -m venv .venv`, `source .venv/bin/activate`로 준비한다.
`autocommit` 인자 오류가 나면 `python --version`을 확인하고 Python 3.12 이상으로 실행한다.

## 카페 명단과 DB 파일

카페의 사용자 명단을 생각해 보자. `users`는 명단 표, 행 하나는 사용자 한 명,
`id`와 `nickname`은 명단의 열이다. `practice.db`는 그 표를 담는 파일이다.
`commit()`은 지금까지 변경한 명단을 확정하는 단계이고 `close()`는 명단 작업을 끝내는 단계다.
명단을 화면에서 읽을 수 있다는 사실만으로 변경이 확정된 것은 아니다.

| SQL·Python 요소 | 하는 일 |
| --- | --- |
| sqlite3.connect | 파일을 열고 DB 연결 생성 |
| CREATE TABLE IF NOT EXISTS | users 표가 없으면 생성 |
| id INTEGER PRIMARY KEY | 행을 구분하는 번호. INSERT에서 생략하면 자동으로 번호 부여 |
| nickname TEXT NOT NULL | 이름을 문자열로 저장하고 NULL은 거절 |
| INSERT INTO | 새 사용자 행 추가 |
| ?와 (nickname,) | SQL 구문과 입력 값을 나누어 전달 |
| SELECT·fetchall | 사용자 행을 조회하고 튜플들의 리스트로 수집 |
| ORDER BY id | 번호 기준으로 결과 정렬 |
| commit | 현재 변경을 확정 |
| close | DB 연결 종료 |

사용자 이름은 중복될 수 있다. 다른 사람의 같은 이름을 구분하려면 id를 사용한다.
여기서 users는 실습용 사용자 명단이며 로그인 인증 기능을 수행하지 않는다.

## 시작 코드 전체 — main.py

```python
"""사용자를 저장하고 연결을 다시 열어 확인한다. 저장 누락 버그가 있다."""
import argparse
from pathlib import Path
import sqlite3


def save_user(db_path, nickname):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY, nickname TEXT NOT NULL)"
        )
        connection.commit()  # 테이블 준비를 확정한다.
        connection.execute(
            "INSERT INTO users (nickname) VALUES (?)", (nickname,)
        )
        rows = connection.execute(
            "SELECT id, nickname FROM users ORDER BY id"
        ).fetchall()
        # 사용자 저장을 확정하는 줄을 확인해 보세요.
        return rows
    finally:
        connection.close()


def read_users(db_path):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        return connection.execute(
            "SELECT id, nickname FROM users ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path(__file__).with_name("practice.db")))
    parser.add_argument("--name", default="민지")
    args = parser.parse_args()
    print("연결 안에서:", save_user(args.db, args.name))
    print("다시 연결하면:", read_users(args.db))
```

### 실행 흐름

1. 직접 실행하면 argparse가 --db와 --name을 읽는다.
2. save_user가 파일을 열고 표를 준비한다. 첫 commit은 이 준비를 마치는 시점이다.
3. INSERT에 이름을 전달하고 같은 연결로 SELECT한다.
4. return 뒤에도 finally의 close가 실행된다.
5. read_users가 같은 파일에 새로 연결해 SELECT한다.

`autocommit=False`는 변경을 자동 확정하지 않고 commit으로 확정하도록 명시하는 설정이다.
`Path(__file__).with_name("practice.db")`는 코드 파일 옆에 DB 경로를 정한다.
따라서 다른 폴더에서 실행하더라도 기본 DB 위치는 코드 옆으로 일정하다.
--db로 상대 경로를 주면 그 경로는 실행 터미널의 현재 폴더를 기준으로 해석된다.

## 예상 → 실행 → 관찰

```bat
python main.py
```

새 practice.db에서 기대하는 결과는 두 줄 모두 `[(1, '민지')]`다.
시작 코드의 실제 결과는 다음과 같다.

```text
연결 안에서: [(1, '민지')]
다시 연결하면: []
```

폴더에 practice.db가 생겼는지 확인하고 '파일 존재'와 '행 저장'을 구분한다.
이제 기존 DB에 영향을 주지 않는 검사도 실행한다.

```bat
python check.py main
```

시작 코드는 failures=2, 종료 코드 1이 의도한 결과다.
같은 연결에서 민지를 보는 검사는 PASS지만 재연결 저장 검사 두 개는 FAIL이다.

## 분석 → AI 수정 → 재실행 → 비교

CODEX_PROMPTS.md의 순서대로 main.py를 분석하고 한 줄만 수정한다.
함수 초반에 commit이 이미 있다는 이유만으로 사용자 저장이 확정됐다고 판단하지 않는다.
commit이 어느 INSERT보다 앞인지 뒤인지 실행 순서를 표시해 보자.

```bat
python check.py main
python check.py solution
```

수정 후 두 검사 모두 failures=0, 종료 코드 0이어야 한다.
CMD에서는 검사 직후 `echo %ERRORLEVEL%`, PowerShell에서는 `$LASTEXITCODE`로 확인한다.

```bat
python main.py
```

practice.db가 빈 상태였다면 수정 후 두 줄 모두 `[(1, '민지')]`가 된다.
다시 실행하면 INSERT가 한 번 더 실행되어 같은 이름의 행이 추가된다.
`CREATE TABLE IF NOT EXISTS`는 표의 재생성만 막고 INSERT의 중복 실행을 막지 않는다.
기존 실습 DB가 있으면 행 수와 id가 예시와 달라도 정상이다.
새 파일에서 비교하려면 `python main.py --db fresh_demo.db`처럼 아직 없는 이름을 지정한다.
임의로 기존 DB 파일을 삭제할 필요는 없다.

## 검사 코드 전체 — check.py

```python
"""임시 DB 파일을 사용해 실제 저장·재연결·잘못된 입력 거절을 확인한다."""
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module", choices=["main", "solution"])
    args = parser.parse_args()
    target = import_module(args.module)
    with TemporaryDirectory() as folder:
        db_path = Path(folder) / "check.db"
        inside = target.save_user(db_path, "민지")
        first_saved = target.read_users(db_path)
        literal_inside = target.save_user(db_path, "O'Neil")
        second_saved = target.read_users(db_path)
        rejected = False
        try:
            target.save_user(db_path, None)
        except sqlite3.IntegrityError:
            rejected = True
        after_error = target.read_users(db_path)
        checks = [
            ("visible_before_close", inside == [(1, "민지")]),
            ("saved_after_reconnect", first_saved == [(1, "민지")]),
            ("quote_in_name_preserved", any(row[1] == "O'Neil" for row in literal_inside)),
            ("both_rows_saved", second_saved == [(1, "민지"), (2, "O'Neil")]),
            ("null_rejected", rejected),
            ("existing_rows_preserved_on_error", after_error == second_saved),
        ]
        print("INSIDE:", inside)
        print("REOPENED:", first_saved)
        print("SECOND REOPENED:", second_saved)
        failures = 0
        for name, passed in checks:
            print(f"{'PASS' if passed else 'FAIL'} {name}")
            failures += int(not passed)
        print(f"RESULT failures={failures}")
        raise SystemExit(1 if failures else 0)
```

check.py는 main 또는 solution을 import하고 별도의 임시 폴더에 실제 DB 파일을 만든다.
한 함수 안의 조회 결과만 보지 않고 새 연결을 열어 사용자가 남아 있는지 확인한다.
`O'Neil`은 따옴표가 있는 값도 ? 자리표시자로 전달되는지 확인하는 입력이다.
`None`은 SQL NULL로 전달되어 NOT NULL에 거절되는 오류 입력이다.
임시 폴더는 검사 종료 시 정리되며 practice.db를 덮어쓰지 않는다.

## 파일 안내

| 파일 | 역할·사용 시점 |
| --- | --- |
| main.py | 저장 누락을 재현하고 수정. python main.py |
| solution.py | 최소 수정 비교본. python check.py solution |
| check.py | 임시 DB에서 정상·재연결·오류 보존 검사 |
| CODEX_PROMPTS.md | 구체적인 재현 조건의 분석·수정·검토 프롬프트 |
| ANSWERS.md | 실습 후 원인·한 줄 수정·확인 질문 답 비교 |
| SOURCES.md | Python sqlite3의 공식 동작 확인 |
| VERIFICATION.md | 실제 실행 결과와 실행 환경 확인 |
| lesson_scope.json | 배포 전 코드 범위 검증 자료. 실습 실행 파일이 아님 |

실행으로 생기는 practice.db는 사용자 데이터를 담는 파일이다. 예제 코드는 공유하고 개인 DB 파일은 공유에서 제외한다.
서버나 포트가 없으므로 서버 시작·재시작은 필요 없다. 코드 저장 후 Python 명령을 다시 실행한다.
끝나면 `deactivate`로 가상환경을 종료한다. 프로그램 종료와 DB 연결 종료는 DB 파일 삭제를 의미하지 않는다.

## 자주 막히는 지점

| 증상·생각 | 확인 |
| --- | --- |
| DB 파일이 있으니 저장됐다 | 새 연결로 행까지 조회 |
| SELECT에 나오니 저장됐다 | 같은 연결과 재연결 결과 비교 |
| close가 commit도 해준다 | 이 설정에서는 commit을 명시 |
| return 전에 close를 안 했다 | finally에서 항상 종료하는 흐름 확인 |
| INSERT SQL에 이름을 직접 붙인다 | ?와 값 튜플로 전달 |
| 실행할 때마다 민지가 늘어난다 | INSERT는 매번 행을 추가. 새 파일 또는 임시 검사로 비교 |
| database is locked | 다른 실행이나 DB 도구가 파일을 잡고 있는지 확인하고 종료 |
| unable to open database file | --db의 부모 폴더와 쓰기 권한 확인. 파일만 만들며 부모 폴더는 자동 생성하지 않음 |

## 이해도 확인·제출

1. sqlite3와 DB 파일은 각각 무엇인가?
2. Python 리스트와 practice.db는 실행 종료 후 어떻게 다른가?
3. users의 행·열은 무엇을 나타내는가?
4. connect·execute·fetchall은 각각 언제 실행되는가?
5. commit과 close는 어떻게 다른가?
6. 저장 검사는 왜 새 연결을 사용해야 하는가?
7. ? 자리표시자를 쓰는 이유는 무엇인가?
8. (nickname,)에 쉼표가 필요한 이유는 무엇인가?
9. None을 저장하면 왜 IntegrityError가 발생하는가?
10. 이름이 같은 두 사용자를 어떻게 구분하는가?

제출: 수정한 main.py, 수정 전후 검사 출력, 기존 commit과 추가한 commit의 차이 설명.
답과 평가 기준은 ANSWERS.md에서 확인한다.
다음에는 여러 사용자를 저장하고 WHERE·ORDER BY·LIMIT으로 필요한 행을 조회한다.
난이도·활동 분량·설명 깊이에 대한 피드백을 기록한다.
