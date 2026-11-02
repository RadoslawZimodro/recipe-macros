"""allow 'microdata' as a recipe import method

Recipes read from schema.org Microdata are stored with import_method = 'microdata' instead
of being mislabelled 'jsonld'.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE recipes DROP CONSTRAINT ck_recipes_import_method")
    op.execute(
        "ALTER TABLE recipes ADD CONSTRAINT ck_recipes_import_method "
        "CHECK (import_method IN ('jsonld', 'microdata', 'llm', 'manual'))"
    )


def downgrade() -> None:
    # The old constraint does not know 'microdata'; such recipes were read from structured
    # data too, so they fall back to the closest old value.
    op.execute("UPDATE recipes SET import_method = 'jsonld' WHERE import_method = 'microdata'")
    op.execute("ALTER TABLE recipes DROP CONSTRAINT ck_recipes_import_method")
    op.execute(
        "ALTER TABLE recipes ADD CONSTRAINT ck_recipes_import_method "
        "CHECK (import_method IN ('jsonld', 'llm', 'manual'))"
    )
