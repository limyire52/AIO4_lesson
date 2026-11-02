import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from .config import ROOT, db_path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def uid():
    return str(uuid4())


@contextmanager
def connect(write=False):
    db = sqlite3.connect(db_path(), timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    db.create_function('casefold', 1, lambda s: s.casefold() if s else '')
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def migrate():
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version == 0:
            sql = (ROOT / 'migrations/001_initial.sql').read_text(encoding='utf-8')
            db.executescript('BEGIN IMMEDIATE;\n' + sql + '\nCOMMIT;')
        elif version != 1:
            raise RuntimeError('지원하지 않는 DB 버전입니다.')
