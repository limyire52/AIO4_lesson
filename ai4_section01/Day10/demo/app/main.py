import secrets
import sqlite3
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from .config import ROOT, secure, session_seconds
from .db import connect, now, uid
from .models import Login, Signup, Post, PostEdit, Password, Comment, Report, ReportEdit, Rule
from .security import csrf, identity, digest, verify, DUMMY, password_budget, reset_password_budget, limit
from .services import create_user, email_address, rules, active_post, active_comment, owner, recheck, session, display_post
from .filtering import mask, validate

app = FastAPI(title='community-demo', docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def guard(request: Request, call_next):
    if request.headers.get('content-length', '0').isdigit() and int(request.headers.get('content-length', '0')) > 131072:
        return JSONResponse({'detail': '입력 데이터가 너무 큽니다.'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    return JSONResponse({'detail': '입력 형식과 길이를 확인하세요.'}, status_code=400)


@app.exception_handler(sqlite3.IntegrityError)
async def conflict(request, exc):
    return JSONResponse({'detail': '중복되거나 올바르지 않은 데이터입니다.'}, status_code=409)


@app.exception_handler(sqlite3.OperationalError)
async def unavailable(request, exc):
    return JSONResponse({'detail': '저장소를 사용할 수 없습니다. 잠시 후 다시 시도하세요.'}, status_code=503,
                        headers={'Retry-After': '2'})


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/static/{filename}')
def static(filename: str):
    if filename not in {'app.js', 'style.css'}:
        raise HTTPException(404)
    return FileResponse(ROOT / 'static' / filename)


@app.get('/health')
def health():
    with connect() as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
    return {'status': 'ok' if version == 1 else 'migration_required'}


@app.get('/api/auth/csrf')
def csrf_token():
    token = secrets.token_urlsafe(32)
    response = JSONResponse({'csrf_token': token})
    response.set_cookie('csrf', token, httponly=True, secure=secure(), samesite='strict')
    return response


@app.post('/api/auth/signup', status_code=201)
def signup(data: Signup, request: Request):
    csrf(request)
    # Hashing is expensive even for an unauthenticated signup.
    limit('signup_ip', request.client.host if request.client else 'unknown', 5, 60)
    return {'id': create_user(data.email, data.nickname, data.password)}


@app.post('/api/auth/login')
def login(data: Login, request: Request):
    csrf(request)
    email = data.email.strip().lower()
    password_budget(request, email)
    with connect() as db:
        user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    valid = verify(user['password_hash'] if user else DUMMY, data.password)
    if not user or not valid:
        raise HTTPException(401, '이메일 또는 비밀번호를 확인하세요.')
    reset_password_budget(email, request=request)
    old = request.cookies.get('session')
    if old:
        with connect(write=True) as db:
            db.execute('UPDATE sessions SET revoked_at=? WHERE token_hash=?', (now(), digest(old)))
    response = JSONResponse({'nickname': user['nickname'], 'role': user['role']})
    response.set_cookie('session', session(user['id']), httponly=True, secure=secure(), samesite='lax', max_age=session_seconds())
    token = secrets.token_urlsafe(32)
    response.set_cookie('csrf', token, httponly=True, secure=secure(), samesite='strict')
    return response


@app.post('/api/auth/logout')
def logout(request: Request):
    csrf(request)
    user = identity(request)
    with connect(write=True) as db:
        db.execute('UPDATE sessions SET revoked_at=? WHERE id=?', (now(), user['session_id']))
    response = JSONResponse({'message': '로그아웃했습니다.'})
    response.delete_cookie('session', secure=secure(), httponly=True, samesite='lax')
    return response


@app.get('/api/auth/me')
def me(request: Request):
    user = identity(request)
    return {k: user[k] for k in ('id', 'nickname', 'role')}


@app.get('/api/posts')
def posts(request: Request, page: int = Query(1, ge=1, le=1000000),
          target: str = Query('all', pattern='^(title|content|all)$'), q: str = Query('', max_length=200)):
    identity(request)
    q = q.strip().casefold()
    escaped = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    columns = ['title', 'content'] if target == 'all' else [target]
    condition = 'deleted_at IS NULL'
    args = []
    if q:
        condition += ' AND (' + ' OR '.join(f"casefold({c}) LIKE ? ESCAPE '\\'" for c in columns) + ')'
        args = [escaped] * len(columns)
    with connect() as db:
        total = db.execute('SELECT count(*) FROM posts WHERE ' + condition, args).fetchone()[0]
        pages = max(1, (total + 9) // 10)
        page = min(page, pages)
        rows = db.execute('SELECT id,title FROM posts WHERE ' + condition + ' ORDER BY created_at DESC,id DESC LIMIT 10 OFFSET ?',
                          args + [(page - 1) * 10]).fetchall()
        current_rules = rules(db)
        return {'items': [{'id': r['id'], 'title': mask(r['title'], current_rules)} for r in rows],
                'page': page, 'pages': pages, 'total': total}


@app.post('/api/posts', status_code=201)
def create_post(data: Post, request: Request):
    csrf(request)
    user = identity(request)
    limit('post', user['id'], 5, 60)
    with connect(write=True) as db:
        post_id, stamp = uid(), now()
        db.execute('INSERT INTO posts VALUES (?,?,?,?,?,?,NULL)',
                   (post_id, user['id'], data.title, data.content, stamp, stamp))
    return {'id': post_id}


@app.get('/api/posts/{post_id}')
def get_post(post_id: str, request: Request):
    user = identity(request)
    with connect() as db:
        return display_post(active_post(db, post_id), rules(db), user)


@app.post('/api/posts/{post_id}/edit-access')
def edit_access(post_id: str, data: Password, request: Request):
    csrf(request)
    user = identity(request)
    with connect() as db:
        row = active_post(db, post_id)
        owner(row, user)
    recheck(request, user, data.password)
    return {'title': row['title'], 'content': row['content']}


@app.patch('/api/posts/{post_id}')
def edit_post(post_id: str, data: PostEdit, request: Request):
    csrf(request)
    user = identity(request)
    with connect() as db:
        owner(active_post(db, post_id), user)
    recheck(request, user, data.password)
    with connect(write=True) as db:
        owner(active_post(db, post_id), user)
        db.execute('UPDATE posts SET title=?,content=?,updated_at=? WHERE id=?', (data.title, data.content, now(), post_id))
    return {'message': '수정했습니다.'}


@app.post('/api/posts/{post_id}/delete')
def delete_post(post_id: str, data: Password, request: Request):
    csrf(request)
    user = identity(request)
    with connect() as db:
        owner(active_post(db, post_id), user)
    recheck(request, user, data.password)
    with connect(write=True) as db:
        owner(active_post(db, post_id), user)
        stamp = now()
        db.execute('UPDATE posts SET deleted_at=? WHERE id=?', (stamp, post_id))
        db.execute('UPDATE comments SET deleted_at=? WHERE post_id=? AND deleted_at IS NULL', (stamp, post_id))
    return {'message': '삭제했습니다.'}


@app.get('/api/posts/{post_id}/comments')
def comments(post_id: str, request: Request):
    user = identity(request)
    with connect() as db:
        active_post(db, post_id)
        current_rules = rules(db)
        return [{'id': r['id'], 'nickname': r['nickname'], 'content': mask(r['content'], current_rules),
                 'is_owner': r['author_id'] == user['id']} for r in db.execute(
                     'SELECT c.*,u.nickname FROM comments c JOIN users u ON c.author_id=u.id '
                     'WHERE post_id=? AND deleted_at IS NULL ORDER BY created_at,id', (post_id,))]


@app.post('/api/posts/{post_id}/comments', status_code=201)
def create_comment(post_id: str, data: Comment, request: Request):
    csrf(request)
    user = identity(request)
    limit('comment', user['id'], 10, 60)
    with connect(write=True) as db:
        active_post(db, post_id)
        comment_id, stamp = uid(), now()
        db.execute('INSERT INTO comments VALUES (?,?,?,?,?,?,NULL)',
                   (comment_id, post_id, user['id'], data.content, stamp, stamp))
    return {'id': comment_id}


@app.get('/api/comments/{comment_id}/edit-access')
def comment_access(comment_id: str, request: Request):
    user = identity(request)
    with connect() as db:
        row = active_comment(db, comment_id)
        owner(row, user)
    return {'content': row['content']}


@app.patch('/api/comments/{comment_id}')
def edit_comment(comment_id: str, data: Comment, request: Request):
    csrf(request)
    user = identity(request)
    with connect(write=True) as db:
        owner(active_comment(db, comment_id), user)
        db.execute('UPDATE comments SET content=?,updated_at=? WHERE id=?', (data.content, now(), comment_id))
    return {'message': '댓글을 수정했습니다.'}


@app.delete('/api/comments/{comment_id}')
def delete_comment(comment_id: str, request: Request):
    csrf(request)
    user = identity(request)
    with connect(write=True) as db:
        owner(active_comment(db, comment_id), user)
        db.execute('UPDATE comments SET deleted_at=? WHERE id=?', (now(), comment_id))
    return {'message': '댓글을 삭제했습니다.'}


@app.post('/api/reports', status_code=201)
def report(data: Report, request: Request):
    csrf(request)
    user = identity(request)
    limit('report', user['id'], 5, 60)
    with connect(write=True) as db:
        (active_post if data.target_type == 'POST' else active_comment)(db, data.target_id)
        report_id = uid()
        db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,NULL,NULL,?,NULL)',
                   (report_id, user['id'], data.target_type, data.target_id if data.target_type == 'POST' else None,
                    data.target_id if data.target_type == 'COMMENT' else None, data.reason, 'RECEIVED', now()))
    return {'id': report_id, 'message': '신고가 접수되었습니다.'}


@app.get('/api/admin/filter-rules')
def rule_list(request: Request):
    identity(request, admin=True)
    with connect() as db:
        return rules(db)


@app.post('/api/admin/filter-rules', status_code=201)
def add_rule(data: Rule, request: Request):
    csrf(request)
    user = identity(request, admin=True)
    rule = data.model_dump()
    if (data.rule_type == 'REGEX') != (data.match_mode == 'REGEX'):
        raise HTTPException(400, '규칙 유형과 일치 방식을 확인하세요.')
    validate(rule)
    with connect(write=True) as db:
        if db.execute('SELECT count(*) FROM filter_rules').fetchone()[0] >= 200:
            raise HTTPException(400, '규칙은 최대 200개까지 등록할 수 있습니다.')
        rule_id = uid()
        db.execute('INSERT INTO filter_rules VALUES (?,?,?,?,?,?,?,?,?)',
                   (rule_id, data.rule_type, data.pattern, data.match_mode, int(data.case_sensitive),
                    data.replacement, data.priority, user['id'], now()))
    return {'id': rule_id}


@app.delete('/api/admin/filter-rules/{rule_id}')
def delete_rule(rule_id: str, request: Request):
    csrf(request)
    identity(request, admin=True)
    with connect(write=True) as db:
        if not db.execute('DELETE FROM filter_rules WHERE id=?', (rule_id,)).rowcount:
            raise HTTPException(404, '규칙을 찾을 수 없습니다.')
    return {'message': '규칙을 삭제했습니다.'}


def report_view(db, row):
    result = dict(row)
    target = db.execute('SELECT * FROM ' + ('posts' if row['target_type'] == 'POST' else 'comments') + ' WHERE id=?',
                        (row['post_id'] or row['comment_id'],)).fetchone()
    result['target_deleted'] = not target or target['deleted_at'] is not None
    result['target_content'] = '[삭제된 대상]' if result['target_deleted'] else mask(target['content'], rules(db))
    return result


@app.get('/api/admin/reports')
def report_list(request: Request, status: str = Query('', pattern='^(|RECEIVED|IN_REVIEW|RESOLVED)$')):
    identity(request, admin=True)
    with connect() as db:
        rows = db.execute('SELECT * FROM reports WHERE (?=\'\' OR status=?) ORDER BY created_at DESC,id', (status, status)).fetchall()
        return [report_view(db, row) for row in rows]


@app.get('/api/admin/reports/{report_id}')
def report_detail(report_id: str, request: Request):
    identity(request, admin=True)
    with connect() as db:
        row = db.execute('SELECT * FROM reports WHERE id=?', (report_id,)).fetchone()
        if not row:
            raise HTTPException(404, '신고를 찾을 수 없습니다.')
        return report_view(db, row)


@app.patch('/api/admin/reports/{report_id}')
def handle_report(report_id: str, data: ReportEdit, request: Request):
    csrf(request)
    user = identity(request, admin=True)
    with connect(write=True) as db:
        changed = db.execute('UPDATE reports SET status=?,admin_note=?,handled_by=?,handled_at=? WHERE id=?',
                             (data.status, data.admin_note, user['id'], now(), report_id)).rowcount
        if not changed:
            raise HTTPException(404, '신고를 찾을 수 없습니다.')
    return {'message': '처리 내용을 저장했습니다.'}
