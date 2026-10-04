"""Reviewer edits: apply an estimator's changes to the draft lines and reprice.

Like the engine, this is pure code with no I/O, no randomness and no LLM. The
edits are always applied to the lines as they were drafted (`Estimate.source_lines`),
never to an already edited estimate, so the same lines and edits always give
the same result and removing an edit restores the draft.

What a reviewer can do to a line
--------------------------------
    * Set the quantity. The quantity checks made against the document
      (QUANTITY_NOT_NUMERIC, QUANTITY_NOT_IN_SOURCE) no longer apply to a
      number the reviewer typed, so those flags are removed.
    * Choose a production rate from the rate card. The line's components are
      replaced by that rate's, and the flags about the LLM's mapping are
      removed. The unit is checked again (UNIT_MISMATCH).
    * Mark it "reviewed": the reviewer accepts the line as priced. That
      resolves its warnings, its info flags and the blockers that only ask
      for a confirmation (CONFIRMABLE_BLOCKERS). A blocker that means the
      line could not be priced properly stays open until the line is fixed
      or excluded.
    * Exclude it, with a reason. The line stays in the list, priced at 0,
      and all of its flags are resolved.

Resolved flags stay on the line (`Flag.resolved`) but are not counted in the
review summary and do not block approval.
"""

from decimal import Decimal

from pydantic import BaseModel

from app.extraction.map import expand_production_rate, unit_mismatch_flag
from app.pricing.engine import price_estimate
from app.pricing.review import (
    DEFAULT_HIGH_IMPACT_PCT,
    collect_flags,
    count_open_flags,
    is_ready_to_approve,
    review_estimate,
)
from app.schemas import BidLineItem, Estimate, Flag, PricedLine, RateCard, ReviewStatus
from app.units import units_match

ZERO = Decimal("0")

# Blockers that ask the reviewer to confirm something. Marking the line
# reviewed is that confirmation. Every other blocker means the line is not
# priced properly and must be fixed or excluded.
CONFIRMABLE_BLOCKERS = frozenset(
    {"ASSUMED_PRODUCTION_RATE", "QUANTITY_NOT_IN_SOURCE", "UNKNOWN_SOURCE_REF"}
)
# Flags about the quantity the LLM extracted. Dropped when the reviewer
# supplies the quantity.
QUANTITY_FLAGS = frozenset({"QUANTITY_NOT_NUMERIC", "QUANTITY_NOT_IN_SOURCE"})
# Flags about the LLM's mapping. Dropped when the reviewer chooses the rate.
MAPPING_FLAGS = frozenset(
    {
        "UNKNOWN_PRODUCTION_RATE",
        "UNIT_MISMATCH",
        "ASSUMED_PRODUCTION_RATE",
        "UNKNOWN_RATE_CODE",
        "INVALID_QUANTITY_PER_UNIT",
        "LOW_CONFIDENCE_MAPPING",
        "NO_RATE_CARD_MATCH",
        "PROPOSED_COMPONENTS_IGNORED",
        "MAPPING_MISSING",
        "STANDARD_RATE_DECLINED",
    }
)


class LineEdit(BaseModel):
    """Everything a reviewer has changed on one line. Unset fields keep the draft."""

    line_id: str
    quantity: Decimal | None = None
    production_rate_code: str | None = None
    status: ReviewStatus = "open"
    # Required when status is "excluded".
    exclusion_reason: str | None = None


class ReviewerEditError(ValueError):
    """An edit that cannot be applied, e.g. it names a line that does not exist."""


def apply_reviewer_edits(
    lines: list[BidLineItem],
    edits: list[LineEdit],
    rate_card: RateCard,
    high_impact_pct: Decimal = DEFAULT_HIGH_IMPACT_PCT,
) -> Estimate:
    """Price `lines` with the reviewer's `edits` applied and review the result.

    `lines` are the draft's source lines. Excluded lines are left out of the
    pricing and of every share and total, and come back priced at 0.
    Raises ReviewerEditError for an edit that cannot be applied.
    """
    by_line_id = _index_edits(lines, edits, rate_card)

    edited: list[BidLineItem] = []
    changed: dict[str, list[str]] = {}
    for line in lines:
        edit = by_line_id.get(line.id)
        if edit is None:
            edited.append(line)
            continue
        line, changes = _edit_line(line, edit, rate_card)
        edited.append(line)
        changed[line.id] = changes

    included = [line for line in edited if _status(by_line_id, line.id) != "excluded"]
    estimate = review_estimate(price_estimate(included, rate_card), rate_card, high_impact_pct)
    priced = {line.id: line for line in estimate.lines}

    result: list[PricedLine] = []
    for line in edited:
        status = _status(by_line_id, line.id)
        if status == "excluded":
            result.append(
                _excluded_line(line, by_line_id[line.id].exclusion_reason or "", changed[line.id])
            )
            continue
        priced_line = priced[line.id]
        result.append(
            priced_line.model_copy(
                update={
                    "review_status": status,
                    "reviewer_edits": changed.get(line.id, []),
                    "flags": (
                        [_resolve_on_review(flag) for flag in priced_line.flags]
                        if status == "reviewed"
                        else priced_line.flags
                    ),
                }
            )
        )

    all_flags = collect_flags(result)
    counts = count_open_flags(all_flags)
    return estimate.model_copy(
        update={
            "lines": result,
            "all_flags": all_flags,
            "review": estimate.review.model_copy(
                update={
                    "blocker_count": counts["blocker"],
                    "warning_count": counts["warning"],
                    "info_count": counts["info"],
                    "ready_to_approve": is_ready_to_approve(result, counts),
                    "lines_excluded": len(edited) - len(included),
                }
            ),
            "source_lines": lines,
        }
    )


def _index_edits(
    lines: list[BidLineItem], edits: list[LineEdit], rate_card: RateCard
) -> dict[str, LineEdit]:
    line_ids = {line.id for line in lines}
    rate_codes = {rate.code for rate in rate_card.production_rates}
    by_line_id: dict[str, LineEdit] = {}
    for edit in edits:
        if edit.line_id not in line_ids:
            raise ReviewerEditError(f"Edit for unknown line '{edit.line_id}'.")
        if edit.line_id in by_line_id:
            raise ReviewerEditError(f"More than one edit for line '{edit.line_id}'.")
        if edit.production_rate_code is not None and edit.production_rate_code not in rate_codes:
            raise ReviewerEditError(
                f"Line '{edit.line_id}': production rate '{edit.production_rate_code}' "
                "is not in the rate card."
            )
        if edit.status == "excluded" and not (edit.exclusion_reason or "").strip():
            raise ReviewerEditError(
                f"Line '{edit.line_id}': a reason is required to exclude a line."
            )
        by_line_id[edit.line_id] = edit
    return by_line_id


def _status(by_line_id: dict[str, LineEdit], line_id: str) -> ReviewStatus:
    edit = by_line_id.get(line_id)
    return edit.status if edit else "open"


def _edit_line(
    line: BidLineItem, edit: LineEdit, rate_card: RateCard
) -> tuple[BidLineItem, list[str]]:
    """The line with the edit's quantity and production rate applied, and what changed."""
    update: dict = {}
    flags = list(line.flags)
    assumptions = list(line.assumptions)
    changes: list[str] = []

    if edit.production_rate_code is not None:
        production_rate = next(
            rate for rate in rate_card.production_rates if rate.code == edit.production_rate_code
        )
        if line.production_rate_code:
            previous = f"the draft used {line.production_rate_code}"
        elif line.components:
            previous = "the draft used quantities assumed by the LLM"
        else:
            previous = "the draft had no mapping"
        flags = [flag for flag in flags if flag.code not in MAPPING_FLAGS]
        assumptions = [
            f"Standard production rate {production_rate.code} "
            f"({production_rate.description}), per {production_rate.unit} "
            f"[chosen by the reviewer; {previous}]"
        ]
        components = []
        if units_match(line.unit, production_rate.unit):
            components, component_assumptions = expand_production_rate(production_rate, rate_card)
            assumptions.extend(component_assumptions)
        else:
            flags.append(unit_mismatch_flag(line, production_rate))
        update["components"] = components
        update["production_rate_code"] = production_rate.code
        changes.append("production_rate")

    if edit.quantity is not None:
        flags = [flag for flag in flags if flag.code not in QUANTITY_FLAGS]
        assumptions.append(
            f"Quantity {_number(edit.quantity)} {line.unit} set by the reviewer "
            f"(the draft had {_number(line.quantity)})."
        )
        update["quantity"] = edit.quantity
        changes.append("quantity")

    update["flags"] = flags
    update["assumptions"] = assumptions
    return line.model_copy(update=update), changes


def _resolve_on_review(flag: Flag) -> Flag:
    if flag.severity == "blocker" and flag.code not in CONFIRMABLE_BLOCKERS:
        return flag
    return flag.model_copy(update={"resolved": True})


def _excluded_line(line: BidLineItem, reason: str, changes: list[str]) -> PricedLine:
    reason = reason.strip()
    if not line.components:
        rate_basis = "none"
    else:
        rate_basis = "standard" if line.production_rate_code else "assumed"
    return PricedLine(
        id=line.id,
        item_number=line.item_number,
        description=line.description,
        quantity=line.quantity,
        unit=line.unit,
        labor_cost=ZERO,
        material_cost=ZERO,
        equipment_cost=ZERO,
        line_subtotal=ZERO,
        calculation_trace=[f"Not priced: excluded by the reviewer ({reason})"],
        flags=[flag.model_copy(update={"resolved": True}) for flag in line.flags],
        source_ref=line.source_ref,
        assumptions=list(line.assumptions),
        rate_basis=rate_basis,
        production_rate_code=line.production_rate_code,
        mapping_confidence=line.mapping_confidence,
        mapping_rationale=line.mapping_rationale,
        review_status="excluded",
        exclusion_reason=reason,
        reviewer_edits=changes,
    )


def _number(value: Decimal) -> str:
    return f"{value.normalize():,f}"
