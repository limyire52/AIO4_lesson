import os
from dotenv import load_dotenv

# .env 읽어
load_dotenv()

# 환경변수 읽어오기
print(os.getenv("host"))
print(os.getenv("port"))
print(os.getenv("dbname"))
print(os.getenv("user"))
print(os.getenv("password"))