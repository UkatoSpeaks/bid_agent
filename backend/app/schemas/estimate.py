"""Pricing engine output."""

from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.bid import Flag


class PricedLine(BaseModel):
    id: str
    item_number: str
    description: str
    quantity: Decimal
    unit: str
    # Direct costs only: markup, tax, overhead and profit are applied at
    # estimate level and appear in EstimateTotals.
    labor_cost: Decimal
    material_cost: Decimal
    equipment_cost: Decimal
    line_subtotal: Decimal
    # Human-readable record of every multiplication behind the costs above.
    calculation_trace: list[str]
    flags: list[Flag]
    source_ref: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class EstimateTotals(BaseModel):
    direct_labor: Decimal
    direct_material: Decimal
    material_markup: Decimal
    sales_tax: Decimal
    direct_equipment: Decimal
    subtotal: Decimal
    overhead: Decimal
    profit: Decimal
    grand_total: Decimal


class LineFlag(Flag):
    """A flag with the id of the line it belongs to."""

    line_id: str


class Estimate(BaseModel):
    currency: str
    lines: list[PricedLine]
    totals: EstimateTotals
    all_flags: list[LineFlag]
