"""Recipe schema models. DDL lives in migration 0004 (plain SQL); these mirror it so the ORM
can write rows and Alembic autogenerate can detect drift. Reads use SQL files in app/sql.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Unit(Base):
    """Dictionary of units a recipe line can use. Seeded by migration, read-only for the API."""

    __tablename__ = "units"
    __table_args__ = (
        CheckConstraint("kind IN ('mass', 'volume', 'count')", name="kind"),
        CheckConstraint(
            "(kind = 'count') = (base_amount IS NULL) AND (base_amount IS NULL OR base_amount > 0)",
            name="base_amount",
        ),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    # Grams (mass units) or millilitres (volume units) in one unit; NULL for count units, whose
    # weight depends on the product (see UnitConversion).
    base_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))


class Ingredient(Base):
    """A product with nutrition per 100 g. user_id NULL = shared catalog, else a private product."""

    __tablename__ = "ingredients"
    __table_args__ = (
        CheckConstraint("btrim(canonical_name) <> ''", name="name_not_blank"),
        CheckConstraint(
            "kcal_per_100g BETWEEN 0 AND 900 AND protein_per_100g BETWEEN 0 AND 100 "
            "AND fat_per_100g BETWEEN 0 AND 100 AND carbs_per_100g BETWEEN 0 AND 100",
            name="macros_range",
        ),
        CheckConstraint(
            "density_g_per_ml IS NULL OR density_g_per_ml > 0", name="density_positive"
        ),
        CheckConstraint("source IN ('off', 'manual', 'llm_estimate')", name="source"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    canonical_name: Mapped[str] = mapped_column(Text)
    kcal_per_100g: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    protein_per_100g: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    fat_per_100g: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    carbs_per_100g: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    density_g_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index(
    "uq_ingredients_shared_name",
    func.lower(Ingredient.canonical_name),
    unique=True,
    postgresql_where=Ingredient.user_id.is_(None),
)
Index(
    "uq_ingredients_user_name",
    Ingredient.user_id,
    func.lower(Ingredient.canonical_name),
    unique=True,
    postgresql_where=Ingredient.user_id.is_not(None),
)
Index(
    "ix_ingredients_name_trgm",
    Ingredient.canonical_name,
    postgresql_using="gin",
    postgresql_ops={"canonical_name": "gin_trgm_ops"},
)


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_recipes_id_user_id"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint("servings > 0", name="servings_positive"),
        CheckConstraint(
            "(prep_time_min IS NULL OR prep_time_min >= 0) "
            "AND (cook_time_min IS NULL OR cook_time_min >= 0)",
            name="times_non_negative",
        ),
        CheckConstraint(
            "import_method IN ('jsonld', 'microdata', 'llm', 'manual')", name="import_method"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    servings: Mapped[int] = mapped_column(server_default="1")
    image_url: Mapped[str | None] = mapped_column(Text)
    prep_time_min: Mapped[int | None] = mapped_column()
    cook_time_min: Mapped[int | None] = mapped_column()
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # Nutrition as published by the source site (schema.org); kept to compare with our estimate.
    source_nutrition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    import_method: Mapped[str] = mapped_column(Text, server_default="manual")
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Maintained by the trg_recipes_set_updated_at trigger, not by the application.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "uq_recipes_user_source_url",
    Recipe.user_id,
    Recipe.source_url,
    unique=True,
    postgresql_where=Recipe.source_url.is_not(None) & Recipe.deleted_at.is_(None),
)
Index(
    "ix_recipes_user_created",
    Recipe.user_id,
    Recipe.created_at.desc(),
    Recipe.id.desc(),
    postgresql_where=Recipe.deleted_at.is_(None),
)
Index(
    "ix_recipes_title_trgm",
    Recipe.title,
    postgresql_using="gin",
    postgresql_ops={"title": "gin_trgm_ops"},
)
Index("ix_recipes_tags", Recipe.tags, postgresql_using="gin")


class RecipeStep(Base):
    """One instruction. user_id is denormalized from the recipe for RLS (see migration 0004)."""

    __tablename__ = "recipe_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["recipe_id", "user_id"],
            ["recipes.id", "recipes.user_id"],
            name="fk_recipe_steps_recipe_id_recipes",
            ondelete="CASCADE",
        ),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("btrim(instruction) <> ''", name="instruction_not_blank"),
    )

    recipe_id: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column()
    instruction: Mapped[str] = mapped_column(Text)


class RecipeIngredient(Base):
    """One ingredient line: the original text plus the parsed/linked parts (filled over time)."""

    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["recipe_id", "user_id"],
            ["recipes.id", "recipes.user_id"],
            name="fk_recipe_ingredients_recipe_id_recipes",
            ondelete="CASCADE",
        ),
        UniqueConstraint("recipe_id", "position", name="uq_recipe_ingredients_recipe_id_position"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("btrim(raw_text) <> ''", name="raw_text_not_blank"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
        CheckConstraint(
            "grams_manual IS NULL OR grams_manual >= 0", name="grams_manual_non_negative"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    recipe_id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    position: Mapped[int] = mapped_column()
    ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredients.id", ondelete="SET NULL")
    )
    raw_text: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    unit_code: Mapped[str | None] = mapped_column(ForeignKey("units.code"))
    # A weight the user typed in for this line; replaces any computed weight.
    grams_manual: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_optional: Mapped[bool] = mapped_column(server_default=false())


class UnitConversion(Base):
    """Grams per ONE unit of a product (an egg: 55 g), the density of a product (unit 'ml':
    grams per millilitre) or a general default (ingredient_id NULL, e.g. a pinch).
    user_id NULL = shared, otherwise the user's own estimate or correction."""

    __tablename__ = "unit_conversions"
    __table_args__ = (
        CheckConstraint("grams_per_unit > 0", name="grams_positive"),
        CheckConstraint("source IN ('off', 'manual', 'llm_estimate')", name="source"),
        CheckConstraint("user_id IS NULL OR ingredient_id IS NOT NULL", name="own_has_product"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    unit_code: Mapped[str] = mapped_column(ForeignKey("units.code"))
    grams_per_unit: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index(
    "uq_unit_conversions_general",
    UnitConversion.unit_code,
    unique=True,
    postgresql_where=UnitConversion.ingredient_id.is_(None),
)
Index(
    "uq_unit_conversions_shared",
    UnitConversion.ingredient_id,
    UnitConversion.unit_code,
    unique=True,
    postgresql_where=UnitConversion.ingredient_id.is_not(None) & UnitConversion.user_id.is_(None),
)
Index(
    "uq_unit_conversions_user",
    UnitConversion.user_id,
    UnitConversion.ingredient_id,
    UnitConversion.unit_code,
    unique=True,
    postgresql_where=UnitConversion.user_id.is_not(None),
)
