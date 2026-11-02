"""USDA FoodData Central: a new value source and the staging tables

  * 'usda' becomes a valid `source` of products and unit conversions: USDA values are laboratory
    measurements, so they are shown as measured (not as an estimate), like 'off'.
  * usda_* tables hold a raw copy of the USDA data (Foundation Foods + SR Legacy). They are a
    snapshot: the import script empties and refills them with COPY. The shared catalog
    (`ingredients`) is filled from them by a separate, explicit mapping step, so the catalog
    stays small and Polish instead of receiving 8000 English product names.
  * Staging tables belong to the database owner only: `app_user` gets no privileges on them.
  * usda_food_macros: USDA stores nutrients as one row per (food, nutrient); the view turns
    that into one row per food. Energy is taken from nutrient 1008, and when a food has none
    (Foundation Foods usually do not) from the Atwater factors 2047, then 2048.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCES_OLD = "('off', 'manual', 'llm_estimate')"
SOURCES_NEW = "('off', 'usda', 'manual', 'llm_estimate')"

VIEW = """
CREATE VIEW usda_food_macros AS
SELECT
    f.fdc_id,
    f.data_type,
    f.description,
    COALESCE(
        max(n.amount) FILTER (WHERE n.nutrient_id = 1008),
        max(n.amount) FILTER (WHERE n.nutrient_id = 2047),
        max(n.amount) FILTER (WHERE n.nutrient_id = 2048)
    )                                                         AS kcal,
    max(n.amount) FILTER (WHERE n.nutrient_id = 1003)         AS protein,
    max(n.amount) FILTER (WHERE n.nutrient_id = 1004)         AS fat,
    max(n.amount) FILTER (WHERE n.nutrient_id = 1005)         AS carbs
FROM usda_food f
LEFT JOIN usda_food_nutrient n ON n.fdc_id = f.fdc_id
GROUP BY f.fdc_id, f.data_type, f.description
"""


def upgrade() -> None:
    for table in ("ingredients", "unit_conversions"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_source")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_source CHECK (source IN {SOURCES_NEW})"
        )

    op.execute(
        """
        CREATE TABLE usda_food (
            fdc_id integer NOT NULL,
            data_type text NOT NULL,
            description text NOT NULL,
            CONSTRAINT pk_usda_food PRIMARY KEY (fdc_id),
            CONSTRAINT ck_usda_food_data_type
                CHECK (data_type IN ('foundation_food', 'sr_legacy_food'))
        )
        """
    )
    # Names are searched when the catalog is mapped, hence a trigram index (as on ingredients).
    op.execute(
        "CREATE INDEX ix_usda_food_description_trgm "
        "ON usda_food USING gin (description gin_trgm_ops)"
    )
    op.execute(
        """
        CREATE TABLE usda_food_nutrient (
            fdc_id integer NOT NULL,
            nutrient_id integer NOT NULL,
            amount numeric(12, 4) NOT NULL,
            CONSTRAINT pk_usda_food_nutrient PRIMARY KEY (fdc_id, nutrient_id),
            CONSTRAINT fk_usda_food_nutrient_fdc_id_usda_food
                FOREIGN KEY (fdc_id) REFERENCES usda_food (fdc_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE usda_measure_unit (
            id integer NOT NULL,
            name text NOT NULL,
            CONSTRAINT pk_usda_measure_unit PRIMARY KEY (id)
        )
        """
    )
    # What one household measure of a food weighs: 1 cup = 125 g, 1 medium egg = 44 g.
    op.execute(
        """
        CREATE TABLE usda_food_portion (
            id integer NOT NULL,
            fdc_id integer NOT NULL,
            amount numeric(12, 4),
            measure_unit_id integer,
            portion_description text NOT NULL DEFAULT '',
            modifier text NOT NULL DEFAULT '',
            gram_weight numeric(12, 4) NOT NULL,
            CONSTRAINT pk_usda_food_portion PRIMARY KEY (id),
            CONSTRAINT fk_usda_food_portion_fdc_id_usda_food
                FOREIGN KEY (fdc_id) REFERENCES usda_food (fdc_id) ON DELETE CASCADE,
            CONSTRAINT ck_usda_food_portion_gram_weight_positive CHECK (gram_weight > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_usda_food_portion_fdc_id ON usda_food_portion (fdc_id)")

    op.execute(VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW usda_food_macros")
    op.execute("DROP TABLE usda_food_portion, usda_measure_unit, usda_food_nutrient, usda_food")
    # Rows with the new source cannot satisfy the old constraint; remove them first.
    op.execute("DELETE FROM unit_conversions WHERE source = 'usda'")
    op.execute("DELETE FROM ingredients WHERE source = 'usda'")
    for table in ("ingredients", "unit_conversions"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_source")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_source CHECK (source IN {SOURCES_OLD})"
        )
