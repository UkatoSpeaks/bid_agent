"""LLM call #1: extract bid line items from a parsed document, then verify.

The LLM only copies text out of the document. Everything it returns is then
checked in code against the source rows it cites; nothing is trusted, and
nothing is computed here.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import LLMClient
from app.parsing import ParsedDocument, SourceBlock
from app.schemas import BidLineItem, Flag

# Blocks sent per LLM call. Larger documents are extracted in several calls.
MAX_BLOCKS_PER_CALL = 120


class ExtractedLine(BaseModel):
    """One bid line item, copied from the document by the LLM."""

    item_number: str = Field(description="Item number exactly as written, or '' if none.")
    description: str = Field(description="Description of the work, exactly as written.")
    quantity: str = Field(
        description="Quantity exactly as written in the document, e.g. '1,200' or 'TBD'."
    )
    unit: str = Field(description="Unit exactly as written, e.g. 'EA', 'each', 'LF'.")
    source_ref: str = Field(
        description="The reference in [brackets] of the row or line this item came from."
    )
    notes: str | None = Field(
        description="Anything ambiguous or unclear about this item, else null."
    )
    scope_clarity: Literal["clear", "vague"] = Field(
        description=(
            "'vague' if the description does not say what work or how much of it "
            "is included, else 'clear'."
        )
    )
    scope_reason: str | None = Field(
        description="When scope_clarity is 'vague': one line saying why. Else null."
    )


class ExtractedLines(BaseModel):
    lines: list[ExtractedLine]


class SkippedLine(BaseModel):
    """A row the LLM returned that code recognised as not being a bid item."""

    line: ExtractedLine
    reason: str


class ExtractionResult(BaseModel):
    # Components are still empty; map.py fills them in.
    lines: list[BidLineItem]
    skipped: list[SkippedLine]


_PROMPT = """You are reading a contractor's bid schedule. Extract every bid line item.

Rules:
- Copy item numbers, descriptions, quantities and units exactly as written in the document. Do not reformat numbers: "1,200" stays "1,200" and "TBD" stays "TBD".
- Never compute, estimate or infer a quantity. If no quantity is written for an item, use an empty string and explain in notes.
- Skip rows that are not bid items: column headers, document titles, section titles, subtotal and total rows, and general notes.
- source_ref must be the reference in [brackets] at the start of the row the item came from, copied exactly, without the brackets.
- If anything else about an item is ambiguous (unclear unit, unreadable or missing value), describe it in notes. Do not guess. Use null for notes when nothing is ambiguous.
- scope_clarity: mark every item "clear" or "vague". An item is "vague" when its description does not pin down what work, or how much of it, is included. Signals are phrases such as "as required", "as needed", "misc.", "allowance", "TBD", "per plans", "per specifications" and "etc.", and lump sums with no defined content. For a vague item, give the reason in scope_reason and quote the phrase. For a clear item, scope_reason is null.

Document: {filename}
Each row below starts with its reference in [brackets]. Table cells are separated by " | ".

{rows}"""


def extract_line_items(document: ParsedDocument, llm: LLMClient) -> ExtractionResult:
    """Extract and verify the bid lines of a parsed document."""
    extracted: list[ExtractedLine] = []
    for start in range(0, len(document.blocks), MAX_BLOCKS_PER_CALL):
        chunk = document.blocks[start : start + MAX_BLOCKS_PER_CALL]
        prompt = build_extraction_prompt(document.filename, chunk)
        extracted.extend(llm.structured(prompt, ExtractedLines).lines)
    return verify_extracted_lines(extracted, document)


def build_extraction_prompt(filename: str, blocks: list[SourceBlock]) -> str:
    rows = "\n".join(f"[{block.ref}] {block.text}" for block in blocks)
    return _PROMPT.format(filename=filename, rows=rows)


def verify_extracted_lines(
    extracted: list[ExtractedLine], document: ParsedDocument
) -> ExtractionResult:
    """Check each extracted line against the document. No LLM involved.

    Flags added here:

        * QUANTITY_NOT_NUMERIC (blocker): the quantity is not a number (e.g.
          "TBD" or blank). The line keeps quantity 0, so it prices to 0.
        * UNKNOWN_SOURCE_REF (blocker): the cited row does not exist.
        * QUANTITY_NOT_IN_SOURCE (blocker): the quantity is not written in the
          cited row, so it may be invented.
        * EXTRACTION_NOTE (info): the LLM's own note about an ambiguity.
        * VAGUE_SCOPE (warning): the LLM marked the scope as vague, or the
          description contains a phrase such as "as required" or "misc."
          (checked in code, so it does not depend on the LLM noticing).

    Rows that are plainly headers or (sub)totals are dropped and reported in
    `skipped` instead of being priced.
    """
    lines: list[BidLineItem] = []
    skipped: list[SkippedLine] = []

    for line in extracted:
        reason = _non_item_reason(line)
        if reason:
            skipped.append(SkippedLine(line=line, reason=reason))
            continue

        flags: list[Flag] = []
        quantity_text = line.quantity.strip()
        quantity = parse_quantity(quantity_text)
        if quantity is None:
            flags.append(
                Flag(
                    severity="blocker",
                    code="QUANTITY_NOT_NUMERIC",
                    message=(
                        f"Quantity is written as '{quantity_text}', which is not a "
                        "number. The line is priced with quantity 0 until it is "
                        "filled in."
                    ),
                )
            )

        block = document.block(line.source_ref)
        if block is None:
            flags.append(
                Flag(
                    severity="blocker",
                    code="UNKNOWN_SOURCE_REF",
                    message=(
                        f"Source reference '{line.source_ref}' does not exist in "
                        "the document, so this line could not be checked against it."
                    ),
                )
            )
        elif not quantity_in_source(quantity_text, block.text):
            flags.append(
                Flag(
                    severity="blocker",
                    code="QUANTITY_NOT_IN_SOURCE",
                    message=(
                        f"Quantity '{quantity_text}' does not appear in its source "
                        f"row [{block.ref}]: \"{block.text}\". It may have been "
                        "invented; check the document."
                    ),
                )
            )

        if line.notes and line.notes.strip():
            flags.append(
                Flag(severity="info", code="EXTRACTION_NOTE", message=line.notes.strip())
            )

        vague = _vague_scope_flag(line)
        if vague:
            flags.append(vague)

        lines.append(
            BidLineItem(
                id=f"L{len(lines) + 1:03d}",
                item_number=line.item_number.strip(),
                description=line.description.strip(),
                quantity=quantity if quantity is not None else Decimal("0"),
                unit=line.unit.strip(),
                flags=flags,
                source_ref=block.ref if block else line.source_ref,
            )
        )

    return ExtractionResult(lines=lines, skipped=skipped)


_PLAIN_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_GROUPED_NUMBER = re.compile(r"[+-]?\d{1,3}(,\d{3})+(\.\d*)?")
# Unsigned: in "B-5" or "3-ton" the hyphen is not a minus sign.
_NUMBER_TOKEN = re.compile(r"\d[\d,]*(\.\d+)?|\.\d+")


def parse_quantity(text: str) -> Decimal | None:
    """'480' -> 480, '1,200.5' -> 1200.5; anything else ('TBD', '', '2 x 4') -> None.

    Only removes thousands separators. It does not evaluate or interpret.
    """
    text = text.strip()
    if _GROUPED_NUMBER.fullmatch(text):
        text = text.replace(",", "")
    elif not _PLAIN_NUMBER.fullmatch(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def quantity_in_source(quantity_text: str, source_text: str) -> bool:
    """True if the quantity is written in the source text.

    The match must be a whole number token, so "2" is not found inside "12" or
    "2.5". A numerically identical spelling ("1,200" vs "1200", "480" vs
    "480.0") also counts: that is a formatting difference, not an invention.
    """
    quantity_text = quantity_text.strip()
    if not quantity_text:
        return False

    quantity = parse_quantity(quantity_text)
    if quantity is None:
        # Not a number ("TBD"): look for the same word, ignoring case.
        pattern = rf"(?<!\w){re.escape(quantity_text)}(?!\w)"
        return re.search(pattern, source_text, flags=re.IGNORECASE) is not None

    for match in _NUMBER_TOKEN.finditer(source_text):
        if parse_quantity(match.group().rstrip(",")) == abs(quantity):
            return True
    return False


# Phrases that leave the amount of work open. Matched as whole words, ignoring
# case; label first, pattern second.
_VAGUE_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, flags=re.IGNORECASE))
    for label, pattern in (
        ("as required", r"\bas\s+(?:may\s+be\s+)?required\b"),
        ("as needed", r"\bas\s+needed\b"),
        ("as necessary", r"\bas\s+necessary\b"),
        ("as directed", r"\bas\s+directed\b"),
        ("misc.", r"\bmisc(?:ellaneous)?\b"),
        ("allowance", r"\ballowances?\b"),
        ("TBD", r"\bt\.?b\.?d\b|\bto\s+be\s+determined\b"),
        ("per plans", r"\bper\s+(?:the\s+)?(?:plans?|drawings?|dwgs?)\b"),
        ("per specifications", r"\bper\s+(?:the\s+)?spec(?:s|ifications?)?\b"),
        ("etc.", r"\betc\b"),
    )
)


def vague_phrases(description: str) -> list[str]:
    """The vague-scope phrases found in a description, e.g. ['misc.', 'as required']."""
    return [label for label, pattern in _VAGUE_PHRASES if pattern.search(description)]


def _vague_scope_flag(line: ExtractedLine) -> Flag | None:
    """One VAGUE_SCOPE warning if the LLM or the phrase check says so."""
    reasons: list[str] = []
    if line.scope_clarity == "vague":
        reason = (line.scope_reason or "").strip()
        if reason and reason[-1] not in ".!?":
            reason += "."
        reasons.append(reason or "The LLM marked the scope as vague without a reason.")
    phrases = vague_phrases(line.description)
    if phrases:
        quoted = ", ".join(f"'{phrase}'" for phrase in phrases)
        reasons.append(f"Description contains {quoted}.")
    if not reasons:
        return None
    return Flag(
        severity="warning",
        code="VAGUE_SCOPE",
        message=(
            " ".join(reasons)
            + " Clarify the scope before relying on this line's price."
        ),
    )


_HEADER_QUANTITIES = {"qty", "qty.", "quantity", "quantities"}
_TOTAL_DESCRIPTION = re.compile(
    r"^\W*(sub[\s-]?total|grand\s+total|total|sum)\b", flags=re.IGNORECASE
)


def _non_item_reason(line: ExtractedLine) -> str | None:
    """Why a row is not a bid item, or None if it looks like one.

    The prompt tells the LLM to skip these rows; this catches the ones it
    returns anyway, so a subtotal is never priced as if it were work.
    """
    if line.quantity.strip().casefold() in _HEADER_QUANTITIES:
        return "column header row"
    for text in (line.description, line.item_number):
        if _TOTAL_DESCRIPTION.match(text.strip()):
            return "subtotal / total row"
    if not line.description.strip() and not line.item_number.strip():
        return "row has no item number or description"
    return None
