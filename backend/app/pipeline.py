"""The draft pipeline: parse -> extract -> map -> price -> review."""

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from app.extraction import SkippedLine, extract_line_items, map_line_items
from app.extraction.map import DEFAULT_DECLINED_RATE_SCORE
from app.llm import LLMClient
from app.parsing import ParsedDocument, parse_bid_document
from app.pricing import DEFAULT_HIGH_IMPACT_PCT, price_estimate, review_estimate
from app.schemas import BidLineItem, Estimate, RateCard, SkippedRow


class DraftResult(BaseModel):
    """The estimate plus the intermediate results a reviewer may want to see."""

    document: ParsedDocument
    skipped: list[SkippedLine]
    lines: list[BidLineItem]
    estimate: Estimate


def draft_estimate(
    path: str | Path,
    rate_card: RateCard,
    llm: LLMClient,
    high_impact_pct: Decimal = DEFAULT_HIGH_IMPACT_PCT,
    declined_rate_score: float = DEFAULT_DECLINED_RATE_SCORE,
) -> DraftResult:
    """Turn a bid document into a draft estimate.

    The LLM extracts lines and picks a production rate code for each; every
    number in the estimate is computed by price_estimate(), and
    review_estimate() then flags the lines that matter most by dollar impact.
    """
    document = parse_bid_document(path)
    extraction = extract_line_items(document, llm)
    lines = map_line_items(extraction.lines, rate_card, llm, declined_rate_score)
    estimate = review_estimate(price_estimate(lines, rate_card), rate_card, high_impact_pct)
    estimate = estimate.model_copy(
        update={
            "skipped_rows": [
                SkippedRow(
                    source_ref=skipped.line.source_ref,
                    description=skipped.line.description,
                    reason=skipped.reason,
                )
                for skipped in extraction.skipped
            ],
            "source_lines": lines,
        }
    )
    return DraftResult(
        document=document,
        skipped=extraction.skipped,
        lines=lines,
        estimate=estimate,
    )
