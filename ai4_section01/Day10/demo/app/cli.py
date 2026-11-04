import argparse
import getpass
import json
import sqlite3
from pathlib import Path
from .config import ROOT, db_path
from .db import connect, migrate, now, uid
from .services import create_user


def main():
    parser = argparse.ArgumentParser(description='community-demo 관리 명령')
    parser.add_argument('command', choices=['migrate', 'create-admin', 'seed-filters', 'cleanup', 'backup', 'restore'])
    parser.add_argument('--output', help='백업 파일의 새 경로')
    parser.add_argument('--source', help='복원할 SQLite 백업 파일')
    args = parser.parse_args()
    if args.command == 'migrate':
        migrate()
        print('DB 마이그레이션 완료')
    elif args.command == 'create-admin':
        email = input('관리자 이메일: ')
        nickname = input('닉네임: ')
        password = getpass.getpass('비밀번호(8~128자): ')
        if password != getpass.getpass('비밀번호 확인: '):
            raise SystemExit('비밀번호가 일치하지 않습니다.')
        create_user(email, nickname, password, 'ADMIN')
        print('관리자 생성 완료')
    elif args.command == 'seed-filters':
        with connect(write=True) as db:
            admin = db.execute("SELECT id FROM users WHERE role='ADMIN' ORDER BY created_at LIMIT 1").fetchone()
            if not admin:
                raise SystemExit('먼저 관리자를 생성하세요.')
            values = json.loads((ROOT / 'data_seed/filter_rules.json').read_text(encoding='utf-8'))
            for value in values:
                db.execute('INSERT OR IGNORE INTO filter_rules VALUES (?,?,?,?,?,?,?,?,?)',
                           (uid(), 'KEYWORD', value, 'PARTIAL', 0, '***', 0, admin['id'], now()))
        print('초기 표현 규칙 등록 완료 (기존 규칙 유지)')
    elif args.command == 'cleanup':
        with connect(write=True) as db:
            db.execute('DELETE FROM sessions WHERE expires_at<? OR revoked_at IS NOT NULL', (now(),))
            db.execute('DELETE FROM rate_limit_buckets WHERE expires_at<?', (now(),))
        print('만료 세션·요청 제한 데이터 정리 완료')
    elif args.command in {'backup', 'restore'}:
        if not args.output:
            raise SystemExit('--output으로 새 백업 경로를 지정하세요.')
        output = Path(args.output).resolve()
        if output.exists() or output == db_path():
            raise SystemExit('기존 파일에 덮어쓰지 않습니다.')
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.command == 'restore':
            if not args.source or not Path(args.source).is_file():
                raise SystemExit('--source로 기존 백업을 지정하세요.')
            source = sqlite3.connect(Path(args.source).resolve().as_uri() + '?mode=ro', uri=True)
        else:
            source = sqlite3.connect(db_path())
        target = sqlite3.connect(output)
        try:
            if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('원본 DB 무결성 검사에 실패했습니다.')
            if source.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise SystemExit('지원하지 않는 스키마 버전입니다.')
            with target:
                source.backup(target)
        finally:
            source.close()
            target.close()
        print('백업/복원 완료:', output)


if __name__ == '__main__':
    main()
