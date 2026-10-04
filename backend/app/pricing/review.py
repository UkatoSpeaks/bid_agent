"""Post-pricing review: rank what a reviewer must check by dollar impact.

Runs on a priced Estimate. Like the engine it is a pure function with no I/O,
no randomness and no LLM. It changes no cost: it only adds flags, each line's
share of the subtotal and the review summary.

A line's share of the subtotal
------------------------------
The subtotal contains material markup and sales tax, which exist only at
estimate level, so a line's direct cost is not directly comparable to it. For
the share, each line is given its part of them:

    loaded cost = labor + equipment
                  + material x (1 + markup %) x (1 + sales tax %)
    share       = loaded cost / sum of all loaded costs

The loaded costs add up to the subtotal (to within the cent rounding of markup
and tax), and dividing by their own sum makes the shares add up to exactly
100%. Shares are only used for ranking and reporting, never for pricing.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.schemas import Estimate, Flag, LineFlag, PricedLine, RateCard, ReviewSummary

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TENTH = Decimal("0.1")
DEFAULT_HIGH_IMPACT_PCT = Decimal("15")


def review_estimate(
    estimate: Estimate,
    rate_card: RateCard,
    high_impact_pct: Decimal = DEFAULT_HIGH_IMPACT_PCT,
) -> Estimate:
    """Return a copy of `estimate` with impact flags and a review summary.

    Flags added or changed here:

        * HIGH_IMPACT_LINE (warning): the line is more than `high_impact_pct`
          percent of the subtotal, so it should be checked first.
        * ASSUMED_PRODUCTION_RATE: raised to a blocker on a high-impact line.
          A guessed rate that moves that much of the bid must be confirmed.

    `rate_card` must be the one the estimate was priced with.
    """
    markups = rate_card.markups
    material_factor = (1 + markups.material_markup_pct / HUNDRED) * (
        1 + markups.sales_tax_pct_on_materials / HUNDRED
    )
    loaded = [
        line.labor_cost + line.equipment_cost + line.material_cost * material_factor
        for line in estimate.lines
    ]
    total = sum(loaded, ZERO)

    lines: list[PricedLine] = []
    high_impact_ids: list[str] = []
    standard = ZERO
    for line, cost in zip(estimate.lines, loaded):
        if total == 0:
            lines.append(line.model_copy(update={"subtotal_share_pct": None}))
            continue

        share = cost / total * HUNDRED
        if line.rate_basis == "standard":
            standard += cost
        flags = list(line.flags)
        if share > high_impact_pct:
            high_impact_ids.append(line.id)
            flags = [_upgrade(flag, share) for flag in flags]
            flags.append(
                Flag(
                    severity="warning",
                    code="HIGH_IMPACT_LINE",
                    message=(
                        f"This line is {_pct(share)}% of the subtotal (threshold "
                        f"{_number(high_impact_pct)}%). Check it first."
                    ),
                )
            )
        lines.append(
            line.model_copy(update={"flags": flags, "subtotal_share_pct": _pct(share)})
        )

    all_flags = [
        LineFlag(line_id=line.id, **flag.model_dump()) for line in lines for flag in line.flags
    ]
    counts = {"blocker": 0, "warning": 0, "info": 0}
    for flag in all_flags:
        counts[flag.severity] += 1

    # The two shares are reported so that they add up to exactly 100.
    standard_pct = _pct(standard / total * HUNDRED) if total else ZERO
    assumed_pct = HUNDRED - standard_pct if total else ZERO

    return estimate.model_copy(
        update={
            "lines": lines,
            "all_flags": all_flags,
            "review": ReviewSummary(
                blocker_count=counts["blocker"],
                warning_count=counts["warning"],
                info_count=counts["info"],
                standard_rate_pct=standard_pct,
                assumed_rate_pct=assumed_pct,
                lines_on_standard_rates=_count(lines, "standard"),
                lines_on_assumed_rates=_count(lines, "assumed"),
                lines_not_priced=_count(lines, "none"),
                high_impact_threshold_pct=high_impact_pct,
                high_impact_line_ids=high_impact_ids,
            ),
        }
    )


def _upgrade(flag: Flag, share: Decimal) -> Flag:
    """An ASSUMED_PRODUCTION_RATE warning becomes a blocker on a big line."""
    if flag.code != "ASSUMED_PRODUCTION_RATE" or flag.severity == "blocker":
        return flag
    return flag.model_copy(
        update={
            "severity": "blocker",
            "message": (
                f"{flag.message} Raised to a blocker because this line is "
                f"{_pct(share)}% of the subtotal."
            ),
        }
    )


def _count(lines: list[PricedLine], basis: str) -> int:
    return sum(1 for line in lines if line.rate_basis == basis)


def _pct(value: Decimal) -> Decimal:
    """A percentage to 1 decimal, half up."""
    return value.quantize(TENTH, rounding=ROUND_HALF_UP)


def _number(value: Decimal) -> str:
    return f"{value.normalize():,f}"
