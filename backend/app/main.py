import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

logger = logging.getLogger(__name__)

app = FastAPI(title="Recipe Macros API")


def _check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database health check failed")
        return False


def _check_redis() -> bool:
    try:
        with Redis.from_url(get_settings().redis_url, socket_timeout=2) as client:
            return bool(client.ping())
    except Exception:
        logger.exception("Redis health check failed")
        return False


@app.get("/health")
def health() -> JSONResponse:
    checks = {"db": _check_db(), "redis": _check_redis()}
    healthy = all(checks.values())
    body = {"status": "ok" if healthy else "error"}
    body.update({name: "ok" if ok else "error" for name, ok in checks.items()})
    return JSONResponse(body, status_code=200 if healthy else 503)
