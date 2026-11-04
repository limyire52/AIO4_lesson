CREATE TABLE users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE CHECK(length(email)<=254),
 nickname TEXT NOT NULL CHECK(length(trim(nickname)) BETWEEN 1 AND 50),
 password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'USER' CHECK(role IN ('USER','ADMIN')),
 created_at TEXT NOT NULL
);
CREATE TABLE posts (
 id TEXT PRIMARY KEY, author_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
 content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 20000),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE comments (
 id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE RESTRICT,
 author_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 2000),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE sessions (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 revoked_at TEXT, CHECK(expires_at>created_at)
);
CREATE TABLE filter_rules (
 id TEXT PRIMARY KEY, rule_type TEXT NOT NULL CHECK(rule_type IN ('KEYWORD','REGEX')),
 pattern TEXT NOT NULL CHECK(length(trim(pattern)) BETWEEN 1 AND 500),
 match_mode TEXT NOT NULL CHECK(match_mode IN ('PARTIAL','WORD','REGEX')),
 case_sensitive INTEGER NOT NULL DEFAULT 0 CHECK(case_sensitive IN (0,1)),
 replacement TEXT NOT NULL DEFAULT '***' CHECK(length(replacement) BETWEEN 1 AND 20),
 priority INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 CHECK((rule_type='REGEX' AND match_mode='REGEX') OR (rule_type='KEYWORD' AND match_mode IN ('PARTIAL','WORD'))),
 UNIQUE(rule_type,pattern,match_mode,case_sensitive)
);
CREATE TABLE reports (
 id TEXT PRIMARY KEY, reporter_id TEXT NOT NULL REFERENCES users(id),
 target_type TEXT NOT NULL CHECK(target_type IN ('POST','COMMENT')),
 post_id TEXT REFERENCES posts(id), comment_id TEXT REFERENCES comments(id),
 reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000),
 status TEXT NOT NULL DEFAULT 'RECEIVED' CHECK(status IN ('RECEIVED','IN_REVIEW','RESOLVED')),
 admin_note TEXT CHECK(length(admin_note)<=2000), handled_by TEXT REFERENCES users(id),
 created_at TEXT NOT NULL, handled_at TEXT,
 CHECK((target_type='POST' AND post_id IS NOT NULL AND comment_id IS NULL) OR
 (target_type='COMMENT' AND post_id IS NULL AND comment_id IS NOT NULL))
);
CREATE TABLE rate_limit_buckets (
 action TEXT NOT NULL, subject_hash TEXT NOT NULL, window_start TEXT NOT NULL,
 request_count INTEGER NOT NULL DEFAULT 0 CHECK(request_count>=0), expires_at TEXT NOT NULL,
 PRIMARY KEY(action,subject_hash,window_start)
);
CREATE INDEX posts_author ON posts(author_id);
CREATE INDEX posts_list ON posts(deleted_at,created_at,id);
CREATE INDEX comments_list ON comments(post_id,deleted_at,created_at,id);
CREATE INDEX reports_status ON reports(status,created_at);
CREATE INDEX reports_post ON reports(post_id);
CREATE INDEX reports_comment ON reports(comment_id);
CREATE INDEX reports_reporter ON reports(reporter_id);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE INDEX sessions_expiry ON sessions(expires_at);
CREATE INDEX buckets_expiry ON rate_limit_buckets(expires_at);
PRAGMA user_version=1;
