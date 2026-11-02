from getpass import getpass

import psycopg
import uvicorn
from fastapi import APIRouter, FastAPI, Request
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="사용자 등록·조회 실습")
router = APIRouter(tags=["users"])


class UserCreate(BaseModel): # 타입 검사
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=1, max_length=100)


def initialize_database(db_config):
    with psycopg.connect(**db_config) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS kdt_api01;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kdt_api01.users (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL
            );
        """)


def get_connection(request: Request):
    return psycopg.connect(
        **request.app.state.db_config,
        row_factory=dict_row,
    )


@router.post("/users", status_code=201)
def create_user(user: UserCreate, request: Request):
    with get_connection(request) as conn:
        row = conn.execute(
            """
            INSERT INTO kdt_api01.users (name, email)
            VALUES (%s, %s)
            RETURNING id, name, email;
            """,
            (user.name, user.email),
        ).fetchone()
    return row


@router.get("/users")
def list_users(request: Request):
    with get_connection(request) as conn:
        rows = conn.execute("""
            SELECT id, name, email
            FROM kdt_api01.users
            ORDER BY id;
        """).fetchall()
    return rows


app.include_router(router)


if __name__ == "__main__":
    db_config = {
        "host": os.getenv('host'),
        "port": os.getenv('port'),
        "dbname": os.getenv('dbname'),
        "user": os.getenv('user'),
        "password": os.getenv('password'),
        "sslmode": "require",
        "connect_timeout": 10,
    }
    initialize_database(db_config)
    app.state.db_config = db_config
    print("DB 준비 완료. http://127.0.0.1:8000/docs 에 접속하세요.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
