"""Draft an estimate from a bid schedule and print it.

    uv run python scripts/draft_estimate.py data/bids/clean_bid.xlsx
    uv run python scripts/draft_estimate.py data/bids/clean_bid.xlsx --json

Parses the document, extracts the lines (LLM), maps each to a company
production rate (LLM), prices them (pricing engine), reviews them by dollar
impact and prints the estimate with its flags and calculation traces.
"""

import argparse
import logging
import sys
import textwrap
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.llm import LLMError, get_llm_client  # noqa: E402
from app.parsing import DocumentParseError  # noqa: E402
from app.pipeline import DraftResult, draft_estimate  # noqa: E402
from app.pricing import load_rate_card  # noqa: E402
from app.schemas import RateCard  # noqa: E402

WIDTH = 100
SEVERITY_ORDER = {"blocker": 0, "warning": 1, "info": 2}
RATE_BASIS = {
    "standard": "company standard",
    "assumed": "ASSUMED by the LLM",
    "none": "not priced",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft an estimate from a bid schedule.")
    parser.add_argument("path", type=Path, help="bid schedule (.pdf, .xlsx, .xlsm, .csv)")
    parser.add_argument("--rate-card", type=Path, help="rate card JSON (default: from settings)")
    parser.add_argument("--json", action="store_true", help="print the Estimate as JSON")
    args = parser.parse_args()

    # Bid documents and LLM rationales contain characters (non-breaking hyphens,
    # inch marks) that the default Windows console encoding cannot represent.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    settings = get_settings()
    try:
        rate_card = load_rate_card(args.rate_card or settings.resolved_rate_card_path)
        result = draft_estimate(
            args.path, rate_card, get_llm_client(settings), settings.high_impact_line_pct
        )
    except (FileNotFoundError, DocumentParseError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(result.estimate.model_dump_json(indent=2))
    else:
        print_estimate(result, rate_card)
    return 0


def print_estimate(result: DraftResult, rate_card: RateCard) -> None:
    estimate = result.estimate
    currency = estimate.currency

    print("=" * WIDTH)
    print(f"DRAFT ESTIMATE: {result.document.filename}")
    print(f"Rate card: {rate_card.company_name} ({rate_card.trade}), {currency}")
    print(f"{len(estimate.lines)} line(s), {len(result.document.blocks)} source row(s) read")
    print("=" * WIDTH)

    for line in estimate.lines:
        print()
        title = f"[{line.id}] Item {line.item_number or '-'}: {line.description}"
        _wrapped(title, indent="", subsequent="    ")
        print(
            f"    Quantity: {_number(line.quantity)} {line.unit}"
            f"    Source: {line.source_ref or '-'}"
            f"    Line subtotal: {_money(line.line_subtotal, currency)}"
        )
        share = (
            f"{line.subtotal_share_pct}% of subtotal"
            if line.subtotal_share_pct is not None
            else "share of subtotal n/a"
        )
        print(f"    Rates: {RATE_BASIS[line.rate_basis]}    {share}")
        if line.assumptions:
            print("    Assumptions:")
            for assumption in line.assumptions:
                _wrapped(assumption, indent="      - ", subsequent="        ")
        print("    Calculation:")
        for step in line.calculation_trace:
            _wrapped(step, indent="      ", subsequent="        ")
        if line.flags:
            print("    Flags:")
            for flag in sorted(line.flags, key=lambda f: SEVERITY_ORDER[f.severity]):
                _wrapped(
                    f"[{flag.severity.upper()}] {flag.code}: {flag.message}",
                    indent="      ",
                    subsequent="        ",
                )

    if estimate.skipped_rows:
        print()
        print("-" * WIDTH)
        print("ROWS NOT TREATED AS BID ITEMS")
        for row in estimate.skipped_rows:
            _wrapped(
                f"[{row.source_ref}] {row.description}: {row.reason}",
                indent="  ",
                subsequent="    ",
            )

    totals = estimate.totals
    markups = rate_card.markups
    print()
    print("-" * WIDTH)
    print("TOTALS")
    rows = [
        ("Direct labor", totals.direct_labor),
        ("Direct material", totals.direct_material),
        (f"Material markup ({_number(markups.material_markup_pct)}%)", totals.material_markup),
        (
            f"Sales tax on materials ({_number(markups.sales_tax_pct_on_materials)}%)",
            totals.sales_tax,
        ),
        ("Direct equipment", totals.direct_equipment),
        ("Subtotal", totals.subtotal),
        (f"Overhead ({_number(markups.overhead_pct)}%)", totals.overhead),
        (f"Profit ({_number(markups.profit_pct)}%)", totals.profit),
        ("GRAND TOTAL", totals.grand_total),
    ]
    for label, amount in rows:
        print(f"  {label:<36}{_money(amount, currency):>16}")

    review = estimate.review
    print()
    print("-" * WIDTH)
    print("REVIEW SUMMARY")
    print(
        f"  Based on company standard production rates: {review.standard_rate_pct}% "
        f"of the subtotal ({review.lines_on_standard_rates} line(s))"
    )
    print(
        f"  Resting on production rates assumed by the LLM: {review.assumed_rate_pct}% "
        f"of the subtotal ({review.lines_on_assumed_rates} line(s))"
    )
    print(f"  Lines not priced: {review.lines_not_priced}")
    print(
        f"  High-impact lines (above {_number(review.high_impact_threshold_pct)}% of the "
        f"subtotal): {', '.join(review.high_impact_line_ids) or 'none'}"
    )
    print(
        f"  Flags: {review.blocker_count} blocker(s), {review.warning_count} warning(s), "
        f"{review.info_count} info"
    )
    for flag in sorted(estimate.all_flags, key=lambda f: SEVERITY_ORDER[f.severity]):
        if flag.severity == "info":
            continue
        print(f"    [{flag.severity.upper()}] {flag.line_id} {flag.code}")
    if review.blocker_count:
        print()
        print("  This draft has blockers: do not rely on the grand total until they are resolved.")


def _wrapped(text: str, indent: str, subsequent: str) -> None:
    print(
        textwrap.fill(text, width=WIDTH, initial_indent=indent, subsequent_indent=subsequent)
    )


# Display only: nothing here feeds back into a calculation.


def _number(value: Decimal) -> str:
    return f"{value.normalize():,f}"


def _money(amount: Decimal, currency: str) -> str:
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{prefix}{amount:,.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
