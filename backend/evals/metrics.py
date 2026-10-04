"""The eval metrics. Pure functions: no I/O, no LLM, no pricing.

Everything here works on small plain values (item numbers, codes, flags,
totals) so that each function can be checked by hand in a unit test.
"""

import re
from collections import Counter
from collections.abc import Hashable, Sequence
from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel, computed_field

from app.units import normalize_unit

# Flags that follow from the estimate's totals, not from anything on the
# line. They are never required and never counted as noise.
IGNORED_FLAGS = frozenset({"HIGH_IMPACT_LINE"})

MappingOutcome = Literal["correct", "false_none", "false_rate", "wrong_code"]


class Ratio(BaseModel):
    """`num` out of `den`. Kept as counts so that ratios can be added up."""

    num: int = 0
    den: int = 0

    @computed_field
    @property
    def rate(self) -> float | None:
        """num / den, or None when there was nothing to measure."""
        return self.num / self.den if self.den else None

    def __add__(self, other: "Ratio") -> "Ratio":
        return Ratio(num=self.num + other.num, den=self.den + other.den)


class LineMatch(NamedTuple):
    """Indexes into the expected and the actual lines."""

    pairs: list[tuple[int, int]]  # (expected, actual)
    missed: list[int]  # expected lines that did not come back
    extra: list[int]  # actual lines that were not expected


class FlagSeen(NamedTuple):
    code: str
    message: str = ""


def item_key(item_number: str) -> str:
    """'  b-5 ' -> 'B-5': item numbers match ignoring case and spacing."""
    return " ".join(item_number.split()).upper()


def match_lines(expected: Sequence[str], actual: Sequence[str]) -> LineMatch:
    """Pair expected and actual lines by item number.

    An item number written twice (a duplicate) pairs in order of appearance:
    the first expected with the first actual, and so on. Whatever is left
    over on either side is a missed or an extra line.
    """
    waiting: dict[str, list[int]] = {}
    for index, number in enumerate(actual):
        waiting.setdefault(item_key(number), []).append(index)

    pairs: list[tuple[int, int]] = []
    missed: list[int] = []
    for index, number in enumerate(expected):
        candidates = waiting.get(item_key(number))
        if candidates:
            pairs.append((index, candidates.pop(0)))
        else:
            missed.append(index)
    extra = sorted(index for indexes in waiting.values() for index in indexes)
    return LineMatch(pairs, missed, extra)


def line_recall(match: LineMatch) -> Ratio:
    """Share of the expected lines that came back."""
    return Ratio(num=len(match.pairs), den=len(match.pairs) + len(match.missed))


def line_precision(match: LineMatch) -> Ratio:
    """Share of the lines that came back that were expected."""
    return Ratio(num=len(match.pairs), den=len(match.pairs) + len(match.extra))


def quantity_matches(expected: Decimal, actual: Decimal) -> bool:
    """Exact: 1240 equals 1240.0, and nothing else."""
    return expected == actual


def unit_matches(expected: str, actual: str) -> bool:
    """The same unit after normalisation: 'linear feet' equals 'LF'."""
    return normalize_unit(expected) == normalize_unit(actual)


def skipped_rows(skip_refs: Sequence[str], actual_refs: Sequence[str | None]) -> Ratio:
    """Share of the must-skip rows that no bid line was made from."""
    used = {_ref_key(ref) for ref in actual_refs if ref}
    return Ratio(
        num=sum(1 for ref in skip_refs if _ref_key(ref) not in used), den=len(skip_refs)
    )


def _ref_key(ref: str) -> str:
    return ref.strip().strip("[]").strip().casefold()


def mapping_outcome(expected: str | None, actual: str | None) -> MappingOutcome:
    """Compare the chosen production rate code with the expected one.

    None means "no standard rate". "false_none": a standard rate existed and
    the model used none. "false_rate": none exists and the model picked one.
    "wrong_code": both are codes, but different ones.
    """
    if expected == actual:
        return "correct"
    if actual is None:
        return "false_none"
    if expected is None:
        return "false_rate"
    return "wrong_code"


def flag_caught(any_of: Sequence[str], message_matches: str | None, seen: Sequence[FlagSeen]) -> bool:
    """True if one of the flags seen is one of `any_of` (and says the right thing)."""
    for flag in seen:
        if flag.code not in any_of:
            continue
        if message_matches is None or re.search(message_matches, flag.message, re.IGNORECASE):
            return True
    return False


def extra_flags(seen: Sequence[FlagSeen], accepted: Sequence[str]) -> list[str]:
    """The codes seen that were neither required nor allowed: noise."""
    ok = set(accepted) | IGNORED_FLAGS
    return [flag.code for flag in seen if flag.code not in ok]


class TotalError(BaseModel):
    actual: Decimal
    gold: Decimal
    error: Decimal  # actual - gold: positive means the draft is too high
    # |error| as a percentage of the gold total. None if the gold total is 0.
    abs_pct: float | None
    exact: bool


def total_error(actual: Decimal, gold: Decimal) -> TotalError:
    error = actual - gold
    return TotalError(
        actual=actual,
        gold=gold,
        error=error,
        abs_pct=float(abs(error) / gold * 100) if gold else None,
        exact=error == 0,
    )


class Stability(BaseModel):
    runs: int
    distinct: int  # how many different answers the runs gave
    # Share of the runs that gave the most common answer: 1.0 when all agree,
    # 2/3 when one of three differs.
    agreement: float | None
    identical: bool


def stability(values: Sequence[Hashable]) -> Stability:
    """How often repeated runs gave the same answer."""
    if not values:
        return Stability(runs=0, distinct=0, agreement=None, identical=False)
    counts = Counter(values)
    return Stability(
        runs=len(values),
        distinct=len(counts),
        agreement=counts.most_common(1)[0][1] / len(values),
        identical=len(counts) == 1,
    )
