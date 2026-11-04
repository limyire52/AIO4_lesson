import json
from pathlib import Path
from getpass import getpass

# pip install "psycopg[binary]"
import psycopg

# config.json 설정파일을 로드
config_path = Path(__file__).with_name('config.json')
config = json.loads(config_path.read_text(encoding='utf-8'))

# supabase 플랫폼의 database 접속
with psycopg.connect(
    host = config['host'],
    port = config['port'],
    dbname = config.get('dbname', config.get('database')),
    user = config['user'],
    password = config['password'],
    sslmode = 'require',
    connect_timeout = 10
)as conn:
   result = conn.execute(
        "select current_database(), current_user;"
    ).fetchone()

   print('접속성공')
   print(f'데이터베이스 : {result[0]}')
   print(f'사용자 : {result[1]}')