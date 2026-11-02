"""WHERE 없는 UPDATE·DELETE를 임시 DB에서 재현하고 항상 rollback한다."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from Day10.lesson_03.main3 import prepare_database, read_users


if __name__ == "__main__":
    with TemporaryDirectory() as folder:
        for index, sql in enumerate([
            "UPDATE users SET points = 0",
            "DELETE FROM users",
        ]):
            print('='*100)
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
