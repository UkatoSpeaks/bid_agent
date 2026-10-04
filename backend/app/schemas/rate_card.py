"""A contractor's rate card: the only source of prices the engine may use."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.bid import ComponentType


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


class ProductionRateComponent(_Strict):
    type: ComponentType
    rate_card_code: str = Field(min_length=1)
    # Amount per ONE bid unit of the production rate, in the rate card
    # entry's own unit (labor in hours).
    quantity_per_unit: Decimal = Field(ge=0)


class ProductionRate(_Strict):
    """The company's standard recipe for one unit of installed work.

    E.g. spiral duct, per LF: 0.18 hr Sheet Metal Worker + 1 LF of duct. This
    is company data: the LLM picks a code, it never supplies the numbers.
    """

    code: str = Field(min_length=1)
    description: str
    unit: str = Field(min_length=1)  # the bid unit the rate is per: "EA", "LF"
    components: list[ProductionRateComponent] = Field(min_length=1)
    notes: str | None = None


class RateCard(_Strict):
    company_name: str
    trade: str
    currency: str
    labor_rates: list[LaborRate]
    materials: list[MaterialRate]
    equipment: list[EquipmentRate]
    markups: Markups
    production_rates: list[ProductionRate] = Field(default_factory=list)
    # Free text on where the production rates come from.
    production_rates_note: str | None = None

    @model_validator(mode="after")
    def _codes_are_unique(self) -> "RateCard":
        # A duplicated code would make lookups ambiguous, so refuse the card.
        for section, entries in (
            ("labor_rates", self.labor_rates),
            ("materials", self.materials),
            ("equipment", self.equipment),
            ("production_rates", self.production_rates),
        ):
            seen: set[str] = set()
            for entry in entries:
                if entry.code in seen:
                    raise ValueError(f"duplicate code '{entry.code}' in {section}")
                seen.add(entry.code)
        return self

    @model_validator(mode="after")
    def _production_rates_use_known_codes(self) -> "RateCard":
        # A production rate pointing at a missing code could never be priced.
        known: dict[str, set[str]] = {
            "labor": {r.code for r in self.labor_rates},
            "material": {m.code for m in self.materials},
            "equipment": {e.code for e in self.equipment},
        }
        for production_rate in self.production_rates:
            for component in production_rate.components:
                if component.rate_card_code not in known[component.type]:
                    raise ValueError(
                        f"production rate '{production_rate.code}' uses "
                        f"{component.type} code '{component.rate_card_code}', "
                        f"which is not a {component.type} entry in the rate card"
                    )
        return self
