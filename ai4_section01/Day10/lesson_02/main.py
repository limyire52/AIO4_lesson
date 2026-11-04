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
        connection.commit() # 1차시에서 왜 여기에 commit 넣어야하는지 배움.
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
            "SELECT id, nickname, city, points FROM users " # select: 조회
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