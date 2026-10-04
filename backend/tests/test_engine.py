"""Pricing engine tests.

Expected values are hand-calculated in the comments. The fixture rate card
(see conftest.py) uses: material markup 10%, sales tax 8%, overhead 10%,
profit 10%.
"""

from decimal import Decimal as D

from app.pricing import price_estimate, round_money
from app.schemas import Flag

from tests.conftest import make_line


def test_single_labor_only_line(rate_card):
    # 12 units x 2.5 hrs x $85.00/hr = $2,550.00
    line = make_line("1", "12", [("labor", "L-TECH", "2.5")])

    estimate = price_estimate([line], rate_card)

    priced = estimate.lines[0]
    assert priced.labor_cost == D("2550.00")
    assert priced.material_cost == D("0.00")
    assert priced.equipment_cost == D("0.00")
    assert priced.line_subtotal == D("2550.00")
    assert priced.calculation_trace == [
        "Labor: 12 EA x 2.5 hrs x $85.00/hr (HVAC Tech) = $2,550.00",
        "Line subtotal: $2,550.00 labor + $0.00 material + $0.00 equipment = $2,550.00",
    ]
    assert priced.flags == []

    # No materials, so no markup or tax.
    # subtotal    = 2,550.00
    # overhead    = 2,550.00 x 10%            =   255.00
    # profit      = (2,550.00 + 255.00) x 10% =   280.50
    # grand total = 2,550.00 + 255.00 + 280.50 = 3,085.50
    totals = estimate.totals
    assert totals.direct_labor == D("2550.00")
    assert totals.direct_material == D("0.00")
    assert totals.material_markup == D("0.00")
    assert totals.sales_tax == D("0.00")
    assert totals.direct_equipment == D("0.00")
    assert totals.subtotal == D("2550.00")
    assert totals.overhead == D("255.00")
    assert totals.profit == D("280.50")
    assert totals.grand_total == D("3085.50")
    assert estimate.all_flags == []


def test_mixed_line_labor_material_equipment(rate_card):
    # labor:     4 x 3 hrs    x $85.00  = 1,020.00
    # material:  4 x 1 EA     x $145.00 =   580.00
    # equipment: 4 x 0.25 day x $185.00 =   185.00
    # line subtotal                     = 1,785.00
    line = make_line(
        "1",
        "4",
        [
            ("labor", "L-TECH", "3"),
            ("material", "M-TSTAT", "1"),
            ("equipment", "E-LIFT", "0.25"),
        ],
    )

    estimate = price_estimate([line], rate_card)

    priced = estimate.lines[0]
    assert priced.labor_cost == D("1020.00")
    assert priced.material_cost == D("580.00")
    assert priced.equipment_cost == D("185.00")
    assert priced.line_subtotal == D("1785.00")
    assert priced.calculation_trace == [
        "Labor: 4 EA x 3 hrs x $85.00/hr (HVAC Tech) = $1,020.00",
        "Material: 4 EA x 1 EA x $145.00/EA (Thermostat) = $580.00",
        "Equipment: 4 EA x 0.25 day x $185.00/day (Scissor lift) = $185.00",
        "Line subtotal: $1,020.00 labor + $580.00 material + $185.00 equipment = $1,785.00",
    ]

    # markup      = 580.00 x 10%                      =    58.00
    # sales tax   = (580.00 + 58.00) x 8%             =    51.04
    # subtotal    = 1,020 + 580 + 58 + 51.04 + 185    = 1,894.04
    # overhead    = 1,894.04 x 10%      = 189.404     ->  189.40
    # profit      = (1,894.04 + 189.404) x 10%
    #             = 2,083.444 x 10%     = 208.3444    ->  208.34
    # grand total = 1,894.04 + 189.40 + 208.34        = 2,291.78
    #   (sum of the rounded figures; the unrounded chain gives 2,291.7884)
    totals = estimate.totals
    assert totals.material_markup == D("58.00")
    assert totals.sales_tax == D("51.04")
    assert totals.subtotal == D("1894.04")
    assert totals.overhead == D("189.40")
    assert totals.profit == D("208.34")
    assert totals.grand_total == D("2291.78")


def test_markup_tax_overhead_profit_order_on_two_lines(rate_card):
    # Line A (qty 10):
    #   labor:    10 x 2 hrs  x $85.00 = 1,700.00
    #   material: 10 x 20 LF  x $11.50 = 2,300.00
    # Line B (qty 2):
    #   labor:     2 x 4 hrs   x $48.00  = 384.00
    #   material:  2 x 1 EA    x $145.00 = 290.00
    #   equipment: 2 x 1.5 hrs x $245.00 = 735.00
    line_a = make_line("A", "10", [("labor", "L-TECH", "2"), ("material", "M-DUCT", "20")])
    line_b = make_line(
        "B",
        "2",
        [
            ("labor", "L-APPR", "4"),
            ("material", "M-TSTAT", "1"),
            ("equipment", "E-CRANE", "1.5"),
        ],
    )

    estimate = price_estimate([line_a, line_b], rate_card)

    assert estimate.lines[0].line_subtotal == D("4000.00")  # 1,700 + 2,300
    assert estimate.lines[1].line_subtotal == D("1409.00")  # 384 + 290 + 735

    # direct labor     = 1,700 + 384 = 2,084.00
    # direct material  = 2,300 + 290 = 2,590.00
    # direct equipment               =   735.00
    totals = estimate.totals
    assert totals.direct_labor == D("2084.00")
    assert totals.direct_material == D("2590.00")
    assert totals.direct_equipment == D("735.00")

    # Markup applies to materials only:
    #   2,590.00 x 10% = 259.00
    #   (marking up labor or equipment too would give a larger number)
    assert totals.material_markup == D("259.00")

    # Tax applies to marked-up materials:
    #   (2,590.00 + 259.00) x 8% = 2,849.00 x 8% = 227.92
    #   (tax on unmarked materials would be 207.20)
    assert totals.sales_tax == D("227.92")

    # subtotal = 2,084 + 2,590 + 259 + 227.92 + 735 = 5,895.92
    assert totals.subtotal == D("5895.92")

    # overhead = 5,895.92 x 10% = 589.592 -> 589.59
    assert totals.overhead == D("589.59")

    # Profit applies to subtotal + overhead:
    #   (5,895.92 + 589.592) x 10% = 6,485.512 x 10% = 648.5512 -> 648.55
    #   (profit on subtotal alone would be 589.59)
    assert totals.profit == D("648.55")

    # grand total = 5,895.92 + 589.59 + 648.55 = 7,134.06
    assert totals.grand_total == D("7134.06")


def test_missing_rate_code_adds_blocker_and_skips_component(rate_card):
    # labor: 2 x 1 hr x $85.00 = 170.00; the unknown material adds nothing.
    line = make_line("1", "2", [("labor", "L-TECH", "1"), ("material", "M-NOPE", "3")])

    estimate = price_estimate([line], rate_card)

    priced = estimate.lines[0]
    assert priced.labor_cost == D("170.00")
    assert priced.material_cost == D("0.00")
    assert priced.line_subtotal == D("170.00")
    assert "Material: SKIPPED, code 'M-NOPE' not found in rate card" in priced.calculation_trace

    assert [(f.severity, f.code) for f in priced.flags] == [("blocker", "UNKNOWN_RATE_CODE")]
    assert "M-NOPE" in priced.flags[0].message
    assert [(f.line_id, f.code) for f in estimate.all_flags] == [("1", "UNKNOWN_RATE_CODE")]


def test_code_from_another_section_is_not_matched(rate_card):
    # L-TECH exists, but as labor. A material component must not pick it up.
    line = make_line("1", "1", [("material", "L-TECH", "1")])

    estimate = price_estimate([line], rate_card)

    assert estimate.lines[0].line_subtotal == D("0.00")
    assert [f.code for f in estimate.all_flags] == ["UNKNOWN_RATE_CODE"]


def test_zero_quantity_is_flagged(rate_card):
    line = make_line("1", "0", [("labor", "L-TECH", "2")])

    estimate = price_estimate([line], rate_card)

    assert estimate.lines[0].line_subtotal == D("0.00")
    assert [(f.severity, f.code) for f in estimate.lines[0].flags] == [("warning", "ZERO_QUANTITY")]
    assert estimate.totals.grand_total == D("0.00")


def test_negative_quantity_is_flagged_and_not_priced(rate_card):
    # Would be -5 x 2 x $85.00 = -850.00 if priced; it must contribute 0.
    line = make_line("1", "-5", [("labor", "L-TECH", "2")])

    estimate = price_estimate([line], rate_card)

    assert estimate.lines[0].labor_cost == D("0.00")
    assert [(f.severity, f.code) for f in estimate.lines[0].flags] == [
        ("blocker", "NEGATIVE_QUANTITY")
    ]
    assert estimate.totals.grand_total == D("0.00")


def test_empty_components_is_flagged(rate_card):
    line = make_line("1", "3", [])

    estimate = price_estimate([line], rate_card)

    assert estimate.lines[0].line_subtotal == D("0.00")
    assert [(f.severity, f.code) for f in estimate.lines[0].flags] == [("blocker", "NO_COMPONENTS")]


def test_all_flags_collects_existing_and_engine_flags_with_line_ids(rate_card):
    # Line "1" arrives with a flag from an earlier stage and prices cleanly.
    # Line "2" has zero quantity and no components.
    line_1 = make_line("1", "1", [("labor", "L-TECH", "1")])
    line_1.flags.append(Flag(severity="info", code="LOW_CONFIDENCE_MATCH", message="check"))
    line_2 = make_line("2", "0", [])

    estimate = price_estimate([line_1, line_2], rate_card)

    assert [(f.line_id, f.code) for f in estimate.all_flags] == [
        ("1", "LOW_CONFIDENCE_MATCH"),
        ("2", "NO_COMPONENTS"),
        ("2", "ZERO_QUANTITY"),
    ]
    # The input line is not modified.
    assert [f.code for f in line_2.flags] == []


def test_round_money_is_half_up():
    assert round_money(D("0.125")) == D("0.13")  # banker's rounding would give 0.12
    assert round_money(D("0.135")) == D("0.14")
    assert round_money(D("0.124")) == D("0.12")
    assert round_money(D("2")) == D("2.00")


def test_line_costs_round_once_after_summing_components(rate_card):
    # Two material components on one line, each 1 x 1 x $0.125 = 0.125.
    #   Sum first, then round: 0.125 + 0.125 = 0.25 -> 0.25   (what we do)
    #   Round each, then sum:  0.13  + 0.13         = 0.26   (wrong)
    line = make_line("1", "1", [("material", "M-SCREW", "1"), ("material", "M-SCREW", "1")])

    estimate = price_estimate([line], rate_card)

    assert estimate.lines[0].material_cost == D("0.25")


def test_lines_round_individually_and_totals_sum_rounded_lines(rate_card):
    # Two lines, each 1 x 1 x $0.125 = 0.125 -> 0.13 (half up) at line level.
    # direct material = 0.13 + 0.13 = 0.26, so the lines add up to the total.
    lines = [
        make_line("1", "1", [("material", "M-SCREW", "1")]),
        make_line("2", "1", [("material", "M-SCREW", "1")]),
    ]

    estimate = price_estimate(lines, rate_card)

    assert [p.material_cost for p in estimate.lines] == [D("0.13"), D("0.13")]
    assert estimate.totals.direct_material == D("0.26")


def test_grand_total_is_the_sum_of_the_reported_figures(rate_card):
    # Same line as test_mixed_line_labor_material_equipment:
    #   subtotal 1,894.04, overhead 189.404, profit 208.3444.
    # Overhead and profit are rounded before summing (189.40 and 208.34):
    #   1,894.04 + 189.40 + 208.34 = 2,291.78
    # The unrounded chain would give 2,291.7884 -> 2,291.79, a cent more
    # than the figures displayed above it.
    line = make_line(
        "1",
        "4",
        [
            ("labor", "L-TECH", "3"),
            ("material", "M-TSTAT", "1"),
            ("equipment", "E-LIFT", "0.25"),
        ],
    )

    totals = price_estimate([line], rate_card).totals

    assert totals.grand_total == D("2291.78")
    assert totals.subtotal + totals.overhead + totals.profit == totals.grand_total


def test_subtotal_is_the_sum_of_the_displayed_categories(rate_card):
    # 6 x 1 EA x $0.125 = 0.75 direct material
    #   markup   = 0.75 x 10%            = 0.075   -> 0.08
    #   tax      = (0.75 + 0.075) x 8%   = 0.066   -> 0.07
    #   subtotal = 0.75 + 0.08 + 0.07    = 0.90
    #     (carried unrounded it would be 0.75 + 0.075 + 0.066 = 0.891 -> 0.89,
    #      a cent less than the three figures displayed above it)
    #   overhead = 0.90 x 10%            = 0.09
    #   profit   = (0.90 + 0.09) x 10%   = 0.099   -> 0.10
    #   grand total = 0.90 + 0.09 + 0.10 = 1.09
    line = make_line("1", "6", [("material", "M-SCREW", "1")])

    totals = price_estimate([line], rate_card).totals

    assert totals.direct_material == D("0.75")
    assert totals.material_markup == D("0.08")
    assert totals.sales_tax == D("0.07")
    assert totals.subtotal == D("0.90")
    assert totals.overhead == D("0.09")
    assert totals.profit == D("0.10")
    assert totals.grand_total == D("1.09")
    assert_foots(price_estimate([line], rate_card))


def assert_foots(estimate):
    """Every displayed figure is the exact sum of the figures above it."""
    totals = estimate.totals
    for line in estimate.lines:
        assert line.labor_cost + line.material_cost + line.equipment_cost == line.line_subtotal
    assert sum((line.labor_cost for line in estimate.lines), D("0")) == totals.direct_labor
    assert sum((line.material_cost for line in estimate.lines), D("0")) == totals.direct_material
    assert sum((line.equipment_cost for line in estimate.lines), D("0")) == totals.direct_equipment
    assert (
        totals.direct_labor
        + totals.direct_material
        + totals.material_markup
        + totals.sales_tax
        + totals.direct_equipment
        == totals.subtotal
    )
    assert totals.subtotal + totals.overhead + totals.profit == totals.grand_total
    # Nothing is displayed with more than 2 decimals.
    for amount in totals.model_dump().values():
        assert amount == amount.quantize(D("0.01"))


def test_every_displayed_figure_foots(rate_card):
    # Awkward quantities, so most intermediate values have more than 2
    # decimals. Whatever they round to, each displayed sum must be exactly
    # the sum of the displayed figures above it.
    for quantity in ("1", "3", "6", "7", "13", "0.333", "17.77", "1850.5"):
        lines = [
            make_line("A", quantity, [("labor", "L-TECH", "0.18"), ("material", "M-SCREW", "1")]),
            make_line("B", quantity, [("material", "M-DUCT", "1.1"), ("equipment", "E-LIFT", "0.07")]),
            make_line("C", "3", [("labor", "L-APPR", "0.333"), ("material", "M-SCREW", "7")]),
        ]

        assert_foots(price_estimate(lines, rate_card))


def test_profit_is_calculated_from_unrounded_overhead(rate_card):
    # 3 x 1 EA x $0.125 = 0.375 -> 0.38 direct material (rounded at line level)
    #   markup   = 0.38 x 10%              = 0.038     -> 0.04
    #   tax      = (0.38 + 0.038) x 8%     = 0.03344   -> 0.03
    #   subtotal = 0.38 + 0.04 + 0.03      = 0.45
    #   overhead = 0.45 x 10%              = 0.045     -> 0.05
    #   profit   = (0.45 + 0.045) x 10%    = 0.0495    -> 0.05
    #     (from the rounded overhead it would be (0.45 + 0.05) x 10% = 0.05
    #      here too, but the input to each percentage stays unrounded)
    #   grand total = 0.45 + 0.05 + 0.05 = 0.55
    line = make_line("1", "3", [("material", "M-SCREW", "1")])

    totals = price_estimate([line], rate_card).totals

    assert totals.subtotal == D("0.45")
    assert totals.overhead == D("0.05")
    assert totals.profit == D("0.05")
    assert totals.grand_total == D("0.55")


def test_pricing_is_deterministic(rate_card):
    lines = [
        make_line("A", "10", [("labor", "L-TECH", "2"), ("material", "M-DUCT", "20")]),
        make_line("B", "2", [("equipment", "E-CRANE", "1.5"), ("material", "M-NOPE", "1")]),
        make_line("C", "0", []),
    ]

    first = price_estimate(lines, rate_card)
    second = price_estimate(lines, rate_card)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_empty_estimate(rate_card):
    estimate = price_estimate([], rate_card)

    assert estimate.lines == []
    assert estimate.totals.grand_total == D("0.00")
