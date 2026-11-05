from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FoodLog(Base):
    """One thing eaten: servings of a recipe OR grams of a product (the CHECK allows exactly one
    kind). No macros are stored; they are computed from the current data on every read (see the
    food_log_nutrition view in migration 0008)."""

    __tablename__ = "food_logs"
    __table_args__ = (
        CheckConstraint(
            "(recipe_id IS NOT NULL AND servings IS NOT NULL "
            "AND ingredient_id IS NULL AND grams IS NULL) "
            "OR (ingredient_id IS NOT NULL AND grams IS NOT NULL "
            "AND recipe_id IS NULL AND servings IS NULL)",
            name="exactly_one_source",
        ),
        CheckConstraint("servings IS NULL OR servings > 0", name="servings_positive"),
        CheckConstraint("grams IS NULL OR grams > 0", name="grams_positive"),
        Index("ix_food_logs_user_id_logged_at", "user_id", "logged_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"))
    servings: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id"))
    grams: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
