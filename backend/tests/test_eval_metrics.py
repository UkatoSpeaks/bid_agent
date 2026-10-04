"""The eval metrics, on small examples that can be checked by hand. No API calls."""

from decimal import Decimal

import pytest

from evals import metrics
from evals.cases import CaseError, EvalCase, ExpectedLine, read_verified
from evals.metrics import FlagSeen, Ratio
from evals.scoring import (
    ActualFlag,
    ActualLine,
    RunOutput,
    gold_estimate,
    known_weaknesses,
    score_case,
    score_run,
    summarize,
)

# --- line matching, recall and precision ---


def test_match_lines_pairs_by_item_number():
    match = metrics.match_lines(["A1", "A2", "A3"], ["A3", "A1", "X9"])

    assert match.pairs == [(0, 1), (2, 0)]
    assert match.missed == [1]  # A2 did not come back
    assert match.extra == [2]  # X9 was not expected


def test_recall_and_precision():
    # 3 expected, 4 came back, 2 of them expected.
    match = metrics.match_lines(["1", "2", "3"], ["1", "2", "7", "8"])

    recall = metrics.line_recall(match)
    precision = metrics.line_precision(match)

    assert (recall.num, recall.den) == (2, 3)
    assert recall.rate == pytest.approx(2 / 3)
    assert (precision.num, precision.den) == (2, 4)
    assert precision.rate == 0.5


def test_item_numbers_match_ignoring_case_and_spacing():
    match = metrics.match_lines(["B-5", "Item 4"], [" b-5 ", "ITEM  4"])

    assert len(match.pairs) == 2
    assert match.missed == [] and match.extra == []


def test_a_differently_written_item_number_does_not_match():
    # "Item 4" extracted as "4" is a missed line and an extra line.
    match = metrics.match_lines(["Item 4"], ["4"])

    assert match.pairs == []
    assert match.missed == [0] and match.extra == [0]


def test_a_duplicate_item_number_pairs_in_order():
    # Expected twice, came back twice: both pair, first with first.
    match = metrics.match_lines(["103", "104", "103"], ["103", "103", "104"])
    assert match.pairs == [(0, 0), (1, 2), (2, 1)]
    assert match.missed == [] and match.extra == []

    # Expected twice, came back once: one is missed.
    match = metrics.match_lines(["103", "103"], ["103"])
    assert match.pairs == [(0, 0)]
    assert match.missed == [1]

    # Expected once, came back twice: one is extra.
    match = metrics.match_lines(["103"], ["103", "103"])
    assert match.extra == [1]


def test_nothing_expected_and_nothing_returned_has_no_rate():
    match = metrics.match_lines([], [])

    assert metrics.line_recall(match).rate is None
    assert metrics.line_precision(match).rate is None


def test_ratios_add_up_as_counts():
    # 1/2 and 3/4 make 4/6, not the mean of 50% and 75%.
    total = Ratio(num=1, den=2) + Ratio(num=3, den=4)

    assert (total.num, total.den) == (4, 6)
    assert total.rate == pytest.approx(4 / 6)


# --- quantity, unit, skipped rows ---


def test_quantity_match_is_exact():
    assert metrics.quantity_matches(Decimal("1240"), Decimal("1240.0"))
    assert not metrics.quantity_matches(Decimal("1240"), Decimal("1.240"))
    assert not metrics.quantity_matches(Decimal("312.5"), Decimal("312"))


def test_unit_match_normalises_spellings():
    assert metrics.unit_matches("linear feet", "LF")
    assert metrics.unit_matches("Each", "ea.")
    assert not metrics.unit_matches("LF", "SF")


def test_skipped_rows_counts_rows_no_line_was_made_from():
    # Three rows must be skipped; a line was made from the subtotal row.
    ratio = metrics.skipped_rows(
        ["p1-t1-r1", "p1-t1-r2", "p1-t1-r7"], ["p1-t1-r3", "P1-T1-R7", None]
    )

    assert (ratio.num, ratio.den) == (2, 3)


# --- mapping ---


def test_mapping_outcomes():
    assert metrics.mapping_outcome("PR-CU-3T", "PR-CU-3T") == "correct"
    assert metrics.mapping_outcome(None, None) == "correct"
    # A standard rate existed and the model used none.
    assert metrics.mapping_outcome("PR-REG-SUP", None) == "false_none"
    # No standard rate exists and the model picked one anyway.
    assert metrics.mapping_outcome(None, "PR-DUCT-FLEX-8") == "false_rate"
    assert metrics.mapping_outcome("PR-CU-3T", "PR-CU-5T") == "wrong_code"


# --- flags ---


def test_required_flag_is_caught_by_any_of_its_codes():
    seen = [FlagSeen("NO_COMPONENTS"), FlagSeen("HIGH_IMPACT_LINE")]

    assert metrics.flag_caught(["ASSUMED_PRODUCTION_RATE", "NO_COMPONENTS"], None, seen)
    assert not metrics.flag_caught(["VAGUE_SCOPE"], None, seen)
    assert not metrics.flag_caught(["VAGUE_SCOPE"], None, [])


def test_required_flag_can_require_what_the_message_says():
    pattern = "duplicat|twice"
    about_units = [FlagSeen("EXTRACTION_NOTE", "The unit is not clear.")]
    about_duplicate = [FlagSeen("EXTRACTION_NOTE", "This row is a DUPLICATE of the row above.")]

    assert not metrics.flag_caught(["EXTRACTION_NOTE"], pattern, about_units)
    assert metrics.flag_caught(["EXTRACTION_NOTE"], pattern, about_duplicate)


def test_extra_flags_are_those_neither_required_nor_allowed():
    seen = [
        FlagSeen("VAGUE_SCOPE"),  # required
        FlagSeen("LOW_CONFIDENCE_MAPPING"),  # allowed
        FlagSeen("HIGH_IMPACT_LINE"),  # follows from the totals: never noise
        FlagSeen("QUANTITY_NOT_IN_SOURCE"),  # noise
        FlagSeen("EXTRACTION_NOTE"),  # noise
    ]

    extra = metrics.extra_flags(seen, ["VAGUE_SCOPE", "LOW_CONFIDENCE_MAPPING"])

    assert extra == ["QUANTITY_NOT_IN_SOURCE", "EXTRACTION_NOTE"]


# --- money ---


def test_total_error():
    # Draft 1,050 against a gold total of 1,000: 50 too high, 5%.
    error = metrics.total_error(Decimal("1050.00"), Decimal("1000.00"))

    assert error.error == Decimal("50.00")
    assert error.abs_pct == pytest.approx(5.0)
    assert not error.exact


def test_total_error_below_the_gold_total_is_negative_but_its_percentage_is_not():
    error = metrics.total_error(Decimal("900.00"), Decimal("1000.00"))

    assert error.error == Decimal("-100.00")
    assert error.abs_pct == pytest.approx(10.0)


def test_total_error_exact_and_zero_gold():
    assert metrics.total_error(Decimal("86425.60"), Decimal("86425.60")).exact
    assert metrics.total_error(Decimal("86425.60"), Decimal("86425.60")).abs_pct == 0

    # No percentage of a gold total of 0.
    assert metrics.total_error(Decimal("10"), Decimal("0")).abs_pct is None
    assert metrics.total_error(Decimal("0"), Decimal("0")).exact


# --- stability ---


def test_stability_all_runs_identical():
    result = metrics.stability(["a", "a", "a"])

    assert result.identical
    assert result.agreement == 1.0
    assert (result.runs, result.distinct) == (3, 1)


def test_stability_one_run_of_three_differs():
    result = metrics.stability([Decimal("100.00"), Decimal("100.00"), Decimal("101.50")])

    assert not result.identical
    assert result.agreement == pytest.approx(2 / 3)
    assert result.distinct == 2


def test_stability_all_runs_differ():
    result = metrics.stability([("x",), ("y",), ("z",)])

    assert result.agreement == pytest.approx(1 / 3)
    assert result.distinct == 3


def test_stability_of_no_runs():
    result = metrics.stability([])

    assert result.agreement is None
    assert not result.identical


# --- scoring a run against a case (the sample rate card prices it) ---


def make_case() -> EvalCase:
    """Three lines: a standard rate, a vague lump sum with no rate, a TBD quantity."""
    return EvalCase(
        id="case",
        title="Test case",
        bid_file="none.xlsx",
        lines=[
            ExpectedLine(
                item_number="1",
                description="Programmable thermostat",
                quantity="4",
                unit="EA",
                production_rate="PR-TSTAT-PROG",
            ),
            ExpectedLine(
                item_number="2",
                description="Misc. work as required",
                quantity="1",
                unit="LS",
                production_rate="none",
                required_flags=[
                    "VAGUE_SCOPE",
                    {"any_of": ["ASSUMED_PRODUCTION_RATE", "NO_COMPONENTS"]},
                ],
                problem="vague lump sum",
            ),
            ExpectedLine(
                item_number="3",
                description="Refrigerant charge",
                quantity="TBD",
                unit="LB",
                production_rate="PR-REFRIG-CHARGE",
                required_flags=["QUANTITY_NOT_NUMERIC"],
                allowed_flags=["ZERO_QUANTITY"],
            ),
        ],
        skip_rows=[{"ref": "R1", "text": "Item | Description | Qty | Unit", "why": "header"}],
    )


def actual_line(item, quantity, unit, code, flags=(), ref="R2", subtotal="0", basis=None):
    return ActualLine(
        item_number=item,
        description="",
        quantity=Decimal(quantity),
        unit=unit,
        source_ref=ref,
        production_rate_code=code,
        rate_basis=basis or ("standard" if code else "none"),
        line_subtotal=Decimal(subtotal),
        flags=[ActualFlag(code=code_, severity="warning", message="") for code_ in flags],
    )


def perfect_run(gold_total: Decimal, run: int = 1) -> RunOutput:
    return RunOutput(
        run=run,
        status="ok",
        seconds=2.0,
        total_tokens=1000,
        grand_total=gold_total,
        standard_only_total=gold_total,
        lines=[
            actual_line("1", "4", "each", "PR-TSTAT-PROG", ref="R2"),
            actual_line("2", "1", "LS", None, ["VAGUE_SCOPE", "NO_COMPONENTS"], ref="R3"),
            actual_line(
                "3", "0", "LB", "PR-REFRIG-CHARGE", ["QUANTITY_NOT_NUMERIC", "ZERO_QUANTITY"], ref="R4"
            ),
        ],
    )


def test_gold_total_comes_from_the_engine(sample_rate_card):
    gold = gold_estimate(make_case(), sample_rate_card)

    # Only line 1 is priced: 4 thermostats at $145.00 + 1.25 h of an
    # electrician at $92.00 = 4 x 260.00 = 1,040.00 direct, of which 580.00
    # is material. Markup 15% = 87.00; tax 7.25% of 667.00 = 48.36 (rounded);
    # subtotal 1,175.36; overhead 10% = 117.54; profit 8% of 1,292.896 =
    # 103.43; grand total 1,396.33.
    assert [line.line_subtotal for line in gold.lines] == [Decimal("1040.00"), 0, 0]
    assert gold.totals.grand_total == Decimal("1396.33")


def test_a_perfect_run_scores_full_marks(sample_rate_card):
    case = make_case()
    gold = gold_estimate(case, sample_rate_card)

    result = score_run(case, gold, perfect_run(gold.totals.grand_total))

    m = result.metrics
    assert m.line_recall.rate == 1 and m.line_precision.rate == 1
    assert m.quantity_exact.rate == 1  # "TBD" came back as 0, as it must
    assert m.unit_match.rate == 1  # "each" is EA
    assert m.skipped_rows.rate == 1
    assert m.code_accuracy.rate == 1
    assert (m.flag_recall.num, m.flag_recall.den) == (3, 3)
    assert m.extra_flags == 0
    assert result.total.exact
    assert result.failures == []


def test_a_missed_required_flag_lowers_flag_recall(sample_rate_card):
    case = make_case()
    gold = gold_estimate(case, sample_rate_card)
    run = perfect_run(gold.totals.grand_total)
    # The vague lump sum comes back without VAGUE_SCOPE.
    run.lines[1] = actual_line("2", "1", "LS", None, ["NO_COMPONENTS"], ref="R3")

    result = score_run(case, gold, run)

    assert (result.metrics.flag_recall.num, result.metrics.flag_recall.den) == (2, 3)
    [failure] = result.failures
    assert failure.kind == "flag_missed"
    assert failure.item_number == "2"
    assert failure.problem == "vague lump sum"
    assert failure.expected == "flag VAGUE_SCOPE"
    assert failure.actual == "flags: NO_COMPONENTS"


def test_required_flags_of_a_line_that_was_not_extracted_are_missed(sample_rate_card):
    case = make_case()
    gold = gold_estimate(case, sample_rate_card)
    run = perfect_run(gold.totals.grand_total)
    del run.lines[1]

    result = score_run(case, gold, run)

    assert (result.metrics.line_recall.num, result.metrics.line_recall.den) == (2, 3)
    assert (result.metrics.flag_recall.num, result.metrics.flag_recall.den) == (1, 3)
    assert [f.kind for f in result.failures] == ["line_missed", "flag_missed", "flag_missed"]


def test_mapping_errors_and_noise_are_counted(sample_rate_card):
    case = make_case()
    gold = gold_estimate(case, sample_rate_card)
    run = perfect_run(gold.totals.grand_total)
    # Line 1: no rate used although one exists, plus a flag nobody asked for.
    run.lines[0] = actual_line(
        "1", "4", "EA", None, ["ASSUMED_PRODUCTION_RATE"], basis="assumed", subtotal="900.00"
    )
    # Line 2: a rate picked although none exists.
    run.lines[1] = actual_line("2", "1", "LS", "PR-DUCT-FLEX-8", ["VAGUE_SCOPE", "UNIT_MISMATCH"])
    # A header row priced as a line.
    run.lines.append(actual_line("", "0", "", None, ["NO_COMPONENTS"], ref="R1"))
    run.standard_only_total = Decimal("0")

    result = score_run(case, gold, run)

    m = result.metrics
    assert (m.code_accuracy.num, m.code_accuracy.den) == (1, 3)
    assert (m.false_none.num, m.false_none.den) == (1, 2)  # 2 lines have a standard rate
    assert (m.false_rate.num, m.false_rate.den) == (1, 1)  # 1 line has none
    assert (m.line_precision.num, m.line_precision.den) == (3, 4)
    assert (m.skipped_rows.num, m.skipped_rows.den) == (0, 1)
    # ASSUMED_PRODUCTION_RATE on line 1, UNIT_MISMATCH on line 2, NO_COMPONENTS
    # on the extra line.
    assert m.extra_flags == 3
    kinds = {f.kind for f in result.failures}
    assert {"false_none", "false_rate", "line_extra", "row_not_skipped", "total_error"} <= kinds
    # NO_COMPONENTS is gone from line 2, but UNIT_MISMATCH is not in its any-of.
    assert "flag_missed" in kinds


def test_dollars_guessed_on_a_line_without_a_rate_are_a_note_not_an_error(sample_rate_card):
    case = make_case()
    gold = gold_estimate(case, sample_rate_card)
    gold_total = gold.totals.grand_total
    run = perfect_run(gold_total)
    run.lines[1] = actual_line(
        "2", "1", "LS", None, ["VAGUE_SCOPE", "ASSUMED_PRODUCTION_RATE"], basis="assumed"
    )
    run.grand_total = gold_total + Decimal("500.00")

    result = score_run(case, gold, run)

    assert not result.total.exact
    assert result.total.error == Decimal("500.00")
    assert result.standard_only.exact
    [failure] = result.failures
    assert (failure.kind, failure.severity) == ("total_off_assumed", "note")


def test_a_failed_run_scores_zero(sample_rate_card):
    case = make_case()
    gold = gold_estimate(case, sample_rate_card)
    run = RunOutput(run=1, status="failed", error="no valid JSON", seconds=3.0)

    result = score_run(case, gold, run)

    assert result.metrics.line_recall.rate == 0
    assert result.metrics.flag_recall.rate == 0
    assert (result.metrics.flag_recall.num, result.metrics.flag_recall.den) == (0, 3)
    assert (result.metrics.skipped_rows.num, result.metrics.skipped_rows.den) == (0, 1)
    assert result.total.abs_pct == pytest.approx(100.0)
    # One failure that says why, not one per missing line.
    assert [f.kind for f in result.failures] == ["run_failed"]
    assert result.failures[0].actual == "no valid JSON"


def test_case_stability_and_summary(sample_rate_card):
    case = make_case()
    gold_total = gold_estimate(case, sample_rate_card).totals.grand_total
    runs = [perfect_run(gold_total, run) for run in (1, 2, 3)]
    # Run 3 picks another code for line 1, which changes its total.
    runs[2].lines[0] = actual_line("1", "4", "EA", "PR-REG-SUP")
    runs[2].grand_total = runs[2].standard_only_total = Decimal("500.00")

    result = score_case(case, runs, sample_rate_card, accuracy_runs=3)

    assert not result.code_stability.identical
    assert result.code_stability.agreement == pytest.approx(2 / 3)
    assert result.total_stability.agreement == pytest.approx(2 / 3)
    assert (result.metrics.code_accuracy.num, result.metrics.code_accuracy.den) == (8, 9)
    assert result.money.exact_runs == 2
    kinds = [f.kind for f in result.failures]
    assert kinds == ["wrong_code", "total_error", "unstable_codes", "unstable_total"]
    wrong = result.failures[0]
    assert wrong.runs == [3]
    assert wrong.actual == {3: "production rate PR-REG-SUP"}

    summary = summarize([result])
    assert summary.hand_verified == 0
    assert (summary.stability.codes_identical.num, summary.stability.codes_identical.den) == (0, 1)
    assert summary.cost.mean_tokens_per_bid == 1000
    assert summary.cost.mean_seconds == 2.0

    weaknesses = known_weaknesses([result])
    assert [w.kind for w in weaknesses] == [
        "unstable_codes",
        "unstable_total",
        "total_error",
        "wrong_code",
    ]
    assert "1 of 3 run(s)" in weaknesses[3].detail


def test_accuracy_counts_only_the_first_runs_but_stability_counts_all(sample_rate_card):
    case = make_case()
    gold_total = gold_estimate(case, sample_rate_card).totals.grand_total
    runs = [perfect_run(gold_total, run) for run in (1, 2, 3)]
    # Runs 2 and 3 exist only to measure stability. Run 3 picks another code.
    runs[2].lines[0] = actual_line("1", "4", "EA", "PR-REG-SUP")
    runs[2].grand_total = runs[2].standard_only_total = Decimal("500.00")

    result = score_case(case, runs, sample_rate_card, accuracy_runs=1, runs_planned=3)

    # Accuracy and money: run 1 alone, which was perfect.
    assert (result.metrics.code_accuracy.num, result.metrics.code_accuracy.den) == (3, 3)
    assert result.metrics.bids == 1
    assert (result.money.runs, result.money.exact_runs) == (1, 1)
    # Stability, cost and the failures: all three runs.
    assert not result.code_stability.identical
    assert result.cost.runs == 3
    assert "wrong_code" in [f.kind for f in result.failures]
    assert (result.runs_requested, result.accuracy_runs) == (3, 1)

    summary = summarize([result])
    assert (summary.runs_scored, summary.runs_total, summary.stability_cases) == (1, 3, 1)


def test_no_failures_means_no_known_weaknesses(sample_rate_card):
    case = make_case()
    gold_total = gold_estimate(case, sample_rate_card).totals.grand_total
    result = score_case(case, [perfect_run(gold_total)], sample_rate_card, accuracy_runs=1)

    assert known_weaknesses([result]) == []


def test_flag_spec_label_says_what_the_message_must_say():
    line = ExpectedLine(
        item_number="5",
        description="",
        quantity="1",
        unit="EA",
        production_rate="none",
        required_flags=[
            "VAGUE_SCOPE",
            {"any_of": ["ASSUMED_PRODUCTION_RATE", "NO_COMPONENTS"]},
            {"any_of": ["EXTRACTION_NOTE"], "message_matches": "duplicat", "meaning": "points out the duplicate"},
        ],
    )

    assert [spec.label for spec in line.required_flags] == [
        "VAGUE_SCOPE",
        "ASSUMED_PRODUCTION_RATE or NO_COMPONENTS",
        "EXTRACTION_NOTE that points out the duplicate",
    ]


# --- the VERIFIED BY HAND marker ---


def test_verified_marker_is_read_from_the_first_line():
    assert read_verified("# VERIFIED BY HAND: yes\nid: x\n")
    assert not read_verified("# VERIFIED BY HAND: no\nid: x\n")
    assert read_verified("# verified by hand:  YES\n")


def test_a_missing_verified_marker_is_an_error():
    with pytest.raises(CaseError):
        read_verified("id: x\n# VERIFIED BY HAND: yes\n")
