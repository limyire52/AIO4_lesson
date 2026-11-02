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
    # database(스키마) 생성
    conn.execute(
        "create schema if not exists ch2;"
    )

    conn.execute('''drop table if exists ch2.users;''')

    conn.execute(
        """
        create table if not exists ch2.users(
        id bigint generated always as identity primary key,
        name text not null,
        email text not null unique
        );
        """
    )

    print('테이블 준비완료')
    # 사용자 2명 입력
    users = [
        ("이순신",'ess@korea.com'),("윤봉길", 'ybg@korea.com')
    ]

    with conn.cursor() as cur :
        cur.executemany("""
            insert into ch2.users(name, email)
            values(%s, %s)
         """, users)
    print('사용자 저장완료')

    # 전체조회
    rows = conn.execute("""
        select id, name, email from ch2.users order by id
    """).fetchall()
    for user_id, user_name, user_email in rows:
        print(user_id, user_name, user_email)

    # 수정 ess@korea.com 강감찬
    conn.execute(''' update ch2.users
        set name = %s
        where email = %s 
        ;''', ('강감찬','ess@korea.com'))
    
    # 전체조회
    print('전체조회----------------------------------------------------')
    rows = conn.execute("""
        select id, name, email from ch2.users order by id
    """).fetchall() 
    for user_id, user_name, user_email in rows:
            print(user_id, user_name, user_email)

    # 삭제
    conn.execute('''delete from ch2.users where email = %s;''',("ybg@korea.com",))      

   # 전체조회
    print('전체조회----------------------------------------------------')
    rows = conn.execute("""
        select id, name, email from ch2.users order by id
    """).fetchall() 
    for user_id, user_name, user_email in rows:
        print(user_id, user_name, user_email)

print('접속 종료')