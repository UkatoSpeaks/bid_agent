"""Post-pricing review: impact flags and the review summary.

Expected values are hand-calculated in the comments. The fixture rate card
(see conftest.py) uses: material markup 10%, sales tax 8%.
"""

from decimal import Decimal as D

from app.pricing import price_estimate, review_estimate
from app.schemas import Flag

from tests.conftest import make_line

ASSUMED = Flag(
    severity="warning",
    code="ASSUMED_PRODUCTION_RATE",
    message="These quantities per unit were guessed by the LLM: 2 hrs per EA of L-TECH.",
)


def labor_line(line_id, hours, production_rate_code=None):
    """One unit of L-TECH labor at $85.00/hr, so the line costs hours x 85."""
    line = make_line(line_id, "1", [("labor", "L-TECH", hours)])
    line.production_rate_code = production_rate_code
    if production_rate_code is None:
        line.flags.append(ASSUMED.model_copy())
    return line


def reviewed(lines, rate_card, high_impact_pct=D("15")):
    return review_estimate(price_estimate(lines, rate_card), rate_card, high_impact_pct)


def codes(line):
    return [(flag.severity, flag.code) for flag in line.flags]


def test_line_above_the_threshold_is_flagged_high_impact(rate_card):
    # A: 80 hrs = 6,800.00 (80%)   B: 10 hrs = 850.00 (10%)   C: 10 hrs = 850.00 (10%)
    lines = [
        labor_line("A", "80", "PR-A"),
        labor_line("B", "10", "PR-B"),
        labor_line("C", "10", "PR-C"),
    ]

    estimate = reviewed(lines, rate_card)

    assert [line.subtotal_share_pct for line in estimate.lines] == [D("80.0"), D("10.0"), D("10.0")]
    assert codes(estimate.lines[0]) == [("warning", "HIGH_IMPACT_LINE")]
    assert "80.0% of the subtotal" in estimate.lines[0].flags[0].message
    assert estimate.lines[1].flags == [] and estimate.lines[2].flags == []
    assert estimate.review.high_impact_line_ids == ["A"]
    assert [(f.line_id, f.code) for f in estimate.all_flags] == [("A", "HIGH_IMPACT_LINE")]


def test_threshold_is_configurable_and_must_be_exceeded(rate_card):
    # A: 5,100.00 (60%)   B: 2,550.00 (30%)   C: 850.00 (10%)
    lines = [
        labor_line("A", "60", "PR-A"),
        labor_line("B", "30", "PR-B"),
        labor_line("C", "10", "PR-C"),
    ]

    assert reviewed(lines, rate_card).review.high_impact_line_ids == ["A", "B"]
    assert reviewed(lines, rate_card, D("50")).review.high_impact_line_ids == ["A"]
    # Exactly at the threshold is not above it.
    assert reviewed(lines, rate_card, D("30")).review.high_impact_line_ids == ["A"]
    assert reviewed(lines, rate_card, D("5")).review.high_impact_line_ids == ["A", "B", "C"]
    assert reviewed(lines, rate_card, D("50")).review.high_impact_threshold_pct == D("50")


def test_assumed_rate_on_a_high_impact_line_is_upgraded_to_a_blocker(rate_card):
    # A: assumed, 6,800.00 (80%)  -> blocker
    # B: assumed,   850.00 (10%)  -> stays a warning
    # C: standard,  850.00 (10%)
    lines = [labor_line("A", "80"), labor_line("B", "10"), labor_line("C", "10", "PR-C")]

    estimate = reviewed(lines, rate_card)

    assert codes(estimate.lines[0]) == [
        ("blocker", "ASSUMED_PRODUCTION_RATE"),
        ("warning", "HIGH_IMPACT_LINE"),
    ]
    assert "Raised to a blocker because this line is 80.0% of the subtotal." in (
        estimate.lines[0].flags[0].message
    )
    assert estimate.lines[0].flags[0].message.startswith(ASSUMED.message)
    assert codes(estimate.lines[1]) == [("warning", "ASSUMED_PRODUCTION_RATE")]
    assert estimate.lines[2].flags == []
    # all_flags is rebuilt, so it carries the upgraded severity too.
    assert [(f.line_id, f.severity, f.code) for f in estimate.all_flags] == [
        ("A", "blocker", "ASSUMED_PRODUCTION_RATE"),
        ("A", "warning", "HIGH_IMPACT_LINE"),
        ("B", "warning", "ASSUMED_PRODUCTION_RATE"),
    ]
    # The input estimate is not modified.
    assert lines[0].flags[0].severity == "warning"


def test_review_summary_counts_and_percentages(rate_card):
    # A: standard, labor 60 hrs x $85.00         = 5,100.00
    # B: assumed,  labor 20 hrs x $85.00         = 1,700.00
    # C: standard, material 10 EA x $145.00      = 1,450.00 direct
    #    loaded with markup and tax: 1,450 x 1.10 x 1.08 = 1,722.60
    # D: no components                            =     0.00
    # loaded total = 5,100.00 + 1,700.00 + 1,722.60 = 8,522.60  (= the subtotal)
    #   A = 59.84%   B = 19.95%   C = 20.21%
    #   standard = (5,100.00 + 1,722.60) / 8,522.60 = 80.05% -> 80.1
    #   assumed  = 100 - 80.1                                 = 19.9
    line_c = make_line("C", "10", [("material", "M-TSTAT", "1")])
    line_c.production_rate_code = "PR-C"
    lines = [labor_line("A", "60", "PR-A"), labor_line("B", "20"), line_c, make_line("D", "1", [])]

    estimate = reviewed(lines, rate_card)

    assert estimate.totals.subtotal == D("8522.60")
    assert [line.subtotal_share_pct for line in estimate.lines] == [
        D("59.8"), D("19.9"), D("20.2"), D("0.0"),
    ]  # fmt: skip
    assert [line.rate_basis for line in estimate.lines] == [
        "standard", "assumed", "standard", "none",
    ]  # fmt: skip
    review = estimate.review
    assert review.standard_rate_pct == D("80.1")
    assert review.assumed_rate_pct == D("19.9")
    assert review.standard_rate_pct + review.assumed_rate_pct == D("100")
    assert (review.lines_on_standard_rates, review.lines_on_assumed_rates) == (2, 1)
    assert review.lines_not_priced == 1
    assert review.high_impact_line_ids == ["A", "B", "C"]
    # Blockers: B's assumed rate (19.9% > 15%) and D's NO_COMPONENTS.
    # Warnings: three HIGH_IMPACT_LINE.
    assert (review.blocker_count, review.warning_count, review.info_count) == (2, 3, 0)
    assert review.blocker_count + review.warning_count == len(estimate.all_flags)


def test_everything_on_standard_rates_is_100_percent(rate_card):
    estimate = reviewed([labor_line("A", "1", "PR-A"), labor_line("B", "1", "PR-B")], rate_card)

    assert estimate.review.standard_rate_pct == D("100.0")
    assert estimate.review.assumed_rate_pct == D("0.0")


def test_review_of_an_estimate_with_nothing_priced(rate_card):
    estimate = reviewed([make_line("A", "1", [])], rate_card)

    assert estimate.lines[0].subtotal_share_pct is None
    assert estimate.review.standard_rate_pct == D("0")
    assert estimate.review.assumed_rate_pct == D("0")
    assert estimate.review.high_impact_line_ids == []
    assert (estimate.review.blocker_count, estimate.review.lines_not_priced) == (1, 1)


def test_review_changes_no_money(rate_card):
    lines = [labor_line("A", "80"), labor_line("B", "10", "PR-B")]
    priced = price_estimate(lines, rate_card)

    estimate = review_estimate(priced, rate_card)

    assert estimate.totals == priced.totals
    assert [l.line_subtotal for l in estimate.lines] == [l.line_subtotal for l in priced.lines]
    assert priced.review is None  # pricing alone adds no review
