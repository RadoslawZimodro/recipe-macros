from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# pool_pre_ping drops dead connections (e.g. after a Postgres restart) instead of failing a request.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Deterministic constraint/index names, so Alembic autogenerate and later migrations can
# refer to them (otherwise Postgres invents names like users_email_key).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for ORM models; its metadata drives Alembic autogenerate."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# The tenant id lives in a transaction-local setting (`set_config(..., true)`), which PostgreSQL
# discards at COMMIT/ROLLBACK, so it can never leak to another request through the connection
# pool. It is re-applied at the start of every transaction from the value kept on the session,
# so request flows that commit more than once keep their tenant context.
@event.listens_for(SessionLocal, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    user_id = session.info.get("tenant_user_id")
    if user_id is not None:
        connection.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"), {"uid": str(user_id)}
        )


def set_tenant(session: Session, user_id: int) -> None:
    """Bind the RLS tenant to `user_id` for this session (current and later transactions).

    Must only be called with the id of an authenticated user (see get_current_user).
    """
    session.info["tenant_user_id"] = user_id
    session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"), {"uid": str(user_id)}
    )


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
