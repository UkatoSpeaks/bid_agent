"""Pricing engine output."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.bid import BidLineItem, Confidence, Flag

RateBasis = Literal["standard", "assumed", "none"]
# "open": not yet looked at. "reviewed": the reviewer accepts the line as
# priced. "excluded": the reviewer took the line out of the estimate.
ReviewStatus = Literal["open", "reviewed", "excluded"]


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
    # Where the quantities per unit behind the costs come from: "standard" (a
    # company production rate, named in production_rate_code), "assumed"
    # (proposed by the LLM) or "none" (the line has no components).
    rate_basis: RateBasis = "none"
    production_rate_code: str | None = None
    # This line's share of the estimate subtotal, in percent. Set by
    # review_estimate(); None before the review or when the subtotal is 0.
    subtotal_share_pct: Decimal | None = None
    mapping_confidence: Confidence | None = None
    mapping_rationale: str | None = None
    # Reviewer state, set by apply_reviewer_edits(). An excluded line stays
    # in the list, priced at 0, with the reviewer's reason.
    review_status: ReviewStatus = "open"
    exclusion_reason: str | None = None
    # What the reviewer changed on this line, e.g. ["quantity"].
    reviewer_edits: list[str] = Field(default_factory=list)


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


class ReviewSummary(BaseModel):
    """What a reviewer needs before reading the lines. See pricing/review.py."""

    # Counts of unresolved flags. In a fresh draft that is every flag.
    blocker_count: int
    warning_count: int
    info_count: int
    # True when at least one line is priced and no blocker is unresolved.
    ready_to_approve: bool = False
    # Share of the subtotal (percent, 1 decimal) priced from company standard
    # production rates, and the share resting on rates assumed by the LLM.
    # They add up to 100, or are both 0 when nothing was priced.
    standard_rate_pct: Decimal
    assumed_rate_pct: Decimal
    lines_on_standard_rates: int
    lines_on_assumed_rates: int
    lines_not_priced: int
    # Lines the reviewer took out of the estimate. They are in none of the
    # counts or shares above.
    lines_excluded: int = 0
    high_impact_threshold_pct: Decimal
    high_impact_line_ids: list[str]


class SkippedRow(BaseModel):
    """A row the LLM returned that code recognised as not being a bid item."""

    source_ref: str
    description: str
    reason: str


class Estimate(BaseModel):
    currency: str
    lines: list[PricedLine]
    totals: EstimateTotals
    all_flags: list[LineFlag]
    # Both are filled in after pricing: review by review_estimate(),
    # skipped_rows by the pipeline.
    review: ReviewSummary | None = None
    skipped_rows: list[SkippedRow] = Field(default_factory=list)
    # The lines as extracted and mapped, before pricing and before any
    # reviewer edit. POST /estimates/reprice takes these back unchanged
    # together with the reviewer's edits.
    source_lines: list[BidLineItem] = Field(default_factory=list)
