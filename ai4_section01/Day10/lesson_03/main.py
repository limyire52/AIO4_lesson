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
