"""The draft pipeline: parse -> extract -> map -> price."""

from pathlib import Path

from pydantic import BaseModel

from app.extraction import SkippedLine, extract_line_items, map_line_items
from app.llm import LLMClient
from app.parsing import ParsedDocument, parse_bid_document
from app.pricing import price_estimate
from app.schemas import BidLineItem, Estimate, RateCard


class DraftResult(BaseModel):
    """The estimate plus the intermediate results a reviewer may want to see."""

    document: ParsedDocument
    skipped: list[SkippedLine]
    lines: list[BidLineItem]
    estimate: Estimate


def draft_estimate(path: str | Path, rate_card: RateCard, llm: LLMClient) -> DraftResult:
    """Turn a bid document into a draft estimate.

    The LLM extracts lines and maps them to rate card codes; every number in
    the estimate is computed by price_estimate().
    """
    document = parse_bid_document(path)
    extraction = extract_line_items(document, llm)
    lines = map_line_items(extraction.lines, rate_card, llm)
    return DraftResult(
        document=document,
        skipped=extraction.skipped,
        lines=lines,
        estimate=price_estimate(lines, rate_card),
    )
