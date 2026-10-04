"""Check that the pipeline gives the same answer when it is run again.

    uv run python scripts/consistency_check.py
    uv run python scripts/consistency_check.py data/bids/clean_bid.xlsx --runs 5

Runs the full pipeline several times on each bid with the LLM cache disabled,
so every run really calls the API, and reports per bid whether the chosen
production rate codes and the grand total were identical across runs.

Lines priced from a company production rate should be stable: the LLM only
picks a code, and the numbers come from the rate card. Lines with no
production rate rest on quantities guessed by the LLM, and those may differ
from run to run. The report says which kind each unstable line is.

Exit status is 1 if any bid was not identical across runs.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BACKEND_DIR, get_settings  # noqa: E402
from app.llm import LLMError, get_llm_client  # noqa: E402
from app.parsing import DocumentParseError  # noqa: E402
from app.pipeline import draft_estimate  # noqa: E402
from app.pricing import load_rate_card  # noqa: E402
from app.schemas import Estimate, PricedLine  # noqa: E402

ASSUMED = "(assumed by the LLM)"
MISSING = "(line missing)"

SAMPLE_BIDS = [
    BACKEND_DIR / "data" / "bids" / name
    for name in ("clean_bid.xlsx", "messy_bid.pdf", "tricky_bid.xlsx")
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the pipeline repeatedly and compare.")
    parser.add_argument("paths", nargs="*", type=Path, help="bid schedules (default: the samples)")
    parser.add_argument("--runs", type=int, default=3, help="runs per bid (default: 3)")
    parser.add_argument("--rate-card", type=Path, help="rate card JSON (default: from settings)")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    # Cache off: a cached reply would make every run trivially identical.
    settings = get_settings().model_copy(update={"llm_cache": False})
    try:
        rate_card = load_rate_card(args.rate_card or settings.resolved_rate_card_path)
        llm = get_llm_client(settings)
    except (FileNotFoundError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"{args.runs} run(s) per bid, cache disabled. Model {settings.llm_model}, "
        f"temperature {settings.llm_temperature}, "
        f"reasoning effort {settings.llm_reasoning_effort}."
    )

    all_identical = True
    for path in args.paths or SAMPLE_BIDS:
        estimates: list[Estimate] = []
        for run in range(1, args.runs + 1):
            print(f"  running {path.name} ({run}/{args.runs}) ...", file=sys.stderr)
            try:
                result = draft_estimate(path, rate_card, llm, settings.high_impact_line_pct)
            except (FileNotFoundError, DocumentParseError, LLMError) as exc:
                print(f"error: {path.name} run {run}: {exc}", file=sys.stderr)
                return 1
            estimates.append(result.estimate)
        all_identical &= report(path.name, estimates)

    print()
    print("RESULT: " + ("identical across runs" if all_identical else "NOT identical across runs"))
    return 0 if all_identical else 1


def report(name: str, estimates: list[Estimate]) -> bool:
    """Print the comparison for one bid. True if codes and totals all agree."""
    codes = [_codes(estimate) for estimate in estimates]
    totals = [estimate.totals.grand_total for estimate in estimates]
    same_codes = all(run == codes[0] for run in codes)
    same_totals = all(total == totals[0] for total in totals)

    print()
    print("=" * 100)
    print(name)
    print(f"  Production rate codes identical across runs: {_yes_no(same_codes)}")
    print(f"  Grand total identical across runs:           {_yes_no(same_totals)}")
    for run, estimate in enumerate(estimates, start=1):
        review = estimate.review
        print(
            f"    run {run}: {len(estimate.lines):>2} lines   "
            f"grand total {estimate.totals.grand_total:>12,.2f}   "
            f"standard rates {review.standard_rate_pct:>5}%   "
            f"{review.blocker_count} blocker(s), {review.warning_count} warning(s)"
        )

    # One row per line that differs between runs in its code or its cost.
    keys = sorted({key for run in codes for key in run})
    for key in keys:
        chosen = [run.get(key, MISSING) for run in codes]
        costs = [_line_cost(estimate, key) for estimate in estimates]
        same_choice = all(c == chosen[0] for c in chosen)
        if same_choice and all(c == costs[0] for c in costs):
            continue
        if MISSING in chosen:
            kind = "the line was not extracted in every run"
        elif not same_choice:
            kind = "the LLM's choice of production rate changed"
        elif chosen[0] == ASSUMED:
            kind = "no company standard rate: the LLM's guessed quantities changed"
        else:
            kind = "same standard rate but a different cost: check the extracted quantity"
        print(f"  UNSTABLE [{key[0]}] item {key[1] or '-'}: {kind}")
        for run, (code, cost) in enumerate(zip(chosen, costs), start=1):
            print(f"      run {run}: {code:<28} line subtotal {cost:>12}")
    return same_codes and same_totals


def _codes(estimate: Estimate) -> dict[tuple[str, str], str]:
    """Each line's production rate choice, keyed by (source ref, item number)."""
    return {
        (line.source_ref or line.id, line.item_number): _choice(line)
        for line in estimate.lines
    }


def _choice(line: PricedLine) -> str:
    if line.production_rate_code:
        return line.production_rate_code
    return ASSUMED if line.rate_basis == "assumed" else "(not mapped)"


def _line_cost(estimate: Estimate, key: tuple[str, str]) -> str:
    for line in estimate.lines:
        if (line.source_ref or line.id, line.item_number) == key:
            return f"{line.line_subtotal:,.2f}"
    return "-"


def _yes_no(value: bool) -> str:
    return "YES" if value else "NO"


if __name__ == "__main__":
    raise SystemExit(main())
