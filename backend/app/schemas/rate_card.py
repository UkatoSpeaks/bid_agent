"""A contractor's rate card: the only source of prices the engine may use."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    # Reject unknown keys so a typo in a rate card file fails loudly.
    model_config = ConfigDict(extra="forbid")


class LaborRate(_Strict):
    code: str = Field(min_length=1)
    role: str
    hourly_rate: Decimal = Field(ge=0)


class MaterialRate(_Strict):
    code: str = Field(min_length=1)
    name: str
    unit: str
    unit_cost: Decimal = Field(ge=0)


class EquipmentRate(_Strict):
    code: str = Field(min_length=1)
    name: str
    unit: Literal["day", "hour"]
    rate: Decimal = Field(ge=0)


class Markups(_Strict):
    """Percentages are expressed as percent, not fractions: 15 means 15%."""

    material_markup_pct: Decimal = Field(ge=0)
    overhead_pct: Decimal = Field(ge=0)
    profit_pct: Decimal = Field(ge=0)
    sales_tax_pct_on_materials: Decimal = Field(ge=0)


class RateCard(_Strict):
    company_name: str
    trade: str
    currency: str
    labor_rates: list[LaborRate]
    materials: list[MaterialRate]
    equipment: list[EquipmentRate]
    markups: Markups

    @model_validator(mode="after")
    def _codes_are_unique(self) -> "RateCard":
        # A duplicated code would make lookups ambiguous, so refuse the card.
        for section, entries in (
            ("labor_rates", self.labor_rates),
            ("materials", self.materials),
            ("equipment", self.equipment),
        ):
            seen: set[str] = set()
            for entry in entries:
                if entry.code in seen:
                    raise ValueError(f"duplicate code '{entry.code}' in {section}")
                seen.add(entry.code)
        return self
