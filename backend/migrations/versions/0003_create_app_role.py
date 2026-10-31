"""create restricted app_user role and tenant helper function

The API connects as `app_user`, which owns nothing and cannot bypass Row-Level Security
(superusers and table owners can). Migrations keep running as the owner. Privileges are
granted per table, only what the API needs (least privilege); later migrations grant on
their own tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # quote_literal escapes the password safely; ':' is escaped so text() won't see a bind param.
    password = bind.execute(
        sa.text("SELECT quote_literal(:pw)"), {"pw": get_settings().app_db_password}
    ).scalar_one()
    password = password.replace(":", r"\:")
    role_exists = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'")).first()
    verb = "ALTER" if role_exists else "CREATE"
    # Roles are cluster-wide, so the role may already exist from another database
    # (e.g. the test database); re-running ALTER keeps the password in sync.
    op.execute(
        f"{verb} ROLE app_user LOGIN PASSWORD {password} "
        "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
    )

    op.execute("GRANT USAGE ON SCHEMA public TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON users, refresh_tokens TO app_user")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE users_id_seq, refresh_tokens_id_seq TO app_user")

    # The tenant id is set per transaction by the application (SELECT set_config(...,
    # true)); every RLS policy compares user_id with this function. NULL (not set) matches
    # no row, so a forgotten context fails closed.
    op.execute(
        """
        CREATE FUNCTION app_current_user_id() RETURNS integer
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.current_user_id', true), '')::integer $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION app_current_user_id()")
    op.execute("REVOKE USAGE, SELECT ON SEQUENCE users_id_seq, refresh_tokens_id_seq FROM app_user")
    op.execute("REVOKE ALL ON users, refresh_tokens FROM app_user")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app_user")
    # The role itself is not dropped: it is cluster-wide and may serve other databases.
