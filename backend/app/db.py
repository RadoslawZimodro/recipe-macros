from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# pool_pre_ping drops dead connections (e.g. after a Postgres restart) instead of failing a request.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for ORM models; its metadata drives Alembic autogenerate."""


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
