"""nutrition: unit conversions and the recipe_line_nutrition view

  * units.base_amount: how many grams (mass units) or millilitres (volume units) one unit is;
    count units (piece, clove, ...) have no base amount: their weight depends on the product.
  * unit_conversions: grams per ONE unit for a product (an egg weighs 55 g, a clove of garlic
    5 g), the density of a product ('ml' row: grams per millilitre), or a general default
    (a pinch). user_id NULL = shared, otherwise a user's own estimate or correction.
  * recipe_ingredients.grams_manual: a weight the user typed in for one line. It replaces
    the never-used grams_estimated column: weights are now computed live by the view.
  * recipe_line_nutrition: for every ingredient line, the grams and the nutrition it
    contributes, how the weight was found, whether any part of it is an estimate and what is
    missing when it cannot be computed. WITH (security_invoker) makes it run with the
    caller's rights, so Row-Level Security still applies; a plain view would run as its owner
    and show every user's recipes.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEW = """
CREATE VIEW recipe_line_nutrition WITH (security_invoker = true) AS
SELECT
    ri.id                  AS line_id,
    ri.recipe_id,
    ri.position,
    ri.raw_text,
    ri.is_optional,
    ri.quantity,
    ri.unit_code,
    p.id                   AS product_id,
    p.canonical_name       AS product_name,
    p.source               AS macro_source,
    w.grams,
    w.weight_source,
    -- a line is an estimate if its weight basis OR its nutrition values come from the AI
    (COALESCE(w.weight_is_estimate, false)
     OR COALESCE(p.source = 'llm_estimate', false)) AS is_estimate,
    p.kcal_per_100g    * w.grams / 100 AS kcal,
    p.protein_per_100g * w.grams / 100 AS protein,
    p.fat_per_100g     * w.grams / 100 AS fat,
    p.carbs_per_100g   * w.grams / 100 AS carbs,
    CASE
        WHEN w.grams IS NULL THEN w.problem
        WHEN p.id IS NULL    THEN 'no_product'
    END                    AS problem
FROM recipe_ingredients ri
LEFT JOIN ingredients linked ON linked.id = ri.ingredient_id
LEFT JOIN units u            ON u.code = ri.unit_code
-- The product actually used. Among the visible products with the linked product's name:
-- the user's own manual entry first, then a shared (measured) one, then the user's own AI
-- estimate. This is how old recipes improve by themselves when the shared catalog grows.
LEFT JOIN LATERAL (
    SELECT c.*
    FROM ingredients c
    WHERE c.id = linked.id OR lower(c.canonical_name) = lower(linked.canonical_name)
    ORDER BY CASE WHEN c.user_id IS NOT NULL AND c.source = 'manual' THEN 0
                  WHEN c.user_id IS NULL THEN 1
                  ELSE 2 END,
             c.id
    LIMIT 1
) p ON true
-- Grams per one unit of the line's unit (count units such as piece or clove).
-- Product-specific beats general; the user's own beats a shared one.
LEFT JOIN LATERAL (
    SELECT uc.grams_per_unit, uc.ingredient_id, uc.source
    FROM unit_conversions uc
    WHERE uc.unit_code = ri.unit_code
      AND (uc.ingredient_id IN (p.id, linked.id) OR uc.ingredient_id IS NULL)
    ORDER BY (uc.ingredient_id IS NOT NULL) DESC, (uc.user_id IS NOT NULL) DESC
    LIMIT 1
) cu ON u.kind = 'count'
-- Density (grams per millilitre) of the product, stored as the 'ml' conversion.
LEFT JOIN LATERAL (
    SELECT uc.grams_per_unit, uc.source
    FROM unit_conversions uc
    WHERE uc.unit_code = 'ml' AND uc.ingredient_id IN (p.id, linked.id)
    ORDER BY (uc.user_id IS NOT NULL) DESC
    LIMIT 1
) cd ON u.kind = 'volume'
CROSS JOIN LATERAL (
    SELECT
        CASE
            WHEN ri.grams_manual IS NOT NULL THEN ri.grams_manual
            WHEN ri.quantity IS NULL THEN NULL
            WHEN u.kind = 'mass'   THEN ri.quantity * u.base_amount
            WHEN u.kind = 'volume' THEN ri.quantity * u.base_amount
                                        * COALESCE(cd.grams_per_unit, p.density_g_per_ml)
            WHEN u.kind = 'count'  THEN ri.quantity * cu.grams_per_unit
        END AS grams,
        CASE
            WHEN ri.grams_manual IS NOT NULL THEN 'manual'
            WHEN ri.quantity IS NULL THEN NULL
            WHEN u.kind = 'mass' THEN 'unit'
            WHEN u.kind = 'volume' AND COALESCE(cd.grams_per_unit, p.density_g_per_ml) IS NOT NULL
                THEN 'density'
            WHEN u.kind = 'count' AND cu.grams_per_unit IS NOT NULL
                THEN CASE WHEN cu.ingredient_id IS NULL THEN 'default' ELSE 'unit_weight' END
        END AS weight_source,
        CASE
            WHEN ri.grams_manual IS NOT NULL OR u.kind = 'mass' THEN false
            WHEN u.kind = 'volume' THEN COALESCE(cd.source, p.source) = 'llm_estimate'
            WHEN u.kind = 'count'  THEN cu.source = 'llm_estimate'
        END AS weight_is_estimate,
        CASE
            WHEN ri.quantity IS NULL THEN 'no_quantity'
            WHEN ri.unit_code IS NULL THEN 'no_unit'
            WHEN u.kind = 'volume' THEN CASE WHEN p.id IS NULL THEN 'no_product'
                                             ELSE 'no_density' END
            WHEN u.kind = 'count'  THEN CASE WHEN p.id IS NULL AND cu.grams_per_unit IS NULL
                                             THEN 'no_product' ELSE 'no_unit_weight' END
        END AS problem
) w
"""


def upgrade() -> None:
    # --- units: how big is one unit ---
    op.execute("ALTER TABLE units ADD COLUMN base_amount numeric(10, 3)")
    op.execute(
        """
        UPDATE units SET base_amount = CASE code
            WHEN 'g' THEN 1 WHEN 'kg' THEN 1000
            WHEN 'ml' THEN 1 WHEN 'l' THEN 1000
            WHEN 'tsp' THEN 5 WHEN 'tbsp' THEN 15 WHEN 'cup' THEN 250
        END
        """
    )
    op.execute(
        "ALTER TABLE units ADD CONSTRAINT ck_units_base_amount "
        "CHECK ((kind = 'count') = (base_amount IS NULL) "
        "AND (base_amount IS NULL OR base_amount > 0))"
    )

    # --- unit_conversions ---
    op.execute(
        """
        CREATE TABLE unit_conversions (
            id integer GENERATED BY DEFAULT AS IDENTITY,
            ingredient_id integer,
            user_id integer,
            unit_code text NOT NULL,
            grams_per_unit numeric(10, 4) NOT NULL,
            source text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_unit_conversions PRIMARY KEY (id),
            CONSTRAINT fk_unit_conversions_ingredient_id_ingredients
                FOREIGN KEY (ingredient_id) REFERENCES ingredients (id) ON DELETE CASCADE,
            CONSTRAINT fk_unit_conversions_user_id_users
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT fk_unit_conversions_unit_code_units
                FOREIGN KEY (unit_code) REFERENCES units (code),
            CONSTRAINT ck_unit_conversions_grams_positive CHECK (grams_per_unit > 0),
            CONSTRAINT ck_unit_conversions_source
                CHECK (source IN ('off', 'manual', 'llm_estimate')),
            -- a user's own row always refers to a product; only shared rows may be general
            CONSTRAINT ck_unit_conversions_own_has_product
                CHECK (user_id IS NULL OR ingredient_id IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_unit_conversions_general ON unit_conversions (unit_code) "
        "WHERE ingredient_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_unit_conversions_shared "
        "ON unit_conversions (ingredient_id, unit_code) "
        "WHERE ingredient_id IS NOT NULL AND user_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_unit_conversions_user "
        "ON unit_conversions (user_id, ingredient_id, unit_code) WHERE user_id IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_unit_conversions_ingredient_id ON unit_conversions (ingredient_id)")
    op.execute("ALTER TABLE unit_conversions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY unit_conversions_read ON unit_conversions FOR SELECT "
        "USING (user_id IS NULL OR user_id = app_current_user_id())"
    )
    op.execute(
        "CREATE POLICY unit_conversions_write_own ON unit_conversions FOR ALL "
        "USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id())"
    )
    # A pinch of anything is about half a gram.
    op.execute(
        "INSERT INTO unit_conversions (unit_code, grams_per_unit, source) "
        "VALUES ('pinch', 0.5, 'manual')"
    )

    # --- recipe lines: a manual weight replaces the unused grams_estimated column ---
    op.execute("ALTER TABLE recipe_ingredients DROP COLUMN grams_estimated")
    op.execute(
        "ALTER TABLE recipe_ingredients ADD COLUMN grams_manual numeric(10, 2) "
        "CONSTRAINT ck_recipe_ingredients_grams_manual_non_negative "
        "CHECK (grams_manual IS NULL OR grams_manual >= 0)"
    )

    op.execute(VIEW)

    # --- privileges (least privilege, as before) ---
    op.execute("GRANT SELECT, INSERT, UPDATE ON unit_conversions TO app_user")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE unit_conversions_id_seq TO app_user")
    op.execute("GRANT UPDATE ON ingredients, recipe_ingredients TO app_user")
    op.execute("GRANT SELECT ON recipe_line_nutrition TO app_user")


def downgrade() -> None:
    op.execute("DROP VIEW recipe_line_nutrition")
    op.execute("REVOKE UPDATE ON ingredients, recipe_ingredients FROM app_user")
    op.execute("ALTER TABLE recipe_ingredients DROP COLUMN grams_manual")
    op.execute("ALTER TABLE recipe_ingredients ADD COLUMN grams_estimated numeric(10, 2)")
    op.execute(
        "ALTER TABLE recipe_ingredients ADD CONSTRAINT ck_recipe_ingredients_grams_non_negative "
        "CHECK (grams_estimated IS NULL OR grams_estimated >= 0)"
    )
    op.execute("DROP TABLE unit_conversions")
    op.execute("ALTER TABLE units DROP CONSTRAINT ck_units_base_amount")
    op.execute("ALTER TABLE units DROP COLUMN base_amount")
