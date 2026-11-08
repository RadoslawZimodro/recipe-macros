"""recipe step images: a local copy of the picture of a step

Two nullable columns on recipe_steps (a step has at most one picture), so the existing
Row-Level Security policy and the composite FK to the recipe cover them with no new table.
`image_path` is only a generated file name inside MEDIA_DIR (never a path or a URL), and the
CHECK constraints keep it that way even if a bug tried to store something else.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE recipe_steps
            ADD COLUMN image_path text,
            ADD COLUMN image_content_type text,
            ADD CONSTRAINT ck_recipe_steps_image_path_name
                CHECK (image_path IS NULL OR image_path ~ '^[0-9a-f]{32}\.(jpg|png|webp|gif)$'),
            ADD CONSTRAINT ck_recipe_steps_image_content_type CHECK (
                image_content_type IS NULL
                OR image_content_type IN ('image/jpeg', 'image/png', 'image/webp', 'image/gif')
            ),
            ADD CONSTRAINT ck_recipe_steps_image_both_or_none
                CHECK ((image_path IS NULL) = (image_content_type IS NULL))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE recipe_steps
            DROP CONSTRAINT ck_recipe_steps_image_both_or_none,
            DROP CONSTRAINT ck_recipe_steps_image_content_type,
            DROP CONSTRAINT ck_recipe_steps_image_path_name,
            DROP COLUMN image_content_type,
            DROP COLUMN image_path
        """
    )
