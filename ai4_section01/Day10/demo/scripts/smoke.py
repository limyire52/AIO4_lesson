"""Minimal application for checking free ASGI account availability before deploying real data."""
from fastapi import FastAPI

app = FastAPI()


@app.get('/')
def root():
    return {'status': 'ASGI smoke test ok'}
