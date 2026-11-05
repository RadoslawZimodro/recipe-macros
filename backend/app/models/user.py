from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    """An account. The tenant boundary: every user-owned row will carry this id."""

    __tablename__ = "users"
    # The API lowercases emails; this makes Postgres enforce it too, so UNIQUE(email)
    # really is case-insensitive even for rows written outside the API.
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(
            "daily_kcal_goal IS NULL OR daily_kcal_goal BETWEEN 500 AND 10000",
            name="daily_kcal_goal_range",
        ),
        CheckConstraint(
            "daily_protein_goal IS NULL OR daily_protein_goal BETWEEN 1 AND 1000",
            name="daily_protein_goal_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # Argon2id hash produced by app.security, never returned by any API schema.
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Daily targets (NULL = not set); the food log compares its day totals with them.
    daily_kcal_goal: Mapped[int | None]
    daily_protein_goal: Mapped[int | None]


class RefreshToken(Base):
    """One issued refresh token, stored as a sha256 HASH (the raw value is never persisted).

    Rotation: on /auth/refresh the used token is revoked and `replaced_by_id` points at its
    successor, forming a chain. Presenting an already-revoked token means it was replayed
    after rotation (theft), so every active token of that user is revoked.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
