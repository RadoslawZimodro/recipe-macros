from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class IngredientIn(BaseModel):
    """A private product (visible only to its creator). Values are per 100 g."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    kcal_per_100g: Decimal = Field(ge=0, le=900, max_digits=7, decimal_places=2)
    protein_per_100g: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    fat_per_100g: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    carbs_per_100g: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    density_g_per_ml: Decimal | None = Field(None, gt=0, max_digits=6, decimal_places=3)


class IngredientOut(BaseModel):
    id: int
    canonical_name: str
    kcal_per_100g: float
    protein_per_100g: float
    fat_per_100g: float
    carbs_per_100g: float
    density_g_per_ml: float | None
    # off | manual | llm_estimate: where the numbers come from (they are estimates).
    source: str
    # True for the shared catalog, False for the user's own products.
    is_shared: bool


class IngredientListOut(BaseModel):
    items: list[IngredientOut]
    total: int
    limit: int
    offset: int


class UnitOut(BaseModel):
    code: str
    kind: str
