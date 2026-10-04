"""Score pipeline runs against the expected answers and add the scores up.

No LLM and no I/O. The gold total of a case is computed here by the pricing
engine from the expected answers, so it never depends on hand arithmetic.
"""

from collections import Counter
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from app.extraction import expand_production_rate
from app.pricing import price_estimate
from app.schemas import BidLineItem, Estimate, EstimateTotals, RateCard
from app.units import units_match
from evals import metrics
from evals.cases import NO_RATE, EvalCase, ExpectedLine, SkipRow
from evals.metrics import FlagSeen, Ratio, Stability, TotalError

ZERO = Decimal("0")

Severity = Literal["error", "note"]


# --- what a run produced (stored as is, so a result can be scored again) ---


class ActualFlag(BaseModel):
    code: str
    severity: str
    message: str


class ActualLine(BaseModel):
    item_number: str
    description: str
    quantity: Decimal
    unit: str
    source_ref: str | None
    production_rate_code: str | None
    rate_basis: str
    line_subtotal: Decimal
    flags: list[ActualFlag]
    # The LLM's own account of its mapping, kept for reading failures.
    mapping_confidence: str | None = None
    mapping_rationale: str | None = None


class RunOutput(BaseModel):
    """One pipeline run on one bid."""

    run: int
    # "failed": the model's output could not be used, so there is no estimate.
    status: Literal["ok", "failed"]
    error: str | None = None
    # Wall-clock time, and the part of it spent waiting on rate limits.
    seconds: float
    rate_limit_wait_seconds: float = 0.0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    grand_total: Decimal = ZERO
    # The grand total with every line on an assumed (LLM-guessed) rate left
    # out: what the draft prices from company standard rates alone.
    standard_only_total: Decimal = ZERO
    # Every total of the estimate, as the engine returned them.
    totals: EstimateTotals | None = None
    lines: list[ActualLine] = Field(default_factory=list)
    # Source refs of the rows the LLM returned and code dropped as non-items.
    code_dropped_rows: list[str] = Field(default_factory=list)


def run_output_from_estimate(
    run: int, estimate: Estimate, rate_card: RateCard, **measured: float | int
) -> RunOutput:
    standard_only = price_estimate(
        [line for line in estimate.source_lines if line.production_rate_code], rate_card
    )
    return RunOutput(
        run=run,
        status="ok",
        grand_total=estimate.totals.grand_total,
        standard_only_total=standard_only.totals.grand_total,
        totals=estimate.totals,
        lines=[
            ActualLine(
                item_number=line.item_number,
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                source_ref=line.source_ref,
                production_rate_code=line.production_rate_code,
                rate_basis=line.rate_basis,
                line_subtotal=line.line_subtotal,
                flags=[
                    ActualFlag(code=f.code, severity=f.severity, message=f.message)
                    for f in line.flags
                ],
                mapping_confidence=line.mapping_confidence,
                mapping_rationale=line.mapping_rationale,
            )
            for line in estimate.lines
        ],
        code_dropped_rows=[row.source_ref for row in estimate.skipped_rows],
        **measured,
    )


# --- the gold estimate ---


def gold_lines(case: EvalCase, rate_card: RateCard) -> list[BidLineItem]:
    """The expected answers as priceable lines.

    A line with a production rate gets that rate's components, unless its
    unit does not fit the rate (then nothing can be priced, exactly as in the
    pipeline). A line with no rate, or no quantity, adds 0.
    """
    rates = {rate.code: rate for rate in rate_card.production_rates}
    lines: list[BidLineItem] = []
    for index, expected in enumerate(case.lines, start=1):
        components = []
        rate = rates.get(expected.rate_code) if expected.rate_code else None
        if rate is not None and units_match(expected.unit, rate.unit):
            components, _assumptions = expand_production_rate(rate, rate_card)
        lines.append(
            BidLineItem(
                id=f"G{index:03d}",
                item_number=expected.item_number,
                description=expected.description,
                quantity=expected.quantity_value,
                unit=expected.unit,
                components=components,
                production_rate_code=expected.rate_code,
            )
        )
    return lines


def gold_estimate(case: EvalCase, rate_card: RateCard) -> Estimate:
    return price_estimate(gold_lines(case, rate_card), rate_card)


# --- scores ---


class Metrics(BaseModel):
    """Counts for one run, or summed over runs and cases."""

    bids: int = 0  # runs scored
    line_recall: Ratio = Ratio()
    line_precision: Ratio = Ratio()
    quantity_exact: Ratio = Ratio()
    unit_match: Ratio = Ratio()
    skipped_rows: Ratio = Ratio()
    # Over the lines that were matched by item number.
    code_accuracy: Ratio = Ratio()
    # "none" although a standard rate existed / a rate although none exists.
    false_none: Ratio = Ratio()
    false_rate: Ratio = Ratio()
    wrong_code: int = 0
    flag_recall: Ratio = Ratio()
    extra_flags: int = 0

    @computed_field
    @property
    def extra_flags_per_bid(self) -> float | None:
        """Flags that were neither required nor allowed, per run: the noise."""
        return self.extra_flags / self.bids if self.bids else None

    def __add__(self, other: "Metrics") -> "Metrics":
        return Metrics(
            **{
                name: getattr(self, name) + getattr(other, name)
                for name in Metrics.model_fields
            }
        )


class Failure(BaseModel):
    """One thing a run got wrong: what was expected and what came back."""

    kind: str
    severity: Severity = "error"
    item_number: str | None = None
    # The problem planted on the line, if any.
    problem: str | None = None
    expected: str
    actual: str
    # Direct cost the difference moved, where that can be said.
    dollar_delta: Decimal | None = None


class RunResult(RunOutput):
    metrics: Metrics
    total: TotalError
    standard_only: TotalError
    extra_flag_codes: list[str]
    failures: list[Failure]


class CaseFailure(BaseModel):
    """A failure of one case, with the runs it happened in."""

    id: str  # unique within the result, e.g. "messy_bid-3"
    kind: str
    severity: Severity
    item_number: str | None
    problem: str | None
    expected: str
    runs: list[int]
    actual: dict[int, str]  # run -> what came back
    dollar_delta: Decimal | None = None


class Money(BaseModel):
    runs: int = 0
    exact_runs: int = 0
    # Mean and worst |draft total - gold total| as a percentage of the gold.
    mean_abs_error_pct: float | None = None
    max_abs_error_pct: float | None = None
    # The same, leaving out every line priced on an assumed rate.
    standard_only_exact_runs: int = 0
    standard_only_mean_abs_error_pct: float | None = None


class Cost(BaseModel):
    runs: int = 0
    mean_seconds: float | None = None  # wall clock per bid
    mean_active_seconds: float | None = None  # without rate-limit waits
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    mean_tokens_per_bid: float | None = None
    tokens_reported: bool = False


class ExpectedLineView(ExpectedLine):
    gold_subtotal: Decimal


class CaseResult(BaseModel):
    id: str
    title: str
    bid_file: str
    verified_by_hand: bool
    planted_problems: list[str]
    expected_lines: list[ExpectedLineView]
    skip_rows: list[SkipRow]
    gold_total: Decimal
    # Runs planned for this case, and how many of the runs (the first ones)
    # the accuracy metrics and the money figures are computed from. Every
    # run counts for stability, cost and the list of failures.
    runs_requested: int
    accuracy_runs: int
    runs: list[RunResult]
    metrics: Metrics
    money: Money
    cost: Cost
    code_stability: Stability
    total_stability: Stability
    failures: list[CaseFailure]


class StabilitySummary(BaseModel):
    # Cases whose runs all gave the same codes / the same grand total.
    codes_identical: Ratio = Ratio()
    totals_identical: Ratio = Ratio()
    mean_code_agreement: float | None = None
    mean_total_agreement: float | None = None


class Weakness(BaseModel):
    title: str
    detail: str
    kind: str
    severity: Severity
    occurrences: int  # runs it happened in, over all cases
    cases: list[str]
    examples: list[str]  # CaseFailure ids


class Summary(BaseModel):
    cases: int
    hand_verified: int
    # Runs the accuracy metrics are computed from, and all runs made.
    runs_scored: int
    runs_total: int
    runs_failed: int
    # Cases run more than once, which is what stability is measured on.
    stability_cases: int
    metrics: Metrics
    money: Money
    stability: StabilitySummary
    cost: Cost


def score_run(case: EvalCase, gold: Estimate, run: RunOutput) -> RunResult:
    """Compare one run with the expected answers of its case."""
    expected = case.lines
    actual = run.lines
    match = metrics.match_lines(
        [line.item_number for line in expected], [line.item_number for line in actual]
    )
    failures: list[Failure] = []
    scored = Metrics(
        bids=1,
        line_recall=metrics.line_recall(match),
        line_precision=metrics.line_precision(match),
    )

    gold_total = gold.totals.grand_total
    if run.status == "failed":
        # Nothing came back, so every count is 0 out of what was expected.
        # One failure says why, instead of one per missing line.
        scored.skipped_rows = Ratio(num=0, den=len(case.skip_rows))
        scored.flag_recall = Ratio(
            num=0, den=sum(len(line.required_flags) for line in expected)
        )
        return RunResult(
            **run.model_dump(),
            metrics=scored,
            total=metrics.total_error(ZERO, gold_total),
            standard_only=metrics.total_error(ZERO, gold_total),
            extra_flag_codes=[],
            failures=[
                Failure(
                    kind="run_failed",
                    expected="a draft estimate",
                    actual=run.error or "no output",
                    dollar_delta=-gold_total,
                )
            ],
        )

    gold_subtotals = [line.line_subtotal for line in gold.lines]
    for index in match.missed:
        line = expected[index]
        failures.append(
            Failure(
                kind="line_missed",
                item_number=line.item_number,
                problem=line.problem,
                expected=_expected_text(line),
                actual="not extracted",
                dollar_delta=-gold_subtotals[index] or None,
            )
        )
    for index in match.extra:
        line = actual[index]
        failures.append(
            Failure(
                kind="line_extra",
                item_number=line.item_number or "(no item number)",
                expected="no such line",
                actual=f"{_actual_text(line)} from [{line.source_ref}]: {line.description}",
                dollar_delta=line.line_subtotal or None,
            )
        )

    # Rows that must not become bid lines.
    used_refs = {(line.source_ref or "").casefold(): line for line in actual}
    scored.skipped_rows = metrics.skipped_rows(
        [row.ref for row in case.skip_rows], [line.source_ref for line in actual]
    )
    for row in case.skip_rows:
        line = used_refs.get(row.ref.casefold())
        if line is not None:
            failures.append(
                Failure(
                    kind="row_not_skipped",
                    item_number=line.item_number or "(no item number)",
                    problem=row.why,
                    expected=f"[{row.ref}] skipped ({row.why}): {row.text}",
                    actual=f"priced as a bid line: {_actual_text(line)}",
                    dollar_delta=line.line_subtotal or None,
                )
            )

    # Quantity, unit and production rate of the matched lines.
    for expected_index, actual_index in match.pairs:
        want, got = expected[expected_index], actual[actual_index]
        delta = got.line_subtotal - gold_subtotals[expected_index]

        quantity_ok = metrics.quantity_matches(want.quantity_value, got.quantity)
        scored.quantity_exact += Ratio(num=int(quantity_ok), den=1)
        if not quantity_ok:
            failures.append(
                Failure(
                    kind="quantity_wrong",
                    item_number=want.item_number,
                    problem=want.problem,
                    expected=f"quantity {want.quantity}",
                    actual=f"quantity {_number(got.quantity)}",
                    dollar_delta=delta or None,
                )
            )

        unit_ok = metrics.unit_matches(want.unit, got.unit)
        scored.unit_match += Ratio(num=int(unit_ok), den=1)
        if not unit_ok:
            failures.append(
                Failure(
                    kind="unit_wrong",
                    item_number=want.item_number,
                    problem=want.problem,
                    expected=f"unit {want.unit}",
                    actual=f"unit {got.unit or '(blank)'}",
                )
            )

        outcome = metrics.mapping_outcome(want.rate_code, got.production_rate_code)
        scored.code_accuracy += Ratio(num=int(outcome == "correct"), den=1)
        if want.rate_code is None:
            scored.false_rate += Ratio(num=int(outcome == "false_rate"), den=1)
        else:
            scored.false_none += Ratio(num=int(outcome == "false_none"), den=1)
            scored.wrong_code += int(outcome == "wrong_code")
        if outcome != "correct":
            failures.append(
                Failure(
                    kind=outcome,
                    item_number=want.item_number,
                    problem=want.problem,
                    expected=f"production rate {want.rate_code or NO_RATE}",
                    actual=(
                        f"production rate {got.production_rate_code or NO_RATE}"
                        + (" (components assumed by the LLM)" if got.rate_basis == "assumed" else "")
                    ),
                    dollar_delta=delta or None,
                )
            )

    # Flags. A required flag counts as caught if any extracted line with that
    # item number carries it, so a duplicate may be noted on either copy.
    seen_by_item: dict[str, list[FlagSeen]] = {}
    for line in actual:
        seen_by_item.setdefault(metrics.item_key(line.item_number), []).extend(
            FlagSeen(flag.code, flag.message) for flag in line.flags
        )
    accepted_by_item: dict[str, set[str]] = {}
    for want in expected:
        key = metrics.item_key(want.item_number)
        seen = seen_by_item.get(key, [])
        accepted = accepted_by_item.setdefault(key, set())
        accepted.update(want.allowed_flags)
        for spec in want.required_flags:
            accepted.update(spec.any_of)
            caught = metrics.flag_caught(spec.any_of, spec.message_matches, seen)
            scored.flag_recall += Ratio(num=int(caught), den=1)
            if not caught:
                failures.append(
                    Failure(
                        kind="flag_missed",
                        item_number=want.item_number,
                        problem=want.problem,
                        expected=f"flag {spec.label}",
                        actual="flags: " + (", ".join(sorted({f.code for f in seen})) or "none"),
                    )
                )
    extra_codes: list[str] = []
    for line in actual:
        accepted = accepted_by_item.get(metrics.item_key(line.item_number), set())
        extra_codes.extend(
            metrics.extra_flags(
                [FlagSeen(f.code, f.message) for f in line.flags], sorted(accepted)
            )
        )
    scored.extra_flags = len(extra_codes)

    # Money.
    total = metrics.total_error(run.grand_total, gold_total)
    standard_only = metrics.total_error(run.standard_only_total, gold_total)
    if not standard_only.exact:
        failures.append(
            Failure(
                kind="total_error",
                expected=f"grand total {_money(gold_total)}",
                actual=(
                    f"{_money(run.standard_only_total)} from standard rates"
                    + (
                        f" ({_money(run.grand_total)} with assumed-rate lines)"
                        if run.grand_total != run.standard_only_total
                        else ""
                    )
                ),
                dollar_delta=standard_only.error,
            )
        )
    elif not total.exact:
        assumed = [line for line in actual if line.rate_basis == "assumed"]
        failures.append(
            Failure(
                kind="total_off_assumed",
                severity="note",
                expected=f"grand total {_money(gold_total)} (lines with no standard rate add 0)",
                actual=(
                    f"{_money(run.grand_total)}: the standard-rate lines are exact; "
                    "the rest is quantities guessed by the LLM on "
                    + ", ".join(f"item {line.item_number}" for line in assumed)
                ),
                dollar_delta=total.error,
            )
        )

    return RunResult(
        **run.model_dump(),
        metrics=scored,
        total=total,
        standard_only=standard_only,
        extra_flag_codes=extra_codes,
        failures=failures,
    )


def code_signature(run: RunOutput) -> tuple:
    """The production rate chosen for every line of a run, in a comparable form."""
    if run.status == "failed":
        return ("run failed",)
    return tuple(
        sorted(
            (metrics.item_key(line.item_number), line.production_rate_code or NO_RATE)
            for line in run.lines
        )
    )


def score_case(
    case: EvalCase,
    runs: list[RunOutput],
    rate_card: RateCard,
    accuracy_runs: int,
    runs_planned: int | None = None,
) -> CaseResult:
    """Score the runs of one case.

    The accuracy metrics and the money figures come from runs 1 to
    `accuracy_runs`, so that a case run more often for stability does not
    weigh more than the others. Stability, cost and the failures use all runs.
    """
    gold = gold_estimate(case, rate_card)
    results = [score_run(case, gold, run) for run in runs]
    accuracy = [result for result in results if result.run <= accuracy_runs]
    return CaseResult(
        id=case.id,
        title=case.title,
        bid_file=case.bid_path.name if case.bid_path else case.bid_file,
        verified_by_hand=case.verified_by_hand,
        planted_problems=case.planted_problems,
        expected_lines=[
            ExpectedLineView(**line.model_dump(), gold_subtotal=priced.line_subtotal)
            for line, priced in zip(case.lines, gold.lines)
        ],
        skip_rows=case.skip_rows,
        gold_total=gold.totals.grand_total,
        runs_requested=runs_planned if runs_planned is not None else accuracy_runs,
        accuracy_runs=accuracy_runs,
        runs=results,
        metrics=sum((r.metrics for r in accuracy), Metrics()),
        money=money_summary(accuracy),
        cost=cost_summary(results),
        code_stability=metrics.stability([code_signature(r) for r in results]),
        total_stability=metrics.stability([r.grand_total for r in results]),
        failures=case_failures(case.id, results),
    )


def case_failures(case_id: str, results: list[RunResult]) -> list[CaseFailure]:
    """The failures of all runs, with the same failure in several runs merged."""
    merged: dict[tuple, CaseFailure] = {}
    for result in results:
        for failure in result.failures:
            key = (failure.kind, failure.item_number, failure.expected)
            entry = merged.get(key)
            if entry is None:
                entry = merged[key] = CaseFailure(
                    id=f"{case_id}-{len(merged) + 1}",
                    kind=failure.kind,
                    severity=failure.severity,
                    item_number=failure.item_number,
                    problem=failure.problem,
                    expected=failure.expected,
                    runs=[],
                    actual={},
                    dollar_delta=failure.dollar_delta,
                )
            if result.run not in entry.runs:
                entry.runs.append(result.run)
                entry.actual[result.run] = failure.actual
    failures = list(merged.values())

    if len(results) > 1:
        codes = metrics.stability([code_signature(r) for r in results])
        totals = metrics.stability([r.grand_total for r in results])
        for kind, measured, what, values in (
            ("unstable_codes", codes, "production rate codes", None),
            ("unstable_total", totals, "grand total", [_money(r.grand_total) for r in results]),
        ):
            if measured.identical:
                continue
            actual = {
                r.run: values[index] if values else _codes_text(r, results)
                for index, r in enumerate(results)
            }
            failures.append(
                CaseFailure(
                    id=f"{case_id}-{len(failures) + 1}",
                    kind=kind,
                    severity="error",
                    item_number=None,
                    problem=None,
                    expected=f"the same {what} in all {len(results)} runs",
                    runs=[r.run for r in results],
                    actual=actual,
                )
            )
    return failures


def _codes_text(run: RunResult, results: list[RunResult]) -> str:
    """The codes of the lines on which the runs disagree, for one run."""
    signatures = [dict(code_signature(r)) if r.status == "ok" else {} for r in results]
    keys = sorted({key for signature in signatures for key in signature})
    differing = [
        key for key in keys if len({signature.get(key) for signature in signatures}) > 1
    ]
    if run.status == "failed":
        return "run failed"
    own = dict(code_signature(run))
    return "; ".join(f"{key}: {own.get(key, 'line missing')}" for key in differing) or "same"


def money_summary(results: list[RunResult]) -> Money:
    errors = [r.total.abs_pct for r in results if r.total.abs_pct is not None]
    standard = [r.standard_only.abs_pct for r in results if r.standard_only.abs_pct is not None]
    return Money(
        runs=len(results),
        exact_runs=sum(1 for r in results if r.total.exact),
        mean_abs_error_pct=_mean(errors),
        max_abs_error_pct=max(errors, default=None),
        standard_only_exact_runs=sum(1 for r in results if r.standard_only.exact),
        standard_only_mean_abs_error_pct=_mean(standard),
    )


def cost_summary(results: list[RunOutput]) -> Cost:
    total_tokens = sum(r.total_tokens for r in results)
    return Cost(
        runs=len(results),
        mean_seconds=_mean([r.seconds for r in results]),
        mean_active_seconds=_mean([r.seconds - r.rate_limit_wait_seconds for r in results]),
        llm_calls=sum(r.llm_calls for r in results),
        prompt_tokens=sum(r.prompt_tokens for r in results),
        completion_tokens=sum(r.completion_tokens for r in results),
        total_tokens=total_tokens,
        mean_tokens_per_bid=total_tokens / len(results) if results and total_tokens else None,
        tokens_reported=total_tokens > 0,
    )


def summarize(cases: list[CaseResult]) -> Summary:
    runs = [run for case in cases for run in case.runs]
    accuracy = [run for case in cases for run in case.runs if run.run <= case.accuracy_runs]
    multi = [case for case in cases if len(case.runs) > 1]
    return Summary(
        cases=len(cases),
        hand_verified=sum(1 for case in cases if case.verified_by_hand),
        runs_scored=len(accuracy),
        runs_total=len(runs),
        runs_failed=sum(1 for run in runs if run.status == "failed"),
        stability_cases=len(multi),
        metrics=sum((case.metrics for case in cases), Metrics()),
        money=money_summary(accuracy),
        stability=StabilitySummary(
            codes_identical=Ratio(
                num=sum(1 for case in multi if case.code_stability.identical), den=len(multi)
            ),
            totals_identical=Ratio(
                num=sum(1 for case in multi if case.total_stability.identical), den=len(multi)
            ),
            mean_code_agreement=_mean([case.code_stability.agreement for case in multi]),
            mean_total_agreement=_mean([case.total_stability.agreement for case in multi]),
        ),
        cost=cost_summary(runs),
    )


_WEAKNESS_TITLES = {
    "flag_missed": "A planted problem was not flagged",
    "false_none": "A standard rate existed, but the model used none",
    "false_rate": "No standard rate exists, but the model picked one",
    "wrong_code": "The wrong production rate was chosen",
    "line_missed": "A bid line was not extracted",
    "line_extra": "A line was extracted that is not in the expected answers",
    "row_not_skipped": "A row that is not a bid item was priced",
    "quantity_wrong": "A quantity was extracted wrongly",
    "unit_wrong": "A unit was extracted wrongly",
    "total_error": "The total priced from standard rates differs from the gold total",
    "total_off_assumed": "The grand total includes dollars guessed by the LLM",
    "run_failed": "A run produced no estimate",
    "unstable_codes": "Repeated runs chose different production rates",
    "unstable_total": "Repeated runs gave different grand totals",
}


def known_weaknesses(cases: list[CaseResult]) -> list[Weakness]:
    """Group the failures that actually happened into a short list.

    One entry per kind of failure and planted problem, most frequent first.
    Nothing here is written by hand: no failures, no entries.
    """
    groups: dict[tuple[str, str | None], list[tuple[CaseResult, CaseFailure]]] = {}
    for case in cases:
        for failure in case.failures:
            groups.setdefault((failure.kind, failure.problem), []).append((case, failure))

    weaknesses: list[Weakness] = []
    for (kind, problem), members in groups.items():
        occurrences = sum(len(failure.runs) for _case, failure in members)
        possible = sum(len(case.runs) for case, _failure in members)
        case_ids = list(dict.fromkeys(case.id for case, _failure in members))
        title = _WEAKNESS_TITLES.get(kind, kind)
        if problem:
            title += f": {problem}"
        case, first = members[0]
        item = f" item {first.item_number}" if first.item_number else ""
        got = Counter(first.actual.values()).most_common(1)[0][0]
        weaknesses.append(
            Weakness(
                title=title,
                detail=(
                    f"{occurrences} of {possible} run(s) in {len(case_ids)} case(s). "
                    f"E.g. {case.id}{item}: expected {first.expected}; got {got}."
                ),
                kind=kind,
                severity=first.severity,
                occurrences=occurrences,
                cases=case_ids,
                examples=[failure.id for _case, failure in members[:3]],
            )
        )
    weaknesses.sort(key=lambda w: (w.severity != "error", -w.occurrences, w.title))
    return weaknesses


def _mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _expected_text(line: ExpectedLine) -> str:
    return f"{line.quantity} {line.unit}, production rate {line.production_rate}"


def _actual_text(line: ActualLine) -> str:
    return (
        f"{_number(line.quantity)} {line.unit or '(no unit)'}, "
        f"production rate {line.production_rate_code or NO_RATE}"
    )


def _number(value: Decimal) -> str:
    return f"{value.normalize():,f}"


def _money(amount: Decimal) -> str:
    return f"${amount:,.2f}"
