import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def db_path():
    return Path(os.environ.get('DATABASE_PATH', str(ROOT / 'data/community.sqlite3'))).resolve()


def secure():
    return os.environ.get('COOKIE_SECURE', '0') == '1'


def session_seconds():
    return int(os.environ.get('SESSION_SECONDS', '7200'))
