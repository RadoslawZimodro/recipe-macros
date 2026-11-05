import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.dependencies import CSRF_HEADER
from app.routers import auth, food_log, ingredients, pantry, recipe_import, recipes

logger = logging.getLogger(__name__)

app = FastAPI(title="Recipe Macros API")

# allow_credentials=True is required for the browser to send/receive the auth cookies. The
# CORS spec forbids combining credentials with wildcard origins/headers, so both are explicit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", CSRF_HEADER],
)

app.include_router(auth.router)
app.include_router(recipe_import.router)
app.include_router(recipes.router)
app.include_router(ingredients.router)
app.include_router(food_log.router)
app.include_router(pantry.router)
app.include_router(pantry.staples_router)
app.include_router(ingredients.units_router)


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
