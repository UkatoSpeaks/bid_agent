from decimal import Decimal

import pytest

from app.schemas import BidLineItem, LineItemComponent, RateCard


@pytest.fixture
def rate_card() -> RateCard:
    """A small rate card with round percentages so tests can be hand-checked.

    Markups: material markup 10%, sales tax 8%, overhead 10%, profit 10%.
    """
    return RateCard.model_validate(
        {
            "company_name": "Test Mechanical",
            "trade": "HVAC",
            "currency": "USD",
            "labor_rates": [
                {"code": "L-TECH", "role": "HVAC Tech", "hourly_rate": "85.00"},
                {"code": "L-APPR", "role": "Apprentice", "hourly_rate": "48.00"},
            ],
            "materials": [
                {"code": "M-TSTAT", "name": "Thermostat", "unit": "EA", "unit_cost": "145.00"},
                {"code": "M-DUCT", "name": "Spiral duct", "unit": "LF", "unit_cost": "11.50"},
                {"code": "M-SCREW", "name": "Screw", "unit": "EA", "unit_cost": "0.125"},
            ],
            "equipment": [
                {"code": "E-LIFT", "name": "Scissor lift", "unit": "day", "rate": "185.00"},
                {"code": "E-CRANE", "name": "Crane", "unit": "hour", "rate": "245.00"},
            ],
            "markups": {
                "material_markup_pct": "10",
                "overhead_pct": "10",
                "profit_pct": "10",
                "sales_tax_pct_on_materials": "8",
            },
        }
    )


def make_line(
    line_id: str,
    quantity: str,
    components: list[tuple[str, str, str]],
    unit: str = "EA",
) -> BidLineItem:
    """Build a line from (type, rate_card_code, quantity_per_unit) tuples."""
    return BidLineItem(
        id=line_id,
        item_number=line_id,
        description=f"Test line {line_id}",
        quantity=Decimal(quantity),
        unit=unit,
        components=[
            LineItemComponent(type=t, rate_card_code=code, quantity_per_unit=Decimal(q))
            for t, code, q in components
        ],
    )
