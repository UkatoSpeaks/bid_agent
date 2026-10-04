"""Run the eval: every case against its expected answers, uncached.

    uv run python evals/run_evals.py
    uv run python evals/run_evals.py --model openai/gpt-oss-20b
    uv run python evals/run_evals.py --model openai/gpt-oss-120b --model openai/gpt-oss-20b
    uv run python evals/run_evals.py --cases messy_bid tricky_bid
    uv run python evals/run_evals.py --dry-run
    uv run python evals/run_evals.py --resume 20261004T124001Z-openai-gpt-oss-120b
    uv run python evals/run_evals.py --rescore 20261004T124001Z-openai-gpt-oss-120b
    uv run python evals/run_evals.py --compare

The default plan fits one day of Groq's free tier per model: every case runs
once, which gives the accuracy metrics, and three cases (clean, messy, tricky)
run three times, which gives stability. That is 15 runs. Before anything is
sent, the token use is estimated and printed; if it is over --max-tokens
(default 150,000) nothing is run.

Per eval it writes, in evals/results/:

    raw/<run_id>.json   what the pipeline returned in every run. Saved after
                        each run, so nothing is lost if the eval stops.
    <run_id>.json/.md   the scores and the report, computed from the raw file.

The LLM cache is always off. Cases run one after the other. Rate limits and
connection errors are waited out and the run tried again; if that does not
help (a daily limit), the eval stops and can be continued with --resume.

--rescore computes the scores and the report again from the saved raw output
against the expected files as they are now. It makes no LLM call. Use it
after correcting an expected file or marking it "VERIFIED BY HAND: yes".
"""

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, get_settings  # noqa: E402
from app.llm import (  # noqa: E402
    LLMClient,
    LLMError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMUsage,
    get_llm_client,
)
from app.pipeline import draft_estimate  # noqa: E402
from app.pricing import load_rate_card  # noqa: E402
from app.schemas import RateCard  # noqa: E402
from evals.cases import RESULTS_DIR, CaseError, EvalCase, check_case, load_cases  # noqa: E402
from evals.report import metric_rows, render_comparison, render_markdown  # noqa: E402
from evals.results import (  # noqa: E402
    EvalResult,
    RawRuns,
    RunMeta,
    build_result,
    latest_results,
    load_raw,
    model_slug,
    raw_path,
    raw_run_ids,
    result_path,
    save_raw,
    save_result,
    timestamp,
)
from evals.scoring import RunOutput, run_output_from_estimate  # noqa: E402

# The default plan: one run of every case for accuracy, and three runs of
# these three cases for stability.
DEFAULT_RUNS = 1
DEFAULT_STABILITY_RUNS = 3
DEFAULT_STABILITY_CASES = ("clean_bid", "messy_bid", "tricky_bid")
# Groq's free tier allows 200,000 tokens per model per day.
DEFAULT_MAX_TOKENS = 150_000
# Tokens assumed for a run of a case that has never been run. The sample
# bids took 7,000 to 10,000; this is on the safe side of their mean.
DEFAULT_TOKENS_PER_RUN = 9_000

# Seconds to wait before trying a run again after the client gave up on a
# rate limit: 60, then 120, then 240.
RATE_LIMIT_WAITS = (60.0, 120.0, 240.0)
# The same, after the provider could not be reached (connection, timeout, 5xx).
UNAVAILABLE_WAITS = (15.0, 60.0, 180.0)
# Groq's wording for limits that do not clear within minutes.
DAILY_LIMIT_MARKERS = ("per day", "tpd", "rpd")

logger = logging.getLogger("evals")


class StopEval(Exception):
    """Stop the eval and keep what has been run."""


def run_once(
    case: EvalCase,
    run: int,
    rate_card: RateCard,
    llm: LLMClient,
    settings: Settings,
    sleep=time.sleep,
) -> RunOutput:
    """One uncached pipeline run.

    A run the model fails (output that cannot be used, a request the provider
    rejects) is a result and comes back with status "failed". Rate limits and
    an unreachable provider say nothing about the model: the run is tried
    again, and StopEval is raised if that does not help.
    """
    limited = unavailable = 0
    while True:
        before = _usage(llm)
        started = time.perf_counter()
        try:
            result = draft_estimate(
                case.bid_path,
                rate_card,
                llm,
                settings.high_impact_line_pct,
                settings.standard_rate_declined_score,
            )
        except LLMRateLimitError as exc:
            message = str(exc)
            if any(marker in message.casefold() for marker in DAILY_LIMIT_MARKERS):
                raise StopEval(f"daily rate limit: {message}") from exc
            if limited == len(RATE_LIMIT_WAITS):
                raise StopEval(f"rate limit did not clear: {message}") from exc
            wait = RATE_LIMIT_WAITS[limited]
            limited += 1
            logger.warning("rate limited on %s run %d, waiting %.0fs", case.id, run, wait)
            sleep(wait)
            continue
        except LLMUnavailableError as exc:
            if unavailable == len(UNAVAILABLE_WAITS):
                raise StopEval(f"provider unavailable: {exc}") from exc
            wait = UNAVAILABLE_WAITS[unavailable]
            unavailable += 1
            logger.warning("%s (%s run %d), waiting %.0fs", exc, case.id, run, wait)
            sleep(wait)
            continue
        except LLMError as exc:
            return RunOutput(
                run=run,
                status="failed",
                error=str(exc),
                **_measured(started, before, _usage(llm)),
            )
        return run_output_from_estimate(
            run, result.estimate, rate_card, **_measured(started, before, _usage(llm))
        )


def _usage(llm: LLMClient) -> LLMUsage:
    """A copy of the client's running totals (zeros if it does not measure)."""
    usage = llm.usage or LLMUsage()
    return LLMUsage(**vars(usage))


def _measured(started: float, before: LLMUsage, after: LLMUsage) -> dict[str, float | int]:
    return {
        "seconds": round(time.perf_counter() - started, 3),
        "rate_limit_wait_seconds": round(
            after.rate_limit_wait_seconds - before.rate_limit_wait_seconds, 3
        ),
        "llm_calls": after.calls - before.calls,
        "prompt_tokens": after.prompt_tokens - before.prompt_tokens,
        "completion_tokens": after.completion_tokens - before.completion_tokens,
        "total_tokens": after.total_tokens - before.total_tokens,
    }


def tokens_per_run(directory: Path = RESULTS_DIR) -> dict[str, float]:
    """Mean tokens of a completed run of each case, from every saved raw file."""
    seen: dict[str, list[int]] = {}
    for run_id in raw_run_ids(directory):
        for case_id, runs in load_raw(run_id, directory).runs.items():
            seen.setdefault(case_id, []).extend(
                run.total_tokens for run in runs if run.status == "ok" and run.total_tokens
            )
    return {case_id: sum(tokens) / len(tokens) for case_id, tokens in seen.items() if tokens}


def estimate_tokens(todo: list[tuple[str, int]], history: dict[str, float]) -> int:
    """Estimated tokens for the (case, run) pairs still to run.

    A case that has been run before counts with its measured mean, any other
    with DEFAULT_TOKENS_PER_RUN.
    """
    return round(sum(history.get(case_id, DEFAULT_TOKENS_PER_RUN) for case_id, _run in todo))


def run_model(
    raw: RawRuns,
    cases: list[EvalCase],
    rate_card: RateCard,
    llm: LLMClient,
    settings: Settings,
    pause: float = 0.0,
    directory: Path = RESULTS_DIR,
    sleep=time.sleep,
    max_tokens: int | None = None,
) -> RawRuns:
    """Make the planned runs that `raw` is still missing, saving after each one.

    Runs go round by round (run 1 of every case, then run 2 of those planned
    for it, ...), so an eval that stops early still covers every case. Stops
    when the tokens used here reach `max_tokens`.
    """
    meta = raw.meta
    by_id = {case.id: case for case in cases}
    start = _usage(llm).total_tokens
    try:
        for case_id, run in raw.missing(list(by_id)):
            used = _usage(llm).total_tokens - start
            if max_tokens is not None and used >= max_tokens:
                raise StopEval(f"token budget used up: {used:,} of {max_tokens:,} tokens")
            planned = meta.planned_runs(case_id)
            print(f"  {meta.model}: {case_id} run {run}/{planned} ...", file=sys.stderr)
            output = run_once(by_id[case_id], run, rate_card, llm, settings, sleep)
            raw.runs.setdefault(case_id, []).append(output)
            save_raw(raw, directory)
            print(
                f"    {output.status}: {len(output.lines)} lines, "
                f"total {output.grand_total:,.2f}, {output.seconds:.1f}s, "
                f"{output.total_tokens} tokens",
                file=sys.stderr,
            )
            sleep(pause)
    except StopEval as exc:
        meta.stopped_because = str(exc)
        logger.error("stopping %s: %s", meta.model, exc)
    meta.complete = not raw.missing(list(by_id))
    if meta.complete:
        meta.stopped_because = None
    meta.finished_at = _now()
    save_raw(raw, directory)
    return raw


def write_result(
    raw: RawRuns, cases: list[EvalCase], rate_card: RateCard, directory: Path = RESULTS_DIR
) -> EvalResult:
    """Score the saved runs and write the .json and .md reports. No LLM calls."""
    result = build_result(raw, cases, rate_card)
    path = save_result(result, directory)
    path.with_suffix(".md").write_text(render_markdown(result), encoding="utf-8")
    return result


def write_comparison(results: list[EvalResult], directory: Path = RESULTS_DIR) -> Path:
    path = directory / f"{timestamp()}-comparison.md"
    path.write_text(render_comparison(results), encoding="utf-8")
    return path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print_summary(result: EvalResult) -> None:
    meta = result.meta
    print()
    print("=" * 100)
    print(f"{meta.model}   run {meta.run_id}" + ("" if meta.complete else "   INCOMPLETE"))
    print(
        f"  {result.dataset.hand_verified} of {result.dataset.cases} cases hand-verified. "
        "Synthetic dataset."
    )
    for label, value in metric_rows(result.summary):
        print(f"  {label:<62} {value}")
    print(f"  Known weaknesses: {len(result.known_weaknesses)} (see the .md report)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the LLM steps against expected answers.")
    parser.add_argument(
        "--model",
        action="append",
        help="model to evaluate; repeat to compare several (default: LLM_MODEL)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help="runs of every case, used for the accuracy metrics (default: 1)",
    )
    parser.add_argument(
        "--stability-runs",
        type=int,
        default=DEFAULT_STABILITY_RUNS,
        help="runs of each stability case in all (default: 3)",
    )
    parser.add_argument(
        "--stability-cases",
        nargs="*",
        default=list(DEFAULT_STABILITY_CASES),
        help="cases run --stability-runs times (default: clean_bid messy_bid tricky_bid)",
    )
    parser.add_argument("--cases", nargs="+", help="case ids to run (default: all)")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="token budget per model; nothing runs if the estimate is higher (default: 150000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and the estimated token use, then stop; no LLM calls",
    )
    parser.add_argument(
        "--pause", type=float, default=5.0, help="seconds between runs (default: 5)"
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="continue a stopped eval: make the runs its plan is still missing",
    )
    parser.add_argument(
        "--rescore",
        metavar="RUN_ID",
        nargs="+",
        help="recompute the metrics and the report of these runs from their saved output; "
        "no LLM calls ('all' for every saved run)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="only write the comparison of the newest result of each model; no LLM calls",
    )
    parser.add_argument("--rate-card", type=Path, help="rate card JSON (default: from settings)")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    base = get_settings()
    try:
        rate_card = load_rate_card(args.rate_card or base.resolved_rate_card_path)
        all_cases = load_cases()
        for case in all_cases:
            check_case(case, rate_card)
        cases = load_cases(only=args.cases)
    except (FileNotFoundError, CaseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.compare:
        results = latest_results()
        if not results:
            print("error: no eval results found in evals/results/", file=sys.stderr)
            return 1
    elif args.rescore:
        run_ids = raw_run_ids() if args.rescore == ["all"] else args.rescore
        results = []
        for run_id in run_ids:
            try:
                raw = load_raw(run_id)
            except FileNotFoundError:
                print(f"error: no saved runs at {raw_path(run_id)}", file=sys.stderr)
                return 1
            results.append(write_result(raw, all_cases, rate_card))
    else:
        jobs = _plan(args, base, cases)
        if jobs is None:
            return 1
        if args.dry_run:
            print("Dry run: nothing was sent.")
            return 0
        results = []
        for raw, settings, todo_cases in jobs:
            llm = get_llm_client(settings)
            raw = run_model(
                raw, todo_cases, rate_card, llm, settings, args.pause, max_tokens=args.max_tokens
            )
            results.append(write_result(raw, all_cases, rate_card))
            if not raw.meta.complete:
                print(
                    f"{raw.meta.model}: stopped early. Continue with --resume {raw.meta.run_id}",
                    file=sys.stderr,
                )

    for result in results:
        _print_summary(result)
        print(f"  Report: {result_path(result.meta.run_id).with_suffix('.md')}")
        print(f"  Raw output: {raw_path(result.meta.run_id)}")
    if len(results) > 1:
        print(f"\nComparison: {write_comparison(results)}")
    return 0 if all(result.meta.complete for result in results) else 1


def _plan(
    args: argparse.Namespace, base: Settings, cases: list[EvalCase]
) -> list[tuple[RawRuns, Settings, list[EvalCase]]] | None:
    """What to run per model, checked against the token budget before any call.

    Returns None, after printing why, if nothing may be run.
    """
    case_ids = [case.id for case in cases]
    unknown = sorted(set(args.stability_cases) - {case.id for case in load_cases()})
    if unknown:
        print(f"error: unknown stability case(s): {', '.join(unknown)}", file=sys.stderr)
        return None

    starts: list[RawRuns] = []
    if args.resume:
        try:
            starts.append(load_raw(args.resume))
        except FileNotFoundError:
            print(f"error: nothing to resume at {raw_path(args.resume)}", file=sys.stderr)
            return None
    else:
        for model in args.model or [base.llm_model]:
            starts.append(
                RawRuns(
                    meta=RunMeta(
                        run_id=f"{timestamp()}-{model_slug(model)}",
                        model=model,
                        temperature=base.llm_temperature,
                        reasoning_effort=base.llm_reasoning_effort,
                        runs_per_case=args.runs,
                        stability_runs=args.stability_runs,
                        stability_cases=[c for c in args.stability_cases if c in case_ids],
                        started_at=_now(),
                    ),
                    runs={},
                )
            )

    history = tokens_per_run()
    jobs: list[tuple[RawRuns, Settings, list[EvalCase]]] = []
    over_budget = False
    for raw in starts:
        meta = raw.meta
        # Cache off: a cached reply would make every run trivially identical.
        # A resumed eval keeps the settings it was started with.
        settings = base.model_copy(
            update={
                "llm_cache": False,
                "llm_model": meta.model,
                "llm_temperature": meta.temperature,
                "llm_reasoning_effort": meta.reasoning_effort,
            }
        )
        todo = raw.missing(case_ids)
        estimate = estimate_tokens(todo, history)
        print(
            f"{meta.model}: {len(todo)} run(s) to make "
            f"({meta.runs_per_case} per case, {meta.stability_runs} on "
            f"{', '.join(meta.stability_cases) or 'no case'}), cache off."
        )
        print(
            f"  Estimated token use: {estimate:,} (budget --max-tokens {args.max_tokens:,}; "
            "Groq's free tier allows 200,000 per model per day)."
        )
        if estimate > args.max_tokens:
            over_budget = True
            print(
                f"  error: the estimate is over the budget by {estimate - args.max_tokens:,} "
                "tokens. Nothing was run. Run fewer cases or runs, or raise --max-tokens.",
                file=sys.stderr,
            )
        jobs.append((raw, settings, cases))
    if over_budget:
        return None
    if not args.dry_run:
        try:
            get_llm_client(jobs[0][1])
        except LLMError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return None
    return jobs


if __name__ == "__main__":
    raise SystemExit(main())
