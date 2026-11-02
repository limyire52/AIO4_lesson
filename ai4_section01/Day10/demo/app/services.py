import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from . import security
from .config import session_seconds
from .db import connect, now, uid
from .filtering import mask


def email_address(value):
    value = value.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value) or len(value) > 254:
        raise HTTPException(400, '올바른 이메일 주소를 입력하세요.')
    return value


def create_user(email, nickname, password, role='USER'):
    email = email_address(email)
    nickname = nickname.strip()
    if not nickname or len(nickname) > 50 or not 8 <= len(password) <= 128:
        raise HTTPException(400, '닉네임은 1~50자, 비밀번호는 8~128자로 입력하세요.')
    encoded = security.hasher.hash(password)
    with connect(write=True) as db:
        user_id = uid()
        db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',
                   (user_id, email, nickname, encoded, role, now()))
    return user_id


def rules(db):
    return [dict(r) for r in db.execute('SELECT * FROM filter_rules ORDER BY priority DESC,id')]


def active_post(db, post_id):
    row = db.execute('SELECT * FROM posts WHERE id=? AND deleted_at IS NULL', (post_id,)).fetchone()
    if not row:
        raise HTTPException(404, '게시글을 찾을 수 없습니다.')
    return dict(row)


def active_comment(db, comment_id):
    row = db.execute('SELECT c.* FROM comments c JOIN posts p ON c.post_id=p.id '
                     'WHERE c.id=? AND c.deleted_at IS NULL AND p.deleted_at IS NULL', (comment_id,)).fetchone()
    if not row:
        raise HTTPException(404, '댓글을 찾을 수 없습니다.')
    return dict(row)


def owner(row, user):
    if row['author_id'] != user['id']:
        raise HTTPException(403, '본인이 작성한 내용만 변경할 수 있습니다.')


def recheck(request, user, password):
    security.password_budget(request, user['email'], 'recheck')
    if not security.verify(user['password_hash'], password):
        raise HTTPException(403, '비밀번호가 일치하지 않습니다.')
    security.reset_password_budget(user['email'], 'recheck', request)


def session(user_id):
    token = secrets.token_urlsafe(32)
    stamp = now()
    expires = (datetime.now(timezone.utc) + timedelta(seconds=session_seconds())).isoformat(timespec='microseconds')
    with connect(write=True) as db:
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,NULL)',
                   (uid(), user_id, security.digest(token), stamp, expires))
    return token


def display_post(row, current_rules, user):
    return {'id': row['id'], 'title': mask(row['title'], current_rules),
            'content': mask(row['content'], current_rules), 'is_owner': row['author_id'] == user['id']}
