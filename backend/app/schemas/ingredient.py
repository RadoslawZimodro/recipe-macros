from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


class IngredientPatch(BaseModel):
    """Correct one of your own products. Send only what changes; the result is marked as typed in
    by you (source = manual). density_g_per_ml may be null to clear it."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    kcal_per_100g: Decimal | None = Field(None, ge=0, le=900, max_digits=7, decimal_places=2)
    protein_per_100g: Decimal | None = Field(None, ge=0, le=100, max_digits=5, decimal_places=2)
    fat_per_100g: Decimal | None = Field(None, ge=0, le=100, max_digits=5, decimal_places=2)
    carbs_per_100g: Decimal | None = Field(None, ge=0, le=100, max_digits=5, decimal_places=2)
    density_g_per_ml: Decimal | None = Field(None, gt=0, max_digits=6, decimal_places=3)

    @model_validator(mode="after")
    def _only_density_may_be_cleared(self) -> "IngredientPatch":
        for name in self.model_fields_set - {"density_g_per_ml"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self


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
