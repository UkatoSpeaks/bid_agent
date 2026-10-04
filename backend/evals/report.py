"""Markdown reports: one per eval result, and a side-by-side model comparison.

Everything is rendered from an EvalResult. Failures are listed as they are.
"""

from collections import Counter
from decimal import Decimal

from evals.metrics import Ratio
from evals.results import EvalResult
from evals.scoring import CaseResult, Summary

DASH = "-"


def pct(ratio: Ratio) -> str:
    """'94.4% (51/54)', or '-' when there was nothing to measure."""
    if ratio.rate is None:
        return DASH
    return f"{ratio.rate * 100:.1f}% ({ratio.num}/{ratio.den})"


def _float(value: float | None, digits: int = 2, suffix: str = "") -> str:
    return DASH if value is None else f"{value:.{digits}f}{suffix}"


def _money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def metric_rows(summary: Summary) -> list[tuple[str, str]]:
    """(label, value) for every overall metric, in report order."""
    m, money, stability, cost = summary.metrics, summary.money, summary.stability, summary.cost
    return [
        ("Extraction: line recall", pct(m.line_recall)),
        ("Extraction: line precision", pct(m.line_precision)),
        ("Extraction: quantity exact match", pct(m.quantity_exact)),
        ("Extraction: unit match", pct(m.unit_match)),
        ("Extraction: rows correctly skipped", pct(m.skipped_rows)),
        ("Mapping: production rate code accuracy", pct(m.code_accuracy)),
        ('Mapping: picked "none" although a rate existed', pct(m.false_none)),
        ("Mapping: picked a rate although none exists", pct(m.false_rate)),
        ("Mapping: picked the wrong rate", str(m.wrong_code)),
        ("Flags: recall on required flags", pct(m.flag_recall)),
        ("Flags: extra flags per bid (noise)", _float(m.extra_flags_per_bid)),
        ("Money: mean grand total error", _float(money.mean_abs_error_pct, 2, "%")),
        ("Money: worst grand total error", _float(money.max_abs_error_pct, 2, "%")),
        ("Money: runs with the exact gold total", f"{money.exact_runs}/{money.runs}"),
        (
            "Money: mean error, standard-rate lines only",
            _float(money.standard_only_mean_abs_error_pct, 2, "%"),
        ),
        (
            "Money: runs exact, standard-rate lines only",
            f"{money.standard_only_exact_runs}/{money.runs}",
        ),
        ("Stability: repeated cases with identical codes in all runs", pct(stability.codes_identical)),
        ("Stability: repeated cases with an identical total in all runs", pct(stability.totals_identical)),
        ("Speed: mean seconds per bid (wall clock)", _float(cost.mean_seconds, 1)),
        ("Speed: mean seconds per bid, without rate-limit waits", _float(cost.mean_active_seconds, 1)),
        (
            "Cost: mean tokens per bid",
            _float(cost.mean_tokens_per_bid, 0) if cost.tokens_reported else "not reported",
        ),
        (
            "Cost: total tokens (prompt + completion)",
            f"{cost.total_tokens:,} ({cost.prompt_tokens:,} + {cost.completion_tokens:,})"
            if cost.tokens_reported
            else "not reported",
        ),
        ("Runs that produced no estimate", f"{summary.runs_failed}/{summary.runs_total}"),
    ]


def _header(result: EvalResult) -> list[str]:
    meta, dataset = result.meta, result.dataset
    lines = [
        f"- Model: `{meta.model}` (temperature {meta.temperature}, "
        f"reasoning effort {meta.reasoning_effort}), LLM cache off",
        f"- Plan: {meta.runs_per_case} run(s) per case for the accuracy metrics"
        + (
            f"; {meta.stability_runs} runs on {', '.join(meta.stability_cases)} for stability"
            if meta.stability_cases
            else ""
        ),
        f"- Runs: {result.summary.runs_total} made on {dataset.cases} cases. Accuracy and money "
        f"are computed from {result.summary.runs_scored} of them (the first "
        f"{meta.runs_per_case} of each case); stability from the "
        f"{result.summary.stability_cases} case(s) run more than once; cost, speed and the "
        "list of failures from all runs.",
        f"- Started {meta.started_at}, finished {meta.finished_at or 'not finished'}",
        f"- **Hand-verified cases: {dataset.hand_verified} of {dataset.cases}.** "
        "Scores on cases that are not hand-verified rest on expected answers nobody has checked.",
        f"- {dataset.note}",
    ]
    if not meta.complete:
        lines.append(
            f"- **INCOMPLETE:** not every planned run has been made "
            f"({meta.stopped_because or 'the eval was interrupted'}). "
            "The numbers below cover only the runs that finished."
        )
    return lines


def _case_row(case: CaseResult) -> str:
    m = case.metrics
    errors = sum(1 for failure in case.failures if failure.severity == "error")
    stable = (
        DASH
        if len(case.runs) < 2
        else ("yes" if case.code_stability.identical and case.total_stability.identical else "NO")
    )
    return (
        f"| {case.id} | {'yes' if case.verified_by_hand else 'no'} "
        f"| {len(case.runs)}/{case.runs_requested} "
        f"| {pct(m.line_recall)} | {pct(m.code_accuracy)} | {pct(m.flag_recall)} "
        f"| {_float(m.extra_flags_per_bid)} | {_float(case.money.mean_abs_error_pct, 2, '%')} "
        f"| {stable} | {_float(case.cost.mean_active_seconds, 1)} | {errors} |"
    )


def render_markdown(result: EvalResult) -> str:
    out = [f"# Eval report: {result.meta.model}", "", *_header(result), ""]

    out += ["## Overall", "", "| Metric | Value |", "| --- | --- |"]
    out += [f"| {label} | {value} |" for label, value in metric_rows(result.summary)]

    out += [
        "",
        "## Per case",
        "",
        "| Case | Hand-verified | Runs | Line recall | Code accuracy | Flag recall "
        "| Extra flags / bid | Mean total error | Stable | Seconds / bid | Failures |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    out += [_case_row(case) for case in result.cases]

    noise = Counter(
        code for case in result.cases for run in case.runs for code in run.extra_flag_codes
    )
    out += ["", "## Extra flags (noise) by code", ""]
    if noise:
        out.append(
            "Flags raised that the expected answers neither require nor allow, over all runs. "
            "HIGH_IMPACT_LINE is not counted: it follows from the totals."
        )
        out.append("")
        out += [f"- `{code}`: {count}" for code, count in noise.most_common()]
    else:
        out.append("None.")

    out += ["", "## Known weaknesses", ""]
    if result.known_weaknesses:
        out.append("Generated from the failures of this run, most frequent first.")
        out.append("")
        for weakness in result.known_weaknesses:
            tag = "" if weakness.severity == "error" else " (note)"
            out.append(f"- **{weakness.title}**{tag}. {weakness.detail}")
    else:
        out.append("No failures in this run. That is a statement about these cases only.")

    out += ["", "## Failures: expected vs. what came back", ""]
    any_failure = False
    for case in result.cases:
        if not case.failures:
            continue
        any_failure = True
        out += [
            f"### {case.id} ({case.bid_file}, gold total {_money(case.gold_total)})",
            "",
            "| # | Kind | Item | Runs | Expected | Came back |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for failure in case.failures:
            got = "<br>".join(
                f"run {run}: {_cell(text)}" for run, text in sorted(failure.actual.items())
            )
            kind = failure.kind + ("" if failure.severity == "error" else " (note)")
            out.append(
                f"| {failure.id} | {kind} | {failure.item_number or DASH} "
                f"| {len(failure.runs)}/{len(case.runs)} | {_cell(failure.expected)} | {got} |"
            )
        out.append("")
    if not any_failure:
        out += ["None.", ""]

    return "\n".join(out).rstrip() + "\n"


def render_comparison(results: list[EvalResult]) -> str:
    """The same metrics for several models, side by side."""
    models = [result.meta.model for result in results]
    out = ["# Model comparison", ""]
    for result in results:
        dataset = result.dataset
        state = "" if result.meta.complete else " **INCOMPLETE**"
        out.append(
            f"- `{result.meta.model}`: run `{result.meta.run_id}`, "
            f"{result.summary.runs_total} runs, "
            f"{dataset.hand_verified} of {dataset.cases} cases hand-verified.{state}"
        )
    out += ["", f"- {results[0].dataset.note}", ""]

    out += [
        "## Overall",
        "",
        "| Metric | " + " | ".join(f"`{model}`" for model in models) + " |",
        "| --- |" + " --- |" * len(models),
    ]
    rows = [metric_rows(result.summary) for result in results]
    for index, (label, _value) in enumerate(rows[0]):
        out.append(f"| {label} | " + " | ".join(row[index][1] for row in rows) + " |")

    out += [
        "",
        "## Per case: failures (errors, not notes) and mean total error",
        "",
        "| Case | " + " | ".join(f"`{model}`" for model in models) + " |",
        "| --- |" + " --- |" * len(models),
    ]
    case_ids = list(dict.fromkeys(case.id for result in results for case in result.cases))
    for case_id in case_ids:
        cells = []
        for result in results:
            case = next((c for c in result.cases if c.id == case_id), None)
            if case is None:
                cells.append("not run")
                continue
            errors = sum(1 for failure in case.failures if failure.severity == "error")
            cells.append(
                f"{errors} failure(s), total error {_float(case.money.mean_abs_error_pct, 2, '%')}"
            )
        out.append(f"| {case_id} | " + " | ".join(cells) + " |")

    out += ["", "## Known weaknesses", ""]
    for result in results:
        out.append(f"### `{result.meta.model}`")
        out.append("")
        if result.known_weaknesses:
            out += [f"- **{w.title}**. {w.detail}" for w in result.known_weaknesses]
        else:
            out.append("No failures in this run.")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _cell(text: str) -> str:
    """Text that is safe inside a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")
