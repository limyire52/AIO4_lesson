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
            add_user(db_path, 2, "수아", "sua@example.test", None) #  None 값을 추출하지 않게 만들어야 한다. -> 함수에서 Null을 줄 수 없도록 규칙을 만들어라!
        except sqlite3.IntegrityError as exc:
            print("NULL 점수 거절:", exc)
        else:
            print("문제: NULL 점수가 저장되었습니다.")
        print(read_users(db_path))
