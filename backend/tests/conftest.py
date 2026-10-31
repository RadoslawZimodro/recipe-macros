"""Pytest setup: run the suite against a throwaway PostgreSQL database, never the dev one.

The test database (`<dev db>_test`) is dropped, recreated and migrated with Alembic once per
session, so the migrations themselves are exercised. Tables are truncated between tests.
DATABASE_URL is overridden BEFORE any `app` import, so the application engine points at it.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent

_dev_url = make_url(
    os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5440/recipe_macros"
    )
)
TEST_DB_NAME = f"{_dev_url.database}_test"
TEST_DATABASE_URL = _dev_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import rate_limit  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


def _recreate_test_database() -> None:
    assert TEST_DB_NAME.endswith("_test")  # guard: this function drops a database
    maintenance_url = _dev_url.set(database="postgres").render_as_string(hide_password=False)
    admin = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    _recreate_test_database()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_state():
    """Empty every table and reset the in-memory rate limiter before each test."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE users, refresh_tokens RESTART IDENTITY CASCADE"))
    rate_limit.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
