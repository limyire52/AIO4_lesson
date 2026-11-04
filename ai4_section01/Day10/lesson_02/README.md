# 2차시 — 여러 사용자를 조건·순서·개수에 맞게 조회하기

**핵심 질문: 조회 개수를 0으로 지정했는데 왜 사용자 두 명이 나올까?**

## 오늘 할 일

- 여러 사용자 데이터를 executemany로 저장한다.
- WHERE로 도시를 선택하고 ORDER BY로 점수·동점 순서를 정한다.
- LIMIT으로 결과 개수를 제한하고 0행도 올바른 결과로 다룬다.
- SQL에 전달되기 전에 입력값이 바뀌는 보조 함수 오류를 수정한다.

connect·execute·commit·close와 리스트·튜플·함수를 사용한다.
결과물은 수정한 main.py, 도시별 조회 결과와 0행 오류의 수정 전후 기록이다.

## 활동 순서

| 시간 | 활동 | 기록 |
| --- | --- | --- |
| 0~5분 | 서울 사용자 상위 2명 예상 | id 목록 |
| 5~15분 | 데이터·WHERE·ORDER BY·LIMIT 읽기 | 조건·정렬·상한 메모 |
| 15~28분 | 도시·개수를 바꾸어 조회하고 0행 오류 재현 | 명령·출력 |
| 28~40분 | Codex 분석·최소 수정 | 원인·변경 한 줄 |
| 40~47분 | 같은 검사와 CLI로 재실행 | 정상·경계·실패 결과 |
| 47~50분 | 확인 질문·제출 | 최종 설명 |

실행 환경 준비는 활동 전에 마친다. 선택 심화는 기본 실습에 추가하지 않는다.

## 실행 준비 — Windows CMD

Python 3.12 이상을 사용한다. 압축을 C:\kdt\KDT_SQLITE_02에 풀었다고 가정한다.

```bat
cd /d C:\kdt\KDT_SQLITE_02\lesson_02
python --version
python -m venv .venv
.venv\Scripts\activate
python -c "import sqlite3; print('SQLite', sqlite3.sqlite_version)"
```

이미 해당 폴더에 가상환경이 있으면 생성 명령은 생략하고 활성화한다.
추가 패키지 설치와 계정·키·서버 준비는 필요 없다.
PowerShell은 `.\.venv\Scripts\Activate.ps1`, macOS/Linux는 `source .venv/bin/activate`로 활성화한다.
서버·포트가 없으므로 수정 후에는 파일을 저장하고 Python 명령만 다시 실행한다.
끝나면 `deactivate`를 실행한다.

1차시 practice.db 대신 별도 lesson02.db를 사용한다. 이번 users는 city·points 열을 함께 사용한다.
1차시 코드나 DB 파일을 복사하지 않아도 실행할 수 있다.

## 카페 명단에서 상위 손님 고르기

서울 거주 손님 중 적립 점수가 높은 두 명에게 안내한다고 생각해 보자.
WHERE는 서울 명단을 고르는 조건, ORDER BY는 적립 점수 순서, LIMIT은 안내할 최대 인원이다.
점수가 같으면 id가 작은 사람을 먼저 선택한다. 동점 순서까지 정해야 실행 결과를 비교할 수 있다.

| id | nickname | city | points |
| --- | --- | --- | --- |
| 1 | 민지 | 서울 | 80 |
| 2 | 준호 | 부산 | 95 |
| 3 | 수아 | 서울 | 95 |
| 4 | 지훈 | 대전 | 70 |
| 5 | 하린 | 서울 | 95 |
| 6 | O'Neil | 서울 | 60 |

서울 명단의 정렬 결과는 id 3 → 5 → 1 → 6이다. 그중 2행은 id 3·5다.
부산의 준호는 점수가 높아도 서울 조회에는 나오면 안 된다.

## 핵심 SQL

```sql
SELECT id, nickname, city, points
FROM users
WHERE city = ?
ORDER BY points DESC, id ASC
LIMIT ?
```

| 구문 | 역할 |
| --- | --- |
| SELECT | 출력할 네 열을 명시 |
| FROM users | 조회할 표 지정 |
| WHERE city = ? | 값으로 받은 도시와 같은 행만 조회 |
| ORDER BY points DESC | 점수 높은 순 |
| id ASC | 같은 점수에서는 작은 id 순 |
| LIMIT ? | 값으로 받은 개수 이하의 행 반환 |

Python은 `(city, effective_limit)`의 값을 SQL의 ? 순서대로 전달한다.
문자열 이어붙이기로 WHERE 값을 만들지 않는다.
없는 도시에는 []가 반환된다. LIMIT은 결과를 채워 주는 개수가 아니라 최대 개수다.

## main.py 전체

```python
"""도시별 사용자를 점수순으로 조회한다. LIMIT 0을 잃는 버그가 있다."""
import argparse
from pathlib import Path
import sqlite3


def prepare_database(db_path):
    users = [
        (1, "민지", "서울", 80),
        (2, "준호", "부산", 95),
        (3, "수아", "서울", 95),
        (4, "지훈", "대전", 70),
        (5, "하린", "서울", 95),
        (6, "O'Neil", "서울", 60),
    ]
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY, nickname TEXT NOT NULL, "
            "city TEXT NOT NULL, points INTEGER NOT NULL)"
        )
        connection.executemany(
            "INSERT OR IGNORE INTO users (id, nickname, city, points) "
            "VALUES (?, ?, ?, ?)", users
        )
        connection.commit()
    finally:
        connection.close()


def normalize_limit(limit):
    if limit < 0:
        raise ValueError("limit은 0 이상이어야 합니다.")
    return limit or 2


def find_users(db_path, city, limit):
    effective_limit = normalize_limit(limit)
    connection = sqlite3.connect(db_path, autocommit=False)
    try:
        return connection.execute(
            "SELECT id, nickname, city, points FROM users "
            "WHERE city = ? "
            "ORDER BY points DESC, id ASC "
            "LIMIT ?", (city, effective_limit)
        ).fetchall()
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path(__file__).with_name("lesson02.db")))
    parser.add_argument("--city", default="서울")
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args()
    prepare_database(args.db)
    print(find_users(args.db, args.city, args.limit))
```

### 필요한 함수와 실제 호출

- prepare_database: 샘플 명단을 생성하고 commit으로 저장한다. 직접 실행 블록과 check.py가 호출한다.
- executemany: 네 자리표시자에 각 사용자 튜플을 반복 전달한다.
- INSERT OR IGNORE: 실습 DB에 같은 id가 있으면 그 삽입을 건너뛴다. 재실행으로 행 수가 늘지 않게 하는 준비 코드다.
  기존 데이터를 갱신하지 않는다. 샘플 내용을 바꿔 다시 준비하려면 새 DB 파일을 지정한다.
- normalize_limit: 음수를 거절하고 SQL에 전달할 개수를 결정한다. find_users가 실제 호출한다.
- find_users: 보조 함수 결과와 도시를 SQL에 전달하고 조회한 튜플 리스트를 반환한다.
- argparse: 명령행의 도시와 개수를 읽는다. --limit은 int로 바꾸고 생략 시 2를 넣는다.
- finally close: 조회 성공·오류 여부와 관계없이 연결을 닫는다.

기본 DB 경로는 코드 파일 옆 lesson02.db다. --db에 상대 경로를 지정하면 현재 터미널 폴더를 기준으로 해석한다.
--db 파일의 부모 폴더는 미리 있어야 한다. 사용 중인 개인 DB를 지정하지 말고 실습용 파일을 사용한다.

## 예상 → 실행 → 관찰

먼저 각 명령의 결과 id를 예상한다.

```bat
python main.py
python main.py --city 서울 --limit 1
python main.py --city 서울 --limit 10
python main.py --city 부산 --limit 2
python main.py --city 제주 --limit 2
```

| 입력 | 기대 id | 관찰할 내용 |
| --- | --- | --- |
| 기본값 서울·2 | [3, 5] | 동점 id 순서 |
| 서울·1 | [3] | 최대 1행 |
| 서울·10 | [3, 5, 1, 6] | 실제 일치 행은 4개 |
| 부산·2 | [2] | 도시 필터 적용 |
| 제주·2 | [] | 없는 도시도 정상 결과 |

기본 출력은 다음과 같다.

```text
[(3, '수아', '서울', 95), (5, '하린', '서울', 95)]
```

이제 경계값인 0을 넣는다.

```bat
python main.py --city 서울 --limit 0
```

기대는 []지만 시작 코드에서는 수아·하린 두 행이 나온다.
SQL을 먼저 고치지 말고 Python 입력에서 SQL 인자로 가는 경로를 추적한다.

```bat
python check.py main
```

시작 코드에서는 zero_means_zero만 FAIL, failures=1, 종료 코드 1이다.
음수는 이 함수의 입력 정책에 따라 거절한다.

```bat
python main.py --city 서울 --limit -1
```

ValueError와 'limit은 0 이상이어야 합니다.'가 나타나면 의도한 거절이다.
SQLite 자체는 음수 LIMIT을 상한 없는 조회로 해석하므로, 이 정책은 SQL 표준 동작이라고 설명하지 않는다.

## 원인 분석 → AI 수정 → 재실행 → 비교

CODEX_PROMPTS.md의 분석 → 최소 수정 → 검토를 사용한다.
--limit 0 → args.limit → find_users → normalize_limit → effective_limit → SQL의 ? 순서로 값을 적어 본다.
Python에서 `0 or 2`가 어떤 값을 내는지 확인한다.

수정 후 같은 명령으로 재확인한다.

```bat
python main.py --city 서울 --limit 0
python check.py main
python check.py solution
```

CLI는 []를 출력하고 두 검사는 10개 PASS, failures=0, 종료 코드 0이어야 한다.
CMD에서는 검사 직후 `echo %ERRORLEVEL%`, PowerShell에서는 `$LASTEXITCODE`를 확인한다.
비교본은 solution.py다. 먼저 직접 수정한 뒤 ANSWERS.md의 최소 수정과 대조한다.

## check.py 전체

```python
"""도시·정렬·상한·0·오류 입력을 실제 임시 DB 파일에서 비교한다."""
import argparse
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module", choices=["main", "solution"])
    args = parser.parse_args()
    target = import_module(args.module)
    cases = [
        ("seoul_two", "서울", 2, [3, 5]),
        ("seoul_one", "서울", 1, [3]),
        ("seoul_all", "서울", 10, [3, 5, 1, 6]),
        ("busan", "부산", 2, [2]),
        ("daejeon", "대전", 2, [4]),
        ("no_match", "제주", 2, []),
        ("sql_text_is_a_value", "서울' OR 1=1 --", 10, []),
        ("zero_means_zero", "서울", 0, []),
    ]
    failures = 0
    with TemporaryDirectory() as folder:
        db_path = Path(folder) / "check.db"
        target.prepare_database(db_path)
        for name, city, limit, expected in cases:
            rows = target.find_users(db_path, city, limit)
            actual = [row[0] for row in rows]
            passed = actual == expected and all(len(row) == 4 and row[2] == city for row in rows)
            print(f"{'PASS' if passed else 'FAIL'} {name}: expected={expected}, actual={actual}")
            failures += int(not passed)
        try:
            target.find_users(db_path, "서울", -1)
        except ValueError:
            print("PASS negative_limit_rejected")
        else:
            print("FAIL negative_limit_rejected")
            failures += 1
        before = target.find_users(db_path, "서울", 10)
        target.prepare_database(db_path)
        after = target.find_users(db_path, "서울", 10)
        passed = before == after and after[-1][1] == "O'Neil"
        print(f"{'PASS' if passed else 'FAIL'} repeat_prepare_preserves_rows_and_quote")
        failures += int(not passed)
    print(f"RESULT failures={failures}")
    raise SystemExit(1 if failures else 0)
```

check.py → 선택 모듈 prepare_database → find_users → normalize_limit → SQL 조회로 이어진다.
검사는 임시 폴더의 실제 .db 파일을 사용하며 lesson02.db를 덮어쓰지 않는다.
정렬·도시·상한·빈 결과·0·음수·SQL처럼 보이는 값·준비 재실행을 확인한다.
`서울' OR 1=1 --`는 실제 SQL 조건이 아니라 도시 문자열 값으로 전달되어 []여야 한다.
임시 폴더는 검사 종료 시 정리된다.

## 파일 안내

| 파일 | 용도 |
| --- | --- |
| main.py | 샘플 저장·조건 조회·0 오류 재현·수정 |
| solution.py | 같은 코드의 최소 수정 비교 |
| check.py | 10개 실제 조회·입력 검사 |
| CODEX_PROMPTS.md | 분석·수정·검토 시 복사할 프롬프트 |
| ANSWERS.md | 수정 원리·질문 답·평가 기준 |
| SOURCES.md | 공식 SELECT·sqlite3 동작 확인 |
| VERIFICATION.md | 제작 시 실행한 출력과 검증 한계 |
| lesson_scope.json | 배포 전 범위 검증 메타데이터. 실습 실행 파일 아님 |

## 오개념과 막히는 지점

| 증상·생각 | 확인 |
| --- | --- |
| LIMIT 10이면 꼭 10행이 나온다 | 일치하는 행 개수까지만 반환 |
| id가 작으면 항상 먼저 나온다 | ORDER BY에 명시한 기준에 따름 |
| 점수만 정렬해도 동점 순서가 확정된다 | 고유 id를 추가 정렬 키로 사용 |
| 0은 값을 안 넣은 것과 같다 | CLI에서 생략과 명시적 0을 구분 |
| no such column: city | 1차시 DB를 지정하지 않았는지 확인 |
| 샘플 값을 바꿨는데 반영되지 않는다 | OR IGNORE는 갱신하지 않음. --db fresh02.db처럼 새 이름 사용 |
| autocommit 키워드 오류 | python --version으로 3.12 이상 확인 |
| DB 파일을 다시 지워야 한다 | 고정 샘플 준비는 재실행 가능. 기존 개인 DB는 삭제하지 않음 |

## 확인 질문·제출

1. WHERE와 ORDER BY는 각각 무엇을 정하는가?
2. DESC와 ASC는 어떤 순서인가?
3. id를 두 번째 정렬 키로 쓰는 이유는 무엇인가?
4. 서울 전체와 상위 2명의 id를 적어 보자.
5. LIMIT 0과 입력 생략은 어떻게 다른가?
6. 음수의 SQL 동작과 이 함수 정책은 어떻게 다른가?
7. 두 ?에는 어떤 값이 어떤 순서로 들어가는가?
8. 없는 도시의 조회는 왜 정상인가?
9. INSERT OR IGNORE는 기존 값을 수정하는가?
10. 1차시 DB 파일을 그대로 지정하면 왜 안 되는가?

제출: main.py, 수정 전후 검사 출력, 0이 바뀌는 위치 설명, 도시·정렬·상한의 역할 설명.
비교 답과 평가 기준은 ANSWERS.md에서 확인한다.
다음에는 WHERE 조건을 사용해 특정 행을 수정·삭제하고 트랜잭션으로 결과를 확인한다.
진행 후 난이도·활동 분량·설명 깊이 피드백을 기록한다.