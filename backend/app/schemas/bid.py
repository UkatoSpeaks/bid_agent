"""Bid schedule line items, after extraction and mapping to rate card codes."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "blocker"]
ComponentType = Literal["labor", "material", "equipment"]


class Flag(BaseModel):
    """Something a human estimator should look at, e.g. UNKNOWN_RATE_CODE."""

    severity: Severity
    code: str
    message: str


class LineItemComponent(BaseModel):
    """One cost component of a bid line."""

    type: ComponentType
    rate_card_code: str
    # Amount of this component per one unit of the bid line,
    # e.g. 2.5 labor hours per unit installed.
    quantity_per_unit: Decimal = Field(ge=0)


class BidLineItem(BaseModel):
    id: str
    item_number: str  # as written in the bid schedule
    description: str
    # Not constrained here: the pricing engine flags zero/negative quantities
    # so a bad line shows up in the estimate instead of failing validation.
    quantity: Decimal
    unit: str
    components: list[LineItemComponent] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
