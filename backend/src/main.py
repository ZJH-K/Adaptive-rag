"""ASGI entrypoint; resource construction occurs only inside lifespan."""

from src.app import create_app


app = create_app()
