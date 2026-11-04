# 3차시 — 필요한 행만 수정·삭제하고 트랜잭션으로 묶기

**핵심 질문: 오류가 나서 rollback했는데 왜 점수 변경은 남아 있을까?**

## 오늘 할 일

- UPDATE·SET·WHERE로 한 사용자의 점수를 바꾼다.
- DELETE·WHERE로 특정 사용자를 제거한다.
- 영향 행 수 rowcount로 대상이 실제 있었는지 확인한다.
- 성공한 두 작업은 함께 확정하고 중간 실패는 함께 되돌린다.
- WHERE 누락의 전체 행 변경을 임시 DB에서 관찰하고 rollback한다.

앞에서 사용한 connect·execute·commit·SELECT·WHERE·? 값 전달·try/finally를 사용한다.
결과물은 수정한 main.py, 정상·실패의 새 연결 조회 결과와 commit 경계 설명이다.

## 활동 순서

| 시간 | 활동 | 기록 |
| --- | --- | --- |
| 0~5분 | 수정·삭제의 대상과 결과 예상 | 원본·기대 행 |
| 5~15분 | UPDATE·DELETE·rowcount·트랜잭션 읽기 | SQL과 역할 |
| 15~28분 | 정상 변경·WHERE 누락·중간 실패 재현 | 전후 행·행 수 |
| 28~40분 | Codex 분석 → 최소 수정 | 원인·삭제한 한 줄 |
| 40~47분 | 정상·실패 재검사·비교 | 여섯 검사 |
| 47~50분 | 확인 질문·제출 | 설명 |

## 실행 준비 — Windows CMD

Python 3.12 이상을 사용한다. 압축을 C:\kdt\KDT_SQLITE_03에 풀었다고 가정한다.
환경 준비는 활동 전에 마친다.

```bat
cd /d C:\kdt\KDT_SQLITE_03\lesson_03
python --version
python -m venv .venv
.venv\Scripts\activate
python -c "import sqlite3; print('SQLite', sqlite3.sqlite_version)"
```

이미 가상환경이 있으면 생성을 생략하고 활성화한다. 추가 패키지는 설치하지 않는다.
PowerShell은 `.\.venv\Scripts\Activate.ps1`, macOS/Linux는 `source .venv/bin/activate`를 사용한다.
서버·포트는 없고 수정 후 저장한 뒤 Python 명령만 재실행한다. 끝나면 `deactivate`를 실행한다.

각 명령은 임시 폴더에 별도 lesson03.db를 만들고 종료 시 정리한다.
같은 명령을 반복해도 항상 같은 원본으로 시작한다. 앞 차시 DB나 다른 파일을 지정하지 않는다.

## 카페 명단에서 두 작업을 한 묶음으로 보기

카페 명단에서 민지의 점수를 90으로 고치고 수아를 삭제한다고 하자.
여기서는 두 요청을 모두 성공했을 때만 반영하기로 정한다.
삭제할 사용자가 없으면 수정한 점수도 취소해야 한다. 이 성공·실패 묶음이 트랜잭션이다.
두 업무를 반드시 묶어야 한다는 것은 이 실습에서 정한 규칙이다.

| id | nickname | points |
| --- | --- | --- |
| 1 | 민지 | 80 |
| 2 | 준호 | 95 |
| 3 | 수아 | 70 |

정상 최종 상태는 민지 90·준호 95 두 행이다. 준호의 점수는 바뀌면 안 된다.
삭제 id가 999라면 원본 세 행과 민지 80점이 그대로 남아야 한다.

## 수정·삭제 SQL

```sql
UPDATE users SET points = ? WHERE id = ?
DELETE FROM users WHERE id = ?
```

| 부분 | 뜻 |
| --- | --- |
| UPDATE users | users 표의 기존 행 수정 |
| SET points = ? | 새 점수 지정 |
| WHERE id = ? | 수정·삭제할 사용자 제한 |
| DELETE FROM users | 조건에 맞는 행 제거 |
| cursor.rowcount | 실행 문장이 영향을 준 행 수 |
| commit | 현재 변경 확정 |
| rollback | 아직 확정하지 않은 변경 취소 |

수정에는 `(points, update_id)`, 삭제에는 `(delete_id,)`를 값으로 전달한다.
WHERE가 있다고 문장이 항상 한 행을 바꾸는 것은 아니다. id=999가 없으면 rowcount는 0이다.
그 자체는 SQL 오류가 아니므로 '정확히 한 명' 정책은 Python에서 검사한다.

## main.py 전체

```python
"""수정과 삭제를 한 묶음으로 처리한다. 중간 commit에 의도한 버그가 있다."""
import argparse
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


def prepare_database(db_path):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        connection.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, "
            "nickname TEXT NOT NULL, points INTEGER NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO users (id, nickname, points) VALUES (?, ?, ?)",
            [(1, "민지", 80), (2, "준호", 95), (3, "수아", 70)],
        )
        connection.commit()
    finally:
        connection.close()


def read_users(db_path):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        return connection.execute(
            "SELECT id, nickname, points FROM users ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


def apply_changes(db_path, update_id, points, delete_id):
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        updated = connection.execute(
            "UPDATE users SET points = ? WHERE id = ?", (points, update_id)
        )
        if updated.rowcount != 1:
            raise ValueError("수정 대상은 정확히 1명이어야 합니다.")
        connection.commit()  # 두 작업 사이의 확정 시점을 관찰한다.
        deleted = connection.execute(
            "DELETE FROM users WHERE id = ?", (delete_id,)
        )
        if deleted.rowcount != 1:
            raise ValueError("삭제 대상은 정확히 1명이어야 합니다.")
        connection.commit()
        return updated.rowcount, deleted.rowcount
    except (ValueError, sqlite3.Error):
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-id", type=int, default=1)
    parser.add_argument("--points", type=int, default=90)
    parser.add_argument("--delete-id", type=int, default=3)
    args = parser.parse_args()
    failed = False
    with TemporaryDirectory() as folder:
        db_path = Path(folder) / "lesson03.db"
        prepare_database(db_path)
        print("변경 전:", read_users(db_path))
        try:
            counts = apply_changes(db_path, args.update_id, args.points, args.delete_id)
            print("수정·삭제 행 수:", counts)
        except ValueError as exc:
            failed = True
            print("오류:", exc)
        print("재연결 결과:", read_users(db_path))
    raise SystemExit(1 if failed else 0)
```

### 함수·실행 흐름

1. CLI는 --update-id·--points·--delete-id를 정수로 읽는다.
2. TemporaryDirectory가 새 임시 폴더를 제공한다.
3. prepare_database가 users 표와 세 행을 만들고 commit한다. 원본 샘플 확정 단계다.
4. read_users가 새 연결로 변경 전 명단을 읽는다.
5. apply_changes가 UPDATE·행 수 검사·DELETE·행 수 검사를 수행한다.
6. 정상은 commit·(1, 1) 반환, 오류는 rollback·예외 재전달을 거친다.
7. main의 ValueError 출력 뒤에도 새 연결로 최종 상태를 읽는다.
8. finally에서 각 연결을 닫고, 실행이 끝나면 임시 폴더가 정리된다.

SQLite 오류는 함수에서 rollback 후 다시 전달한다. CLI는 업무상 ValueError만 설명 문구로 표시한다.
예상하지 못한 SQLite 오류는 traceback으로 나타난다. NULL 입력 거절은 check.py에서 직접 검증한다.

## 정상 실행

```bat
python main.py
```

```text
변경 전: [(1, '민지', 80), (2, '준호', 95), (3, '수아', 70)]
수정·삭제 행 수: (1, 1)
재연결 결과: [(1, '민지', 90), (2, '준호', 95)]
```

정상 실행만 보면 중간 commit의 문제를 알기 어렵다. 실패 사례를 함께 실행해야 한다.

## WHERE 누락 재현 — reproduce.py

```bat
python reproduce.py
```

```python
"""WHERE 없는 UPDATE·DELETE를 임시 DB에서 재현하고 항상 rollback한다."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from main import prepare_database, read_users


if __name__ == "__main__":
    with TemporaryDirectory() as folder:
        for index, sql in enumerate([
            "UPDATE users SET points = 0",
            "DELETE FROM users",
        ]):
            db_path = Path(folder) / f"missing_where_{index}.db"
            prepare_database(db_path)
            before = read_users(db_path)
            connection = sqlite3.connect(db_path, autocommit=False)
            try:
                cursor = connection.execute(sql)
                during = connection.execute(
                    "SELECT id, nickname, points FROM users ORDER BY id"
                ).fetchall()
                print("SQL:", sql)
                print("변경 전:", before)
                print("영향 행 수:", cursor.rowcount)
                print("확정 전:", during)
            finally:
                connection.rollback()
                connection.close()
            after = read_users(db_path)
            print("되돌린 뒤:", after)
            assert after == before
```

| 문장 | 영향 행 수 | 확정 전 | rollback 후 |
| --- | --- | --- | --- |
| UPDATE users SET points = 0 | 3 | 세 명 모두 0점 | 원래 세 명의 점수 |
| DELETE FROM users | 3 | 빈 명단 | 원본 세 행 |

각 문장은 별도 임시 DB에서 실행한다. finally의 rollback이 commit 전 변경을 취소한다.
WHERE 없는 예제는 실제 명단에 적용하는 명령이 아니라 전체 행 영향과 되돌리기를 관찰하는 재현 코드다.
reproduce.py는 main의 준비·조회 함수만 가져오며 apply_changes는 호출하지 않는다.

## 중간 실패 재현

```bat
python main.py --delete-id 999
python check.py main
```

기대는 오류와 함께 원본 세 행 유지다. 시작 코드의 실제 결과는 다음과 같다.

```text
오류: 삭제 대상은 정확히 1명이어야 합니다.
재연결 결과: [(1, '민지', 90), (2, '준호', 95), (3, '수아', 70)]
```

rollback을 호출했는데 민지의 90점이 남는다. UPDATE부터 예외까지 각 commit 위치에 선을 그어 보자.
check.py는 missing_delete_rolls_back_update만 FAIL, failures=1, 종료 코드 1이다.

## Codex 분석·최소 수정·재실행

CODEX_PROMPTS.md의 세 단계를 사용한다. 중간 commit 한 줄을 제거하고 최종 commit·rollback은 보존한다.
원래 점수로 되돌리는 UPDATE를 추가하거나 오류를 무시하는 방식으로 고치지 않는다.

```bat
python main.py
python main.py --delete-id 999
python check.py main
python check.py solution
```

수정 후 정상 명령은 기존 정상 결과를 유지한다.
삭제 id=999 명령은 오류를 출력하고 종료 코드 1이지만 원본 세 행과 민지 80점이 남는다.
두 check 명령은 여섯 검사 PASS·failures=0·종료 코드 0이어야 한다.
CMD는 검사 직후 `echo %ERRORLEVEL%`, PowerShell은 `$LASTEXITCODE`로 종료 코드를 확인한다.

**rollback은 이미 commit한 과거 변경까지 되돌리지 않는다.**
이 설정에서 commit·rollback 후 새 트랜잭션은 자동으로 열린다. BEGIN을 따로 추가하지 않는다.

## check.py 전체

```python
"""매 사례에 새 DB를 만들어 전체 성공·실패 뒤 데이터 상태를 검사한다."""
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
    original = [(1, "민지", 80), (2, "준호", 95), (3, "수아", 70)]
    cases = [
        ("normal_commit", 1, 90, 3, None, [(1, "민지", 90), (2, "준호", 95)]),
        ("missing_delete_rolls_back_update", 1, 90, 999, ValueError, original),
        ("missing_update_preserves_all", 999, 90, 3, ValueError, original),
        ("null_points_rejected", 1, None, 3, sqlite3.IntegrityError, original),
        ("zero_points_is_valid", 1, 0, 3, None, [(1, "민지", 0), (2, "준호", 95)]),
        ("different_delete_target", 1, 90, 2, None, [(1, "민지", 90), (3, "수아", 70)]),
    ]
    failures = 0
    with TemporaryDirectory() as folder:
        for index, (name, update_id, points, delete_id, expected_error, expected_rows) in enumerate(cases):
            db_path = Path(folder) / f"case_{index}.db"
            target.prepare_database(db_path)
            actual_error = None
            counts = None
            try:
                counts = target.apply_changes(db_path, update_id, points, delete_id)
            except (ValueError, sqlite3.Error) as exc:
                actual_error = type(exc)
            actual_rows = target.read_users(db_path)
            passed = actual_error is expected_error and actual_rows == expected_rows
            if expected_error is None:
                passed = passed and counts == (1, 1)
            print(f"{'PASS' if passed else 'FAIL'} {name}")
            print(f"  expected={expected_rows}")
            print(f"  actual={actual_rows}; error={actual_error}; counts={counts}")
            failures += int(not passed)
    print(f"RESULT failures={failures}")
    raise SystemExit(1 if failures else 0)
```

검사마다 새 파일을 준비해 이전 사례의 영향을 제거한다.
전체 성공의 반환 (1, 1)과 새 연결의 전체 명단을 비교한다.
없는 수정·삭제 대상, None의 NOT NULL 오류, 0점 입력과 다른 삭제 대상을 포함한다.
None은 SQL NULL로 전달되고 points INTEGER NOT NULL에 거절된다.
업무 오류와 SQL 오류에서 모두 기존 데이터가 유지되는지 확인한다.

## 파일 안내

| 파일 | 역할·호출 |
| --- | --- |
| main.py | 정상·실패 재현·트랜잭션 수정. python main.py |
| solution.py | 중간 commit을 제거한 비교본. python check.py solution |
| reproduce.py | WHERE 없는 수정·삭제와 rollback을 실제 실행 |
| check.py | 여섯 정상·실패 사례의 전체 상태 비교 |
| CODEX_PROMPTS.md | 분석·최소 수정·검토 활동 |
| ANSWERS.md | 원리·수정·확인 질문 답·평가 기준 |
| SOURCES.md | 공식 UPDATE·DELETE·트랜잭션 동작 |
| VERIFICATION.md | 실제 실행 출력·감사 결과·검증 한계 |
| lesson_scope.json | 배포 전 범위 검증 자료. 실습 실행 파일 아님 |

## 오개념·막히는 지점

| 상황 | 확인 |
| --- | --- |
| WHERE가 없으면 SQL 오류가 난다 | 오류 없이 전체 행이 대상이 됨 |
| 없는 id를 삭제하면 DB가 오류를 낸다 | 0행 적용. 이 수업은 rowcount로 ValueError 생성 |
| rollback을 넣었으니 모든 과거 변경이 복구된다 | 현재 미확정 변경만 취소 |
| finally close면 실패를 모두 처리한다 | 자원 종료와 업무 rollback 의도를 구분 |
| 실행 후 DB 파일이 안 보인다 | 임시 폴더가 종료 시 정리되는 구조 |
| 두 번째 실행 결과가 처음과 같다 | 매 실행 새 원본으로 시작 |
| autocommit 인자 오류 | python --version에서 3.12 이상 확인 |

## 확인 질문·제출

1. UPDATE와 DELETE는 각각 무엇을 바꾸는가?
2. WHERE를 빼면 어떤 행이 대상이 되는가?
3. rowcount는 무엇을 알려 주는가?
4. 없는 id의 DELETE가 왜 0행인가? 왜 별도 ValueError를 만드는가?
5. commit과 rollback은 무엇을 대상으로 하는가?
6. 중간 commit 이후 rollback이 점수를 돌려놓지 못한 이유는 무엇인가?
7. 샘플 준비 commit은 왜 유지하는가?
8. 왜 최종 상태를 새 연결로 읽는가?
9. 두 작업을 하나의 트랜잭션으로 묶는다는 뜻은 무엇인가?
10. 매번 같은 샘플로 실습할 수 있는 이유는 무엇인가?

제출: 수정 main.py, 정상·실패 전후 출력, WHERE 누락 재현 결과, commit 경계 설명.
답과 평가 기준은 ANSWERS.md에서 확인한다.
다음에는 자료형·기본키·필수값·중복·허용값 제약으로 데이터 규칙을 정한다.
진행 후 난이도·활동 분량·설명 깊이 피드백을 기록한다.