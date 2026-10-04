"""Eval cases: a bid schedule plus its expected answers (evals/cases/*.yaml).

The expected answers are written by hand. Each file starts with the comment
"# VERIFIED BY HAND: yes" or "# VERIFIED BY HAND: no", which records whether
a person has checked it against the bid document.
"""

import re
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.extraction.extract import parse_quantity
from app.parsing import ParsedDocument, parse_bid_document
from app.schemas import RateCard

EVALS_DIR = Path(__file__).resolve().parent
CASES_DIR = EVALS_DIR / "cases"
RESULTS_DIR = EVALS_DIR / "results"

# What an expected file writes for "no standard production rate covers this".
NO_RATE = "none"

_VERIFIED = re.compile(r"^#\s*VERIFIED BY HAND:\s*(yes|no)\s*$", flags=re.IGNORECASE)


class CaseError(ValueError):
    """An expected-answer file is malformed or does not fit its bid document."""


class _Strict(BaseModel):
    # Reject unknown keys so a typo in an expected file fails loudly.
    model_config = ConfigDict(extra="forbid")


class FlagSpec(_Strict):
    """A flag that must appear on a line: any one of `any_of` satisfies it.

    `message_matches` (a regex, case-insensitive) narrows it to flags whose
    message says the right thing, e.g. an EXTRACTION_NOTE about a duplicate.
    """

    any_of: list[str] = Field(min_length=1)
    message_matches: str | None = None
    # What the message must say, in words, for the reports.
    meaning: str | None = None

    @property
    def label(self) -> str:
        label = " or ".join(self.any_of)
        if self.message_matches:
            label += " that " + (self.meaning or f"matches /{self.message_matches}/")
        return label


class ExpectedLine(_Strict):
    item_number: str
    # For the person checking the file; not scored.
    description: str
    # As a plain number ("1240", "312.5"), or the text written in the
    # document when it has no number ("TBD"): such a line must come back with
    # quantity 0.
    quantity: str
    unit: str
    # A production rate code from the rate card, or "none".
    production_rate: str
    required_flags: list[FlagSpec] = Field(default_factory=list)
    # Flags that are a correct reaction to this line but are not required.
    # They do not count as noise.
    allowed_flags: list[str] = Field(default_factory=list)
    # The problem planted on this line, in a few words.
    problem: str | None = None

    @field_validator("required_flags", mode="before")
    @classmethod
    def _bare_codes(cls, value: object) -> object:
        # "VAGUE_SCOPE" is short for {any_of: [VAGUE_SCOPE]}.
        if isinstance(value, list):
            return [{"any_of": [item]} if isinstance(item, str) else item for item in value]
        return value

    @property
    def rate_code(self) -> str | None:
        """The expected production rate code, or None for "none"."""
        return None if self.production_rate.strip().casefold() == NO_RATE else self.production_rate

    @property
    def quantity_value(self) -> Decimal:
        """The quantity the pipeline should end up with: 0 if none is written."""
        quantity = parse_quantity(self.quantity)
        return quantity if quantity is not None else Decimal("0")


class SkipRow(_Strict):
    """A row of the document that must not come back as a bid line."""

    ref: str
    text: str  # the row as parsed, so the file can be checked without the tool
    why: str


class EvalCase(_Strict):
    id: str
    title: str
    # Relative to the expected file.
    bid_file: str
    planted_problems: list[str] = Field(default_factory=list)
    lines: list[ExpectedLine]
    skip_rows: list[SkipRow] = Field(default_factory=list)
    # Not in the YAML: set by load_case().
    verified_by_hand: bool = False
    bid_path: Path | None = None
    expected_path: Path | None = None


def read_verified(text: str) -> bool:
    """True if the file's first line is "# VERIFIED BY HAND: yes"."""
    first = text.splitlines()[0] if text else ""
    match = _VERIFIED.match(first.strip())
    if match is None:
        raise CaseError('first line must be "# VERIFIED BY HAND: yes" or "# VERIFIED BY HAND: no"')
    return match.group(1).casefold() == "yes"


def load_case(path: Path) -> EvalCase:
    text = path.read_text(encoding="utf-8")
    try:
        verified = read_verified(text)
        case = EvalCase.model_validate(yaml.safe_load(text))
    except (CaseError, ValueError, yaml.YAMLError) as exc:
        raise CaseError(f"{path.name}: {exc}") from exc
    bid_path = (path.parent / case.bid_file).resolve()
    if not bid_path.is_file():
        raise CaseError(f"{path.name}: bid file not found: {bid_path}")
    return case.model_copy(
        update={"verified_by_hand": verified, "bid_path": bid_path, "expected_path": path}
    )


def load_cases(directory: Path = CASES_DIR, only: list[str] | None = None) -> list[EvalCase]:
    """Every case in `directory`, by file name; `only` keeps the named ids."""
    cases = [load_case(path) for path in sorted(directory.glob("*.yaml"))]
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise CaseError(f"duplicate case ids in {directory}")
    if only:
        unknown = sorted(set(only) - set(ids))
        if unknown:
            raise CaseError(f"unknown case(s): {', '.join(unknown)}. Known: {', '.join(ids)}")
        cases = [case for case in cases if case.id in only]
    return cases


def check_case(case: EvalCase, rate_card: RateCard, document: ParsedDocument | None = None) -> None:
    """Raise CaseError if the expected answers cannot be right for this bid.

    Catches slips in a hand-written file: a production rate code that is not
    in the rate card, a skip row that is not in the document or reads
    differently, an expected line whose item number is written nowhere.
    """
    document = document or parse_bid_document(case.bid_path)
    codes = {rate.code for rate in rate_card.production_rates}
    problems: list[str] = []
    for line in case.lines:
        if line.rate_code is not None and line.rate_code not in codes:
            problems.append(
                f"item {line.item_number}: production rate '{line.rate_code}' is not in the rate card"
            )
        if not any(line.item_number in block.cells for block in document.blocks):
            problems.append(f"item {line.item_number}: no row of the document has this item number")
    for row in case.skip_rows:
        block = document.block(row.ref)
        if block is None:
            problems.append(f"skip row {row.ref}: no such row in the document")
        elif block.text.strip() != row.text.strip():
            problems.append(f"skip row {row.ref}: the document reads \"{block.text}\"")
    if problems:
        raise CaseError(f"{case.id}: " + "; ".join(problems))
