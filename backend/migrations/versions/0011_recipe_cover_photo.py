"""recipe cover photo: a local copy of the picture of the dish

Two nullable columns on recipes, same shape and CHECKs as recipe_steps.image_*. `image_url` (the
source address) is unchanged. The table-level grants (SELECT, INSERT, UPDATE) and the existing
Row-Level Security policy on recipes already cover new columns, so nothing else is needed.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE recipes
            ADD COLUMN cover_path text,
            ADD COLUMN cover_content_type text,
            ADD CONSTRAINT ck_recipes_cover_path_name
                CHECK (cover_path IS NULL OR cover_path ~ '^[0-9a-f]{32}\.(jpg|png|webp|gif)$'),
            ADD CONSTRAINT ck_recipes_cover_content_type CHECK (
                cover_content_type IS NULL
                OR cover_content_type IN ('image/jpeg', 'image/png', 'image/webp', 'image/gif')
            ),
            ADD CONSTRAINT ck_recipes_cover_both_or_none
                CHECK ((cover_path IS NULL) = (cover_content_type IS NULL))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE recipes
            DROP CONSTRAINT ck_recipes_cover_both_or_none,
            DROP CONSTRAINT ck_recipes_cover_content_type,
            DROP CONSTRAINT ck_recipes_cover_path_name,
            DROP COLUMN cover_content_type,
            DROP COLUMN cover_path
        """
    )
