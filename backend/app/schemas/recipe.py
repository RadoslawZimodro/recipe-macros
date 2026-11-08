from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

_http_url = TypeAdapter(AnyHttpUrl)


def _clean_text(value: Any) -> Any:
    """Trim strings; a blank string means 'not provided' (None)."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _clean_url(value: Any) -> Any:
    """Accept only http(s) URLs (links are rendered in the UI, so javascript: etc. is refused)."""
    value = _clean_text(value)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("URL must be a string of at most 2048 characters")
    _http_url.validate_python(value)  # raises for non-http(s) schemes and malformed URLs
    return value  # keep the text as the user typed it


OptionalUrl = Annotated[str | None, BeforeValidator(_clean_url)]
OptionalText = Annotated[
    Annotated[str, StringConstraints(max_length=5000)] | None, BeforeValidator(_clean_text)
]
Tag = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=50)
]


# --- input ---
class StepIn(BaseModel):
    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
    ]


class IngredientLineIn(BaseModel):
    raw_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    quantity: Decimal | None = Field(None, ge=0, max_digits=10, decimal_places=3)
    unit: Annotated[
        Annotated[str, StringConstraints(max_length=20)] | None, BeforeValidator(_clean_text)
    ] = None
    ingredient_id: int | None = Field(None, ge=1)
    is_optional: bool = False
    # A weight typed in by the user; it replaces the computed weight of this line.
    grams: Decimal | None = Field(None, ge=0, max_digits=10, decimal_places=2)


class LinePatch(BaseModel):
    """Correct one ingredient line. Send only what changes; null clears the value."""

    model_config = ConfigDict(extra="forbid")

    grams: Decimal | None = Field(None, ge=0, max_digits=10, decimal_places=2)
    ingredient_id: int | None = Field(None, ge=1)


class RecipeIn(BaseModel):
    """Full recipe body for POST and PUT. Position of steps/lines is their order in the list."""

    # Unknown fields (e.g. user_id) are rejected instead of silently ignored.
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    description: OptionalText = None
    source_url: OptionalUrl = None
    image_url: OptionalUrl = None
    servings: int = Field(1, ge=1, le=1000)
    prep_time_min: int | None = Field(None, ge=0, le=100_000)
    cook_time_min: int | None = Field(None, ge=0, le=100_000)
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    steps: list[StepIn] = Field(default_factory=list, max_length=100)
    ingredients: list[IngredientLineIn] = Field(default_factory=list, max_length=200)

    @field_validator("tags")
    @classmethod
    def _dedupe_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))  # drop duplicates, keep order


# --- output ---
class StepOut(BaseModel):
    position: int
    instruction: str
    # Relative address of the saved picture (served by our API), or null. Output only.
    image_url: str | None = None


class IngredientLineOut(BaseModel):
    id: int
    position: int
    raw_text: str
    quantity: float | None
    unit: str | None
    is_optional: bool
    grams: float | None  # the manually entered weight, if any
    ingredient_id: int | None
    ingredient_name: str | None


class RecipeSummary(BaseModel):
    id: int
    title: str
    description: str | None
    image_url: str | None
    servings: int
    tags: list[str]
    prep_time_min: int | None
    cook_time_min: int | None
    source_url: str | None
    import_method: str
    created_at: datetime
    updated_at: datetime


class RecipeOut(RecipeSummary):
    source_nutrition: dict[str, Any] | None
    imported_at: datetime | None
    steps: list[StepOut]
    ingredients: list[IngredientLineOut]


class RecipeListOut(BaseModel):
    items: list[RecipeSummary]
    total: int
    limit: int
    offset: int


# --- import ---
class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: Annotated[str, StringConstraints(max_length=2048)]
    # Fetch the page again and overwrite the saved recipe (manual edits are lost).
    refresh: bool = False


class RecipeImportOut(BaseModel):
    # created: new recipe; existing: already saved, nothing fetched; refreshed: overwritten
    status: Literal["created", "existing", "refreshed"]
    recipe: RecipeOut
    # True when the AI shaped the recipe (parsed ingredients, tidied steps). False when it was
    # not needed (the recipe already existed) or not available; `notice` then explains why.
    ai_used: bool = False
    notice: str | None = None
