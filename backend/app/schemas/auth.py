from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.functional_validators import AfterValidator

from app import security


def _normalize_email(value: str) -> str:
    """Trim and lowercase so email works as a case-insensitive account identifier.

    Applied on both register and login, so storage and lookup always use the same form
    (the users table also enforces it with a CHECK constraint).
    """
    return value.strip().lower()


NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]


class UserRegister(BaseModel):
    email: NormalizedEmail
    password: str

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        error = security.validate_password_strength(value)
        if error:
            raise ValueError(error)
        return value


class UserLogin(BaseModel):
    email: NormalizedEmail
    # No strength rules on login (they may change over time), only a cap against huge inputs.
    password: str = Field(max_length=security.MAX_PASSWORD_LENGTH)


class UserOut(BaseModel):
    """Public view of an account; never exposes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    created_at: datetime
    daily_kcal_goal: int | None
    daily_protein_goal: int | None


class GoalsIn(BaseModel):
    """Daily targets. A field that is left out stays as it is; null clears it."""

    daily_kcal_goal: int | None = Field(None, ge=500, le=10000)
    daily_protein_goal: int | None = Field(None, ge=1, le=1000)
