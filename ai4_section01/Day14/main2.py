import os 
import time
import uuid

import redis
from dotenv import load_dotenv

load_dotenv()

host = os.getenv('REDIS_HOST')
port_text = os.getenv('REDIS_PORT')
port = int(port_text)

prefix = f'Day14:message:{uuid.uuid4().hex}'   # 매번 실행할때마다 다른 키를 생성
string_key = f"{prefix}:status"
hash_key = f"{prefix}:profile"
list_key = f"{prefix}:message"

with redis.Redis(
    host=host,
    port=port,
    decode_responses=True,  # bytes대신에 문자열
    socket_connect_timeout=2,   # 연결설정 2초 제한
    socket_timeout=2   # 읽기 쓰기 제한시간 2초
)as client: 
    print(f'PING : {client.ping()}')
    try:
        client.set(string_key, 'ready',ex=60)
        # mapping으로 여러 필드와 값을 한키에 넣는다.
        added = client.hset(
            hash_key,   # 사용자 프로필 담을 키
            mapping={'name': 'honggildong', 'level':'basic'}
        )
        client.expire(hash_key,60)
        print(f"hash의 새 필드 수: {added}")
        print(f"hash 이름: {client.hget(hash_key,'name')}")
        client.hset(hash_key, 'level','practice')
        print(f"hash 전체: {client.hgetall(hash_key)}")
    except Exception as e:
        print(e)