"""Deterministic pricing engine.

This module does all of the arithmetic for an estimate. It performs no I/O,
uses no randomness and makes no LLM calls: the same input always produces the
same output.

Order of operations
-------------------
Per line, for each component found in the rate card:

    component cost = line quantity x quantity_per_unit x rate

Component costs are summed per type into the line's labor, material and
equipment costs. These are direct costs; nothing is marked up at line level.

Across the estimate:

    1. direct_labor / direct_material / direct_equipment = sum of line costs
    2. material_markup = round(direct_material x material_markup_pct)
    3. sales_tax       = round((direct_material + material_markup)
                               x sales_tax_pct_on_materials)
       (tax is charged on the marked-up material price)
    4. subtotal        = direct_labor
                         + direct_material + material_markup + sales_tax
                         + direct_equipment
    5. overhead        = round(subtotal x overhead_pct)
    6. profit          = round((subtotal + overhead) x profit_pct)
    7. grand_total     = subtotal + overhead + profit

Labor and equipment carry no markup or tax of their own; they only pick up
overhead and profit.

Rounding
--------
Money is rounded to 2 decimals with ROUND_HALF_UP (0.125 -> 0.13). Every
displayed figure is rounded before it is added to another, so every displayed
sum foots to the cent:

    * Line level: a line's labor, material and equipment costs are each
      rounded once, after summing that line's unrounded component costs.
      line_subtotal is the sum of those three rounded figures, and the direct
      totals are sums of the rounded line costs, so lines always add up to
      the direct totals exactly.
    * Markup and tax are each rounded once, and subtotal is the sum of the
      five displayed categories: direct labor + direct material + material
      markup + sales tax + direct equipment.
    * Overhead and profit are each rounded once, and grand_total is the sum
      of the three displayed figures: subtotal + overhead + profit.

Within a percentage chain the input to the next step stays unrounded: tax is
calculated on direct material plus the unrounded markup, and profit on
subtotal plus the unrounded overhead, so half-cent errors do not compound.

The trade-off is that subtotal and grand_total can each differ by a cent from
a calculation carried at full precision from end to end. Adding up exactly as
displayed is worth more to a reviewer than that cent.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from app.schemas import (
    BidLineItem,
    ComponentType,
    Estimate,
    EstimateTotals,
    Flag,
    LineFlag,
    PricedLine,
    RateBasis,
    RateCard,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


class _Rate(NamedTuple):
    name: str
    rate: Decimal
    quantity_unit: str  # how the component quantity reads in the trace: "hrs"
    rate_unit: str  # how the rate reads in the trace: "/hr"


_RateIndex = dict[ComponentType, dict[str, _Rate]]


def round_money(amount: Decimal) -> Decimal:
    """Round to 2 decimals, half up. See the module docstring for where."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def price_estimate(lines: list[BidLineItem], rate_card: RateCard) -> Estimate:
    """Price bid lines against a rate card.

    Pure function: inputs are not modified. The order of operations and the
    rounding policy are documented in the module docstring.

    Problems never raise and are never guessed around. They become flags on
    the affected line (and in Estimate.all_flags):

        * UNKNOWN_RATE_CODE (blocker): the component is skipped and adds $0.
        * NEGATIVE_QUANTITY (blocker): the whole line is priced at $0.
        * NO_COMPONENTS (blocker): the line has nothing to price, so adds $0.
        * ZERO_QUANTITY (warning): the line prices to $0.
    """
    index = _index_rates(rate_card)
    currency = rate_card.currency
    priced = [_price_line(line, index, currency) for line in lines]

    direct_labor = sum((p.labor_cost for p in priced), ZERO)
    direct_material = sum((p.material_cost for p in priced), ZERO)
    direct_equipment = sum((p.equipment_cost for p in priced), ZERO)

    # Each displayed figure is rounded before it is summed, so the subtotal
    # is exactly the five categories above it and the grand total is exactly
    # subtotal + overhead + profit.
    markups = rate_card.markups
    material_markup = direct_material * markups.material_markup_pct / HUNDRED
    sales_tax = (
        (direct_material + material_markup)
        * markups.sales_tax_pct_on_materials
        / HUNDRED
    )
    reported_markup = round_money(material_markup)
    reported_tax = round_money(sales_tax)
    subtotal = (
        direct_labor + direct_material + reported_markup + reported_tax + direct_equipment
    )
    overhead = subtotal * markups.overhead_pct / HUNDRED
    profit = (subtotal + overhead) * markups.profit_pct / HUNDRED
    reported_overhead = round_money(overhead)
    reported_profit = round_money(profit)
    grand_total = subtotal + reported_overhead + reported_profit

    return Estimate(
        currency=currency,
        lines=priced,
        totals=EstimateTotals(
            direct_labor=direct_labor,
            direct_material=direct_material,
            material_markup=reported_markup,
            sales_tax=reported_tax,
            direct_equipment=direct_equipment,
            subtotal=subtotal,
            overhead=reported_overhead,
            profit=reported_profit,
            grand_total=grand_total,
        ),
        all_flags=[
            LineFlag(line_id=p.id, **flag.model_dump())
            for p in priced
            for flag in p.flags
        ],
    )


def _index_rates(rate_card: RateCard) -> _RateIndex:
    return {
        "labor": {
            r.code: _Rate(r.role, r.hourly_rate, "hrs", "hr")
            for r in rate_card.labor_rates
        },
        "material": {
            m.code: _Rate(m.name, m.unit_cost, m.unit, m.unit)
            for m in rate_card.materials
        },
        "equipment": {
            e.code: _Rate(e.name, e.rate, e.unit, e.unit) for e in rate_card.equipment
        },
    }


def _price_line(line: BidLineItem, index: _RateIndex, currency: str) -> PricedLine:
    flags = list(line.flags)
    trace: list[str] = []
    costs: dict[ComponentType, Decimal] = {
        "labor": ZERO,
        "material": ZERO,
        "equipment": ZERO,
    }

    if not line.components:
        flags.append(
            Flag(
                severity="blocker",
                code="NO_COMPONENTS",
                message="Line has no cost components, so it is priced at 0.",
            )
        )
        trace.append("Not priced: line has no cost components")

    if line.quantity < 0:
        flags.append(
            Flag(
                severity="blocker",
                code="NEGATIVE_QUANTITY",
                message=(
                    f"Quantity is {_number(line.quantity)}; "
                    "line is not priced and contributes 0."
                ),
            )
        )
        trace.append(f"Not priced: quantity is negative ({_number(line.quantity)})")
    else:
        if line.quantity == 0:
            flags.append(
                Flag(
                    severity="warning",
                    code="ZERO_QUANTITY",
                    message="Quantity is 0, so the line prices to 0.",
                )
            )
        for component in line.components:
            label = component.type.capitalize()
            entry = index[component.type].get(component.rate_card_code)
            if entry is None:
                flags.append(
                    Flag(
                        severity="blocker",
                        code="UNKNOWN_RATE_CODE",
                        message=(
                            f"Rate card has no {component.type} entry with code "
                            f"'{component.rate_card_code}'; component skipped "
                            "and priced at 0."
                        ),
                    )
                )
                trace.append(
                    f"{label}: SKIPPED, code '{component.rate_card_code}' "
                    "not found in rate card"
                )
                continue

            amount = line.quantity * component.quantity_per_unit * entry.rate
            costs[component.type] += amount
            trace.append(
                f"{label}: {_number(line.quantity)} {line.unit}"
                f" x {_number(component.quantity_per_unit)} {entry.quantity_unit}"
                f" x {_rate(entry.rate, currency)}/{entry.rate_unit}"
                f" ({entry.name}) = {_money(round_money(amount), currency)}"
            )

    labor_cost = round_money(costs["labor"])
    material_cost = round_money(costs["material"])
    equipment_cost = round_money(costs["equipment"])
    line_subtotal = labor_cost + material_cost + equipment_cost
    trace.append(
        f"Line subtotal: {_money(labor_cost, currency)} labor"
        f" + {_money(material_cost, currency)} material"
        f" + {_money(equipment_cost, currency)} equipment"
        f" = {_money(line_subtotal, currency)}"
    )

    return PricedLine(
        id=line.id,
        item_number=line.item_number,
        description=line.description,
        quantity=line.quantity,
        unit=line.unit,
        labor_cost=labor_cost,
        material_cost=material_cost,
        equipment_cost=equipment_cost,
        line_subtotal=line_subtotal,
        calculation_trace=trace,
        flags=flags,
        source_ref=line.source_ref,
        assumptions=list(line.assumptions),
        rate_basis=_rate_basis(line),
        production_rate_code=line.production_rate_code,
        mapping_confidence=line.mapping_confidence,
        mapping_rationale=line.mapping_rationale,
    )


def _rate_basis(line: BidLineItem) -> RateBasis:
    """Whose quantities per unit the line's components carry."""
    if not line.components:
        return "none"
    return "standard" if line.production_rate_code else "assumed"


# Trace formatting. Display only: nothing below feeds back into a calculation.


def _number(value: Decimal) -> str:
    """12.50 -> '12.5', 1E+3 -> '1,000'."""
    return f"{value.normalize():,f}"


def _money(amount: Decimal, currency: str) -> str:
    """An already-rounded amount as '$2,550.00', or 'EUR 2,550.00' if not USD."""
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{prefix}{amount:,.2f}"


def _rate(rate: Decimal, currency: str) -> str:
    """A rate with at least 2 decimals, never rounded: 85 -> '$85.00'."""
    if rate == rate.quantize(CENT):
        return _money(rate, currency)
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{prefix}{rate.normalize():,f}"
