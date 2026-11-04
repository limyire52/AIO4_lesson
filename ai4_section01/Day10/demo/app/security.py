import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from .db import connect, now

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY = hasher.hash(secrets.token_urlsafe(24))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def verify(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def identity(request: Request, admin=False):
    with connect() as db:
        row = db.execute('SELECT u.*, s.id session_id FROM sessions s JOIN users u ON u.id=s.user_id '
                         'WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?',
                         (digest(request.cookies.get('session', '')), now())).fetchone()
    if not row:
        raise HTTPException(401, '로그인이 필요합니다.')
    if admin and row['role'] != 'ADMIN':
        raise HTTPException(403, '관리자만 사용할 수 있습니다.')
    return dict(row)


def csrf(request: Request):
    cookie = request.cookies.get('csrf', '')
    header = request.headers.get('x-csrf-token', '')
    if not cookie or not hmac.compare_digest(cookie, header):
        raise HTTPException(403, '화면을 새로고침한 뒤 다시 시도하세요.')
    # Same-origin JSON requests with a custom header cannot be sent by an unrelated site.
    origin = request.headers.get('origin')
    expected_origin = os.environ.get('PUBLIC_ORIGIN', str(request.base_url)).rstrip('/')
    if origin and origin != expected_origin:
        raise HTTPException(403, '다른 출처의 요청은 허용되지 않습니다.')


def limit(action, subject, maximum, seconds):
    maximum = int(os.environ.get('LIMIT_' + action.upper(), maximum))
    timestamp = time.time()
    start = int(timestamp // seconds) * seconds
    end = start + seconds
    fmt = lambda x: datetime.fromtimestamp(x, timezone.utc).isoformat(timespec='microseconds')
    blocked = False
    with connect(write=True) as db:
        row = db.execute('SELECT request_count FROM rate_limit_buckets WHERE action=? AND subject_hash=? AND window_start=?',
                         (action, digest(subject), fmt(start))).fetchone()
        if row and row[0] >= maximum:
            blocked = True
        else:
            db.execute('INSERT INTO rate_limit_buckets VALUES (?,?,?,?,?) ON CONFLICT(action,subject_hash,window_start) '
                       'DO UPDATE SET request_count=request_count+1',
                       (action, digest(subject), fmt(start), 1, fmt(end)))
        db.execute('DELETE FROM rate_limit_buckets WHERE rowid IN '
                   '(SELECT rowid FROM rate_limit_buckets WHERE expires_at<? LIMIT 20)', (now(),))
    if blocked:
        raise HTTPException(429, '요청이 너무 많습니다. 잠시 후 다시 시도하세요.',
                            headers={'Retry-After': str(max(1, int(end - timestamp) + 1))})


def password_budget(request, email, action='login'):
    # Reserve before expensive verification so parallel guesses cannot exceed the budget.
    limit(action + '_ip', request.client.host if request.client else 'unknown', 30, 900)
    limit(action + '_account', email, 5, 900)


def reset_password_budget(email, action='login', request=None):
    with connect(write=True) as db:
        subjects = [(action + '_account', email)]
        if request:
            subjects.append((action + '_ip', request.client.host if request.client else 'unknown'))
        for key, subject in subjects:
            db.execute('UPDATE rate_limit_buckets SET request_count=max(0,request_count-1) '
                       'WHERE action=? AND subject_hash=? AND expires_at>?', (key, digest(subject), now()))
