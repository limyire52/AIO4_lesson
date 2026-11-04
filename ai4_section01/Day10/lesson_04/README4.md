# 4차시 — 자료형·기본키·필수값·중복·허용 범위로 데이터 규칙 정하기

**핵심 질문: 0~100점만 허용했는데 NULL 점수가 왜 저장될까?**

## 오늘 할 일

- PK로 행을 구분하고 UNIQUE로 이메일 중복을 막는다.
- NOT NULL과 CHECK가 맡는 역할을 구분한다.
- 정상값·경계값·누락값을 실제 DB 파일에서 비교한다.

사용하는 개념: CREATE TABLE·INSERT·? 값 전달·commit·rollback·IntegrityError.
결과물: 수정한 테이블 정의, 10개 검사 출력, NULL과 범위 조건의 차이 설명.

## 활동 순서

| 시간 | 활동 | 남길 기록 |
| --- | --- | --- |
| 0~5분 | 핵심 질문과 샘플 결과 예상 | 예상 상태 |
| 5~15분 | 표·SQL·함수 호출 읽기 | 규칙·호출 흐름 |
| 15~28분 | 정상·실패 실행 비교 | 실제 출력 |
| 28~40분 | Codex 분석 → 최소 수정 | 원인·변경 |
| 40~47분 | 동일 검사로 재실행 | 정상 보존·실패 처리 |
| 47~50분 | 확인 질문·제출 | 설명 |

환경 준비는 활동 전에 마친다. 선택 심화는 기본 실행에 추가하지 않는다.

## 실행 준비 — Windows CMD

Python 3.12 이상을 사용한다. 압축을 C:\kdt\KDT_SQLITE_FULL에 풀었다고 가정한다.
실제 압축 위치에 맞게 경로를 바꾼다.

```bat
cd /d C:\kdt\KDT_SQLITE_FULL\lesson_04
python --version
python -m venv .venv
.venv\Scripts\activate
python -c "import sqlite3; print('SQLite', sqlite3.sqlite_version)"
```

가상환경이 있으면 생성을 생략하고 활성화한다. 별도 pip 설치·서버·계정·키는 필요 없다.
PowerShell 활성화는 `.\.venv\Scripts\Activate.ps1`, macOS/Linux는 `source .venv/bin/activate`다.
수정한 파일을 저장하고 Python 명령을 다시 실행한다. 끝나면 `deactivate`를 실행한다.
각 실행·검사는 실제 임시 DB 파일을 사용하고 종료 때 정리한다. 앞 차시 DB 파일을 가져오지 않는다.

## 개념을 데이터와 연결하기

카페 회원 명단에서 회원 번호는 식별표, 이메일 중복 금지는 같은 연락처의 중복 등록 검사다. 점수 0~100 검사는 적립 범위이고, 점수 칸을 비워도 되는지는 별도의 약속이다. 범위 검사만으로 필수 칸이 되는 것은 아니다.

| 요소 | 역할 |
| --- | --- |
| INTEGER·TEXT | SQLite의 타입 선호도. 일반 테이블에서는 선언만으로 엄격한 타입 검사가 완성되지 않음 |
| INTEGER PRIMARY KEY | 행의 식별 번호. 이번 입력에서는 id를 명시하여 중복을 검사 |
| NOT NULL | 값 누락을 거절. Python None은 SQL NULL로 전달 |
| UNIQUE | 같은 이메일의 중복 행을 거절 |
| CHECK(points BETWEEN 0 AND 100) | 정해진 범위를 검사. NULL 처리와 필수 여부는 별도 |
| IntegrityError | 제약을 위반해 거절된 입력을 Python에서 확인 |

### 열의 데이터 규칙

| 열 | 규칙 | 확인 입력 |
| --- | --- | --- |
| id | INTEGER PRIMARY KEY | 기존 id=1 중복 거절 |
| nickname | TEXT NOT NULL | None 거절 |
| email | TEXT NOT NULL UNIQUE | None·기존 이메일 거절 |
| points | 범위 0~100·필수값 | 0·100 허용, -1·101·None 거절 |

`BETWEEN 0 AND 100`은 양 끝값을 포함한다. `None`과 0을 같은 누락값으로 다루지 않는다.
Python None은 SQL NULL로 전달된다. 0을 저장하는 것과 값을 주지 않는 것은 다르다.

## main.py 전체

```python
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


def create_database(db_path):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        connection.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, "
            "nickname TEXT NOT NULL, email TEXT NOT NULL UNIQUE, "
            "points INTEGER CHECK(points BETWEEN 0 AND 100))"
        )
        connection.commit()
    finally:
        connection.close()


def add_user(db_path, user_id, nickname, email, points):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        connection.execute(
            "INSERT INTO users (id, nickname, email, points) VALUES (?, ?, ?, ?)",
            (user_id, nickname, email, points),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise
    finally:
        connection.close()


def read_users(db_path):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        return connection.execute(
            "SELECT id, nickname, email, points FROM users ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


if __name__ == "__main__":
    with TemporaryDirectory() as folder:
        db_path = Path(folder) / "constraints.db"
        create_database(db_path)
        add_user(db_path, 1, "민지", "minji@example.test", 80)
        try:
            add_user(db_path, 2, "수아", "sua@example.test", None)
        except sqlite3.IntegrityError as exc:
            print("NULL 점수 거절:", exc)
        else:
            print("문제: NULL 점수가 저장되었습니다.")
        print(read_users(db_path))
```

| 함수·파일 | 필요한 이유·실제 사용 |
| --- | --- |
| create_database | 현재 차시의 users 표만 만들고 정의를 확정한다. |
| add_user | 값 네 개를 INSERT하고 정상 시 commit, SQL 오류 시 rollback 후 다시 전달한다. |
| read_users | 새 연결에서 저장된 전체 행을 확인한다. |
| check.py | 매 사례마다 새 DB와 민지 한 명을 준비하고 결과·제약 오류·기존 행 보존을 함께 검사한다. |

SCHEMA가 있는 차시는 실행할 SQL 전체를 선언한 문자열이다. 선언만으로 DB에 실행되지 않는다.
create_database에서 execute 또는 executescript가 호출될 때 표가 만들어진다.
각 함수는 필요한 연결을 열고 finally에서 닫는다. 저장은 commit으로 확정하고 실패 변경은 rollback한다.
`autocommit=False`를 쓰는 코드는 Python 3.12 이상에서 실행한다.
`?`에는 별도의 값 튜플을 전달한다. 값 문자열을 SQL에 이어 붙이지 않는다.

## 예상 → 실행 → 관찰

```bat
python main.py
python check.py main
```

**시작 코드 증상:** 민지 80점은 저장되지만 수아의 None도 저장되어 두 번째 행의 points가 NULL이다.

**기대 결과:** NULL 점수 입력은 IntegrityError로 거절되고 민지 한 행만 남아야 한다.

check.py의 시작 결과는 `RESULT failures=1`, 종료 코드 1이다.
성공하는 정상 사례도 함께 관찰한다. 문법 오류가 없거나 commit이 있다는 사실만으로 요구사항을 만족한다고 판단하지 않는다.

## 원인 분석 → AI 수정 → 재실행 → 비교

다음 순서로 입력·SQL·결과를 따라간다.

> create_database의 points 열 정의 → add_user의 None 값 전달 → CHECK 결과 → INSERT 허용 → 재연결 SELECT

CODEX_PROMPTS.md의 분석 → 최소 수정 → 검토를 사용한다.
다른 데이터나 검사 기대값을 바꾸지 않고 현재 원인만 수정한다.

```bat
python check.py main
python check.py solution
python solution.py
```

수정한 main과 비교본 solution은 **10개 검사 PASS·failures=0·종료 코드 0**이어야 한다.
CMD는 명령 직후 `echo %ERRORLEVEL%`, PowerShell은 `$LASTEXITCODE`로 종료 코드를 확인한다.
같은 입력을 다시 실행해 정상 동작과 실패 처리·기존 데이터 보존을 함께 확인한다.
최소 수정 위치와 질문 답은 직접 수정한 뒤 ANSWERS.md에서 비교한다.

## check.py 전체

```python
import argparse
from importlib import import_module
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module", choices=["main", "solution"])
    target = import_module(parser.parse_args().module)
    cases = [
        ("normal", (2, "수아", "sua@example.test", 50), False),
        ("zero", (2, "수아", "sua@example.test", 0), False),
        ("hundred", (2, "수아", "sua@example.test", 100), False),
        ("null_points", (2, "수아", "sua@example.test", None), True),
        ("negative", (2, "수아", "sua@example.test", -1), True),
        ("above_hundred", (2, "수아", "sua@example.test", 101), True),
        ("duplicate_id", (1, "수아", "sua@example.test", 50), True),
        ("duplicate_email", (2, "수아", "minji@example.test", 50), True),
        ("null_name", (2, None, "sua@example.test", 50), True),
        ("null_email", (2, "수아", None, 50), True),
    ]
    failures = 0
    with TemporaryDirectory() as folder:
        for index, (name, values, expected_rejection) in enumerate(cases):
            db_path = Path(folder) / f"case{index}.db"
            target.create_database(db_path)
            target.add_user(db_path, 1, "민지", "minji@example.test", 80)
            before = target.read_users(db_path)
            rejected = False
            try:
                target.add_user(db_path, *values)
            except sqlite3.IntegrityError:
                rejected = True
            after = target.read_users(db_path)
            expected = before if expected_rejection else before + [values]
            passed = rejected == expected_rejection and after == expected
            print(f"{'PASS' if passed else 'FAIL'} {name}: rejected={rejected}; rows={after}")
            failures += int(not passed)
    print(f"RESULT failures={failures}")
    raise SystemExit(1 if failures else 0)
```

검사는 main 또는 solution을 실제 import하고 함수를 호출한다.
TemporaryDirectory와 실제 .db 파일을 사용하므로 메모리 목록을 DB처럼 흉내 낸 검사가 아니다.
실패 시 거절 여부뿐 아니라 행 수·내용·참조 위반·기존 데이터 등 해당 검사의 계약을 확인한다.
표 이름을 문자열로 조합하는 검사에서는 코드에 고정된 표 이름만 사용한다. 사용자 입력을 식별자로 붙이는 방식이 아니다.

## 파일 안내

| 파일 | 역할 |
| --- | --- |
| README.md | 실행·개념·코드·관찰·제출 |
| main.py | 정상·오류 재현과 수정 |
| solution.py | 같은 목표의 최소 수정 비교본 |
| check.py | 실제 DB 파일에서 계약 검사 |
| CODEX_PROMPTS.md | 분석·수정·검토용 구체적 프롬프트 |
| ANSWERS.md | 원리·질문 답·평가 기준 |
| SOURCES.md | 공식 문서와 수업 정책 구분 |
| VERIFICATION.md | 실제 실행 출력·감사 결과·한계 |
| lesson_scope.json | 배포 전 범위 검증 자료. 실습 실행 파일 아님 |

## 오개념·막히는 지점

- 빈 문자열과 NULL은 다르다. NOT NULL이 빈 문자열이나 이메일 형식까지 검증하지는 않는다.
- 이 실습은 점수 범위·누락 검사를 다룬다. INTEGER 표기만으로 소수 입력이 모두 거절된다고 주장하지 않는다.

- 실행 후 DB 파일이 보이지 않는 것은 임시 폴더가 정리되었기 때문이다.
- autocommit 키워드 오류는 Python 버전을 확인한다. sqlite3가 없으면 사용하는 Python 배포판의 설치 상태를 확인한다.
- main.py와 solution.py를 동시에 수정하지 않는다. check.py의 기대값은 그대로 둔다.
- 전체 SQL 코드는 현재 파일의 표 정의를 기준으로 한다. 다른 차시 DB 스키마와 섞지 않는다.

## 확인 질문·제출

1. NOT NULL과 CHECK의 차이는?
2. NULL 점수에 CHECK만 있으면?
3. 0점은 누락값인가?
4. 같은 이메일은 어떻게 거절하는가?
5. INTEGER라고 쓰면 항상 정수만 저장되는가?
6. 오류 뒤 기존 데이터는?

제출: 수정 main.py, 수정 전후 검사 출력, 원인과 최소 수정의 관계 설명.
평가 기준과 비교 답은 ANSWERS.md에서 확인한다.

다음 학습: 사용자·대화방·메시지로 데이터를 나누고 1:N 관계를 설계한다.
진행 후 난이도·활동 분량·설명 깊이 피드백을 기록한다.