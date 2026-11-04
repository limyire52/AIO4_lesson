import os
import sqlite3
import tempfile
import unittest
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect, migrate, now, uid
from app.services import create_user
from app.security import limit, digest
from app.filtering import mask


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DATABASE_PATH': self.temp.name + '/test.sqlite3',
                                          'COOKIE_SECURE': '0', 'LIMIT_SIGNUP_IP': '100'})
        self.env.start()
        migrate()
        self.owner = create_user('owner@example.com', '작성자', 'password123')
        self.other = create_user('other@example.com', '다른회원', 'password123')
        self.admin = create_user('admin@example.com', '관리자', 'password123', 'ADMIN')
        self.client = self.login('owner@example.com')
        self.b = self.login('other@example.com')
        self.a = self.login('admin@example.com')

    def tearDown(self):
        self.client.close()
        self.b.close()
        self.a.close()
        self.env.stop()
        self.temp.cleanup()

    def login(self, email):
        client = TestClient(app)
        token = client.get('/api/auth/csrf').json()['csrf_token']
        self.assertEqual(client.post('/api/auth/login', json={'email': email, 'password': 'password123'},
                                     headers={'X-CSRF-Token': token}).status_code, 200)
        client.headers['X-CSRF-Token'] = client.get('/api/auth/csrf').json()['csrf_token']
        return client

    def post(self, title='제목', content='내용'):
        response = self.client.post('/api/posts', json={'title': title, 'content': content})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def rule(self, pattern='금칙어', **kwargs):
        data = {'rule_type': 'KEYWORD', 'pattern': pattern, 'match_mode': 'PARTIAL', **kwargs}
        response = self.a.post('/api/admin/filter-rules', json=data)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def test_signup_validation_hash_and_roles(self):
        c = TestClient(app)
        c.headers['X-CSRF-Token'] = c.get('/api/auth/csrf').json()['csrf_token']
        payload = {'email': ' New@Example.com ', 'nickname': '새회원', 'password': 'newpassword'}
        self.assertEqual(c.post('/api/auth/signup', json=payload).status_code, 201)
        self.assertEqual(c.post('/api/auth/signup', json=payload).status_code, 409)
        self.assertEqual(c.post('/api/auth/signup', json={**payload, 'email': 'bad'}).status_code, 400)
        self.assertEqual(c.post('/api/auth/signup', json={**payload, 'role': 'ADMIN'}).status_code, 400)
        self.assertEqual(c.post('/api/auth/signup', json={**payload, 'nickname': '  '}).status_code, 400)
        with connect() as db:
            row = db.execute("SELECT * FROM users WHERE email='new@example.com'").fetchone()
            self.assertTrue(row['password_hash'].startswith('$argon2id$'))
            self.assertEqual(row['role'], 'USER')
        c.close()

    def test_session_logout_csrf_and_expiry(self):
        raw = self.client.cookies.get('session')
        with connect() as db:
            row = db.execute('SELECT * FROM sessions WHERE token_hash=?', (digest(raw),)).fetchone()
            self.assertIsNotNone(row)
            self.assertNotEqual(raw, row['token_hash'])
        self.assertEqual(self.client.post('/api/posts', json={'title': 'x', 'content': 'x'},
                                         headers={'X-CSRF-Token': 'bad'}).status_code, 403)
        self.assertEqual(self.client.post('/api/posts', json={'title': 'x', 'content': 'x'},
                                         headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.client.cookies.set('session', raw)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        with connect(write=True) as db:
            db.execute("UPDATE sessions SET expires_at='2000-01-02',created_at='2000-01-01' WHERE user_id=?", (self.other,))
        self.assertEqual(self.b.get('/api/auth/me').status_code, 401)

    def test_secure_cookie(self):
        with patch.dict(os.environ, {'COOKIE_SECURE': '1'}):
            c = TestClient(app, base_url='https://testserver')
            token = c.get('/api/auth/csrf').json()['csrf_token']
            r = c.post('/api/auth/login', json={'email': 'owner@example.com', 'password': 'password123'},
                       headers={'X-CSRF-Token': token})
            cookies = ';'.join(r.headers.get_list('set-cookie'))
            self.assertIn('Secure', cookies)
            self.assertIn('HttpOnly', cookies)
            self.assertIn('SameSite=lax', cookies)
            c.close()

    def test_search_pagination_and_delete_last_page(self):
        with connect(write=True) as db:
            for i in range(11):
                db.execute('INSERT INTO posts VALUES (?,?,?,?,?,?,NULL)',
                           (uid(), self.owner, f'제목{i}', '본문 %_ 특수', now(), now()))
        first = self.client.get('/api/posts').json()
        second = self.client.get('/api/posts?page=2').json()
        self.assertEqual(len(first['items']), 10)
        self.assertEqual(len(second['items']), 1)
        self.assertEqual(self.client.get('/api/posts?target=content&q=%25_').json()['total'], 11)
        self.assertEqual(self.client.get('/api/posts?target=title&q=없는글').json()['total'], 0)
        last = second['items'][0]['id']
        self.assertEqual(self.client.post(f'/api/posts/{last}/delete', json={'password': 'password123'}).status_code, 200)
        self.assertEqual(self.client.get('/api/posts?page=2').json()['page'], 1)
        self.assertEqual(set(first['items'][0]), {'id', 'title'})

    def test_posts_owner_password_original_and_mask(self):
        pid = self.post('금칙어', '금칙어 본문')
        rid = self.rule()
        self.assertEqual(self.client.get('/api/posts/'+pid).json()['content'], '*** 본문')
        self.assertEqual(self.b.patch('/api/posts/'+pid, json={'title': '탈취', 'content': 'x', 'password': 'password123'}).status_code, 403)
        self.assertEqual(self.client.patch('/api/posts/'+pid, json={'title': 'x', 'content': 'y', 'password': 'wrong'}).status_code, 403)
        original = self.client.post('/api/posts/'+pid+'/edit-access', json={'password': 'password123'})
        self.assertEqual(original.json()['title'], '금칙어')
        self.assertEqual(self.client.patch('/api/posts/'+pid, json={'title': '금칙어 수정', 'content': '새내용', 'password': 'password123'}).status_code, 200)
        self.assertEqual(self.a.delete('/api/admin/filter-rules/'+rid).status_code, 200)
        self.assertEqual(self.client.get('/api/posts/'+pid).json()['title'], '금칙어 수정')

    def test_comments_and_deleted_parent(self):
        pid = self.post()
        self.rule()
        cid = self.client.post(f'/api/posts/{pid}/comments', json={'content': '금칙어'}).json()['id']
        self.assertEqual(self.b.patch('/api/comments/'+cid, json={'content': '탈취'}).status_code, 403)
        self.assertEqual(self.b.delete('/api/comments/'+cid).status_code, 403)
        self.assertEqual(self.client.patch('/api/comments/'+cid, json={'content': '수정 금칙어'}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/posts/{pid}/comments').json()[0]['content'], '수정 ***')
        self.assertEqual(self.client.post(f'/api/posts/{pid}/comments', json={'content': '  '}).status_code, 400)
        self.client.post(f'/api/posts/{pid}/delete', json={'password': 'password123'})
        self.assertEqual(self.client.post(f'/api/posts/{pid}/comments', json={'content': '늦은댓글'}).status_code, 404)
        self.assertEqual(self.client.get('/api/comments/'+cid+'/edit-access').status_code, 404)
        with connect() as db:
            self.assertIsNotNone(db.execute('SELECT deleted_at FROM comments WHERE id=?', (cid,)).fetchone()[0])

    def test_reports_admin_and_deleted_target(self):
        pid = self.post()
        rid = self.b.post('/api/reports', json={'target_type': 'POST', 'target_id': pid, 'reason': '불쾌함'}).json()['id']
        self.assertEqual(self.client.get('/api/admin/reports').status_code, 403)
        self.assertEqual(self.client.patch('/api/admin/reports/'+rid, json={'status': 'RESOLVED', 'admin_note': 'secret'}).status_code, 403)
        self.assertEqual(self.a.patch('/api/admin/reports/'+rid, json={'status': 'IN_REVIEW', 'admin_note': '검토 메모'}).status_code, 200)
        row = self.a.get('/api/admin/reports/'+rid).json()
        self.assertEqual(row['handled_by'], self.admin)
        self.assertIsNotNone(row['handled_at'])
        self.client.post('/api/posts/'+pid+'/delete', json={'password': 'password123'})
        self.assertTrue(self.a.get('/api/admin/reports/'+rid).json()['target_deleted'])

    def test_rules_validation_unicode_and_remask(self):
        pid = self.post('bad', '나쁜말')
        rid = self.rule('나쁜말', match_mode='WORD')
        self.assertEqual(self.client.get('/api/posts/'+pid).json()['content'], '***')
        self.assertEqual(self.client.post('/api/admin/filter-rules', json={'rule_type': 'KEYWORD', 'pattern': 'x', 'match_mode': 'PARTIAL'}).status_code, 403)
        self.assertEqual(self.a.post('/api/admin/filter-rules', json={'rule_type': 'REGEX', 'pattern': '[', 'match_mode': 'REGEX'}).status_code, 400)
        self.assertEqual(self.a.post('/api/admin/filter-rules', json={'rule_type': 'REGEX', 'pattern': '(a+)+$', 'match_mode': 'REGEX'}).status_code, 400)
        self.assertEqual(self.a.post('/api/admin/filter-rules', json={'rule_type': 'KEYWORD', 'pattern': '나쁜말', 'match_mode': 'WORD'}).status_code, 409)
        r = [{'rule_type': 'KEYWORD', 'pattern': '나쁜말', 'match_mode': 'WORD', 'case_sensitive': 0, 'replacement': '***'}]
        self.assertEqual(mask('나쁜말단어', r), '나쁜말단어')

    def test_rate_limit_atomic_and_window(self):
        def attempt(_):
            try:
                limit('test', 'subject', 5, 60)
                return 200
            except Exception as e:
                return e.status_code
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(results.count(200), 5)
        self.assertEqual(results.count(429), 7)
        with patch('app.security.time.time', return_value=2000000040):
            limit('boundary', 'x', 1, 60)
            with self.assertRaises(Exception):
                limit('boundary', 'x', 1, 60)
        with patch('app.security.time.time', return_value=2000000100):
            limit('boundary', 'x', 1, 60)

    def test_login_failures_and_creation_limits(self):
        c = TestClient(app)
        c.headers['X-CSRF-Token'] = c.get('/api/auth/csrf').json()['csrf_token']
        for _ in range(5):
            self.assertEqual(c.post('/api/auth/login', json={'email': 'missing@example.com', 'password': 'wrong'}).status_code, 401)
        blocked = c.post('/api/auth/login', json={'email': 'missing@example.com', 'password': 'wrong'})
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(int(blocked.headers['Retry-After']), 0)
        with patch.dict(os.environ, {'LIMIT_POST': '1'}):
            self.post()
            self.assertEqual(self.client.post('/api/posts', json={'title': '차단', 'content': 'x'}).status_code, 429)
        with connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM posts').fetchone()[0], 1)
        c.close()

    def test_db_constraints_and_migration_idempotent(self):
        migrate()
        with self.assertRaises(sqlite3.IntegrityError), connect(write=True) as db:
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (uid(), self.owner, 'POST', None, None, 'x', 'RECEIVED', None, None, now(), None))
        with self.assertRaises(sqlite3.IntegrityError), connect(write=True) as db:
            db.execute('INSERT INTO posts VALUES (?,?,?,?,?,?,NULL)', (uid(), 'missing', 'x', 'x', now(), now()))
        with connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_static_security_and_xss_is_data(self):
        pid = self.post('<script>alert(1)</script>', '<img src=x onerror=alert(1)>')
        self.assertEqual(self.client.get('/api/posts/'+pid).json()['title'], '<script>alert(1)</script>')
        self.assertEqual(self.client.get('/static/community.sqlite3').status_code, 404)
        response = self.client.get('/')
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertIn('hidden', response.text)
        self.assertEqual(self.client.get('/health').json()['status'], 'ok')

    def test_backup_restore_seed_and_cleanup(self):
        backup = self.temp.name + '/backup.sqlite3'
        restore = self.temp.name + '/restore.sqlite3'
        for args in [('seed-filters',), ('seed-filters',), ('backup', '--output', backup),
                     ('restore', '--source', backup, '--output', restore), ('cleanup',)]:
            result = subprocess.run([sys.executable, '-m', 'app.cli', *args], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        db = sqlite3.connect(restore)
        self.assertEqual(db.execute('SELECT count(*) FROM filter_rules').fetchone()[0], 2)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        db.close()
        result = subprocess.run([sys.executable, '-m', 'app.cli', 'backup', '--output', backup], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_comment_delete_and_comment_report(self):
        pid = self.post()
        cid = self.client.post(f'/api/posts/{pid}/comments', json={'content': '댓글'}).json()['id']
        rid = self.b.post('/api/reports', json={'target_type': 'COMMENT', 'target_id': cid, 'reason': '신고'}).json()['id']
        self.assertEqual(self.client.delete('/api/comments/'+cid).status_code, 200)
        self.assertEqual(self.client.get(f'/api/posts/{pid}/comments').json(), [])
        self.assertTrue(self.a.get('/api/admin/reports/'+rid).json()['target_deleted'])

    def test_comment_report_recheck_limits(self):
        pid = self.post()
        with patch.dict(os.environ, {'LIMIT_COMMENT': '1', 'LIMIT_REPORT': '1', 'LIMIT_RECHECK_ACCOUNT': '1'}):
            self.assertEqual(self.client.post(f'/api/posts/{pid}/comments', json={'content': '첫댓글'}).status_code, 201)
            self.assertEqual(self.client.post(f'/api/posts/{pid}/comments', json={'content': '차단댓글'}).status_code, 429)
            self.assertEqual(self.client.post('/api/reports', json={'target_type': 'POST', 'target_id': pid, 'reason': '첫신고'}).status_code, 201)
            self.assertEqual(self.client.post('/api/reports', json={'target_type': 'POST', 'target_id': pid, 'reason': '차단신고'}).status_code, 429)
            self.assertEqual(self.client.post(f'/api/posts/{pid}/delete', json={'password': 'wrong'}).status_code, 403)
            self.assertEqual(self.client.post(f'/api/posts/{pid}/delete', json={'password': 'wrong'}).status_code, 429)
        with connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM comments').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM reports').fetchone()[0], 1)

    def test_password_spaces_and_non_ascii_search(self):
        pid = self.post('Straße', '본문')
        self.assertEqual(self.client.get('/api/posts?q=STRASSE').json()['total'], 1)
        create_user('spaces@example.com', '공백', ' pass word ')
        c = TestClient(app)
        c.headers['X-CSRF-Token'] = c.get('/api/auth/csrf').json()['csrf_token']
        self.assertEqual(c.post('/api/auth/login', json={'email': 'spaces@example.com', 'password': ' pass word '}).status_code, 200)
        c.headers['X-CSRF-Token'] = c.get('/api/auth/csrf').json()['csrf_token']
        p = c.post('/api/posts', json={'title': '공백', 'content': '비밀번호'}).json()['id']
        self.assertEqual(c.patch('/api/posts/'+p, json={'title': '수정', 'content': '수정', 'password': ' pass word '}).status_code, 200)
        c.close()

    def test_proxy_origin_and_explicit_public_origin(self):
        with patch.dict(os.environ, {'PUBLIC_ORIGIN': 'https://demo.pythonanywhere.com'}):
            r = self.client.post('/api/posts', json={'title': '출처', 'content': '검증'},
                                 headers={'Origin': 'https://demo.pythonanywhere.com'})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(self.client.post('/api/posts', json={'title': '공격', 'content': 'x'},
                                              headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_regex_overlap_timeout_and_search_injection(self):
        pid = self.post('abc', '일반 본문')
        self.rule('abc', replacement='X', priority=10)
        self.rule('bc', replacement='Y')
        self.assertEqual(self.client.get('/api/posts/'+pid).json()['title'], 'X')
        self.assertEqual(self.client.get('/api/posts', params={'q': "' OR 1=1 --"}).json()['total'], 0)
        self.assertEqual(self.client.get('/api/posts?target=password_hash').status_code, 400)
        self.assertEqual(self.client.get('/api/posts?page=0').status_code, 400)
        r = [{'rule_type': 'REGEX', 'pattern': '(a+)+$', 'match_mode': 'REGEX',
              'case_sensitive': 0, 'replacement': '***'}]
        self.assertIn('표현 필터 처리 제한', mask('a' * 20000 + '!', r))


if __name__ == '__main__':
    unittest.main()
