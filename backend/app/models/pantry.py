from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PantryItem(Base):
    """A product the user has at home right now (one row per user and product)."""

    __tablename__ = "pantry_items"
    __table_args__ = (
        UniqueConstraint("user_id", "ingredient_id", name="uq_pantry_items_user_id_ingredient_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StapleIngredient(Base):
    """A product the user ALWAYS has (oil, sugar): it never counts as missing in a recipe."""

    __tablename__ = "staple_ingredients"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "ingredient_id", name="uq_staple_ingredients_user_id_ingredient_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DefaultStaple(Base):
    """Names every user has for free (water, salt, pepper); read-only for the API."""

    __tablename__ = "default_staples"
    __table_args__ = (CheckConstraint("name = lower(btrim(name))", name="name_lowercase"),)

    name: Mapped[str] = mapped_column(Text, primary_key=True)
