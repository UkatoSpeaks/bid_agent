"""FastAPI application entry point."""

from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
