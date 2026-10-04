from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.config import BACKEND_DIR
from app.llm import LLMClient
from app.pricing import load_rate_card
from app.schemas import BidLineItem, LineItemComponent, RateCard

BIDS_DIR = BACKEND_DIR / "data" / "bids"


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


class FakeLLMClient(LLMClient):
    """Returns canned responses per schema and records every prompt.

    `responses` maps a schema class to a list of replies, handed out in call
    order. A reply is a dict (validated against the schema), or a callable
    taking the prompt and returning a dict.
    """

    def __init__(self, responses: dict[type[BaseModel], list]) -> None:
        self._responses = {schema: list(replies) for schema, replies in responses.items()}
        self.calls: list[tuple[type[BaseModel], str]] = []

    def structured(self, prompt, schema):
        self.calls.append((schema, prompt))
        replies = self._responses.get(schema)
        assert replies, f"FakeLLMClient has no reply left for {schema.__name__}"
        reply = replies.pop(0)
        if callable(reply):
            reply = reply(prompt)
        return schema.model_validate(reply)


@pytest.fixture
def sample_rate_card() -> RateCard:
    """The real Northline Mechanical sample rate card."""
    return load_rate_card(BACKEND_DIR / "data" / "rate_cards" / "hvac_rate_card.json")
