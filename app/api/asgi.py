"""Uvicorn entrypoint: `uvicorn app.api.asgi:app --reload`"""
from app.api.main import create_app

app = create_app()
