"""Bid schedule line items, after extraction and mapping to rate card codes."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "blocker"]
ComponentType = Literal["labor", "material", "equipment"]
Confidence = Literal["high", "medium", "low"]


class Flag(BaseModel):
    """Something a human estimator should look at, e.g. UNKNOWN_RATE_CODE."""

    severity: Severity
    code: str
    message: str
    # Set on STANDARD_RATE_DECLINED: the company production rate the reviewer
    # can apply instead of the LLM's own numbers.
    suggested_production_rate_code: str | None = None
    # True once a reviewer has dealt with the flag (see pricing/reviewer.py).
    # Resolved flags stay on the line but no longer count or block approval.
    resolved: bool = False


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
    # Where the line came from in the bid document, e.g. "p2-t1-r4".
    source_ref: str | None = None
    # The company production rate the components were expanded from. None
    # means the components (if any) are not a company standard: their
    # quantities per unit were proposed by the LLM.
    production_rate_code: str | None = None
    # Mapping assumptions (one per component, e.g. labor hours per unit) for
    # the reviewer. Display only: the engine copies them through untouched.
    assumptions: list[str] = Field(default_factory=list)
    # The LLM's confidence in, and one-line reason for, its mapping of this
    # line. None if it returned no mapping or a reviewer chose the rate.
    mapping_confidence: Confidence | None = None
    mapping_rationale: str | None = None
