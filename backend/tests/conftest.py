"""Pytest setup: run the suite against a throwaway PostgreSQL database, never the dev one.

The test database (`<dev db>_test`) is dropped, recreated and migrated with Alembic once per
session, so the migrations themselves are exercised. Tables are truncated between tests.

Two database roles are used, exactly like in production:
  * the application engine (`app.db.engine`) connects as the restricted `app_user`, so
    Row-Level Security applies to everything the API and the `db` fixture do;
  * the `admin_db` fixture connects as the database owner (bypasses RLS) for setup and for
    asserting what is really stored.

DATABASE_URL / ADMIN_DATABASE_URL are overridden BEFORE any `app` import, so the
application engine points at the test database.
"""

import os
import re
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent

_app_url = make_url(
    os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://app_user:app_pass_dev@localhost:5440/recipe_macros"
    )
)
_admin_url = make_url(
    os.environ.get(
        "ADMIN_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5440/recipe_macros"
    )
)
TEST_DB_NAME = f"{_admin_url.database}_test"
TEST_ADMIN_URL = _admin_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = _app_url.set(database=TEST_DB_NAME).render_as_string(
    hide_password=False
)
os.environ["ADMIN_DATABASE_URL"] = TEST_ADMIN_URL
# Redis database 15 is the tests' own: it is flushed before every test, so the cache and
# rate-limit counters of the development stack (database 0) are never touched.
os.environ["REDIS_URL"] = (
    re.sub(r"/\d+$", "", os.environ.get("REDIS_URL", "redis://localhost:6379/0")) + "/15"
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import rate_limit  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.redis_client import get_redis  # noqa: E402

_admin_engine = create_engine(TEST_ADMIN_URL)


def _recreate_test_database() -> None:
    assert TEST_DB_NAME.endswith("_test")  # guard: this function drops a database
    maintenance_url = _admin_url.set(database="postgres").render_as_string(hide_password=False)
    maintenance = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with maintenance.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    maintenance.dispose()


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    _recreate_test_database()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_ADMIN_URL.replace("%", "%%"))
    command.upgrade(cfg, "head")
    yield
    engine.dispose()
    _admin_engine.dispose()


@pytest.fixture(autouse=True)
def _clean_state():
    """Empty every user-data table and reset the in-memory rate limiter before each test.

    `units` is dictionary data seeded by a migration, so it is kept.
    """
    with _admin_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE users, refresh_tokens, ingredients, recipes, recipe_steps, "
                "recipe_ingredients RESTART IDENTITY CASCADE"
            )
        )
    rate_limit.clear()
    get_redis().flushdb()


@pytest.fixture
def redis_client():
    return get_redis()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    """A session as `app_user` WITHOUT a tenant: RLS-protected tables look empty to it."""
    with SessionLocal() as session:
        yield session


@pytest.fixture
def admin_db():
    """A session as the database owner: bypasses RLS, sees and can write everything."""
    with Session(_admin_engine) as session:
        yield session


def register_client(email: str) -> TestClient:
    """A TestClient that is registered, logged in and sends the CSRF header on every request."""
    client = TestClient(app)
    response = client.post("/auth/register", json={"email": email, "password": "correcthorse7"})
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    client.user_id = response.json()["id"]
    return client


@pytest.fixture
def alice() -> TestClient:
    return register_client("alice@example.com")


@pytest.fixture
def bob() -> TestClient:
    return register_client("bob@example.com")
