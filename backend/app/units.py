"""Unit-of-measure normalisation, so "each" and "EA" compare as equal."""

import re

# Canonical unit -> the spellings accepted for it (compared after _clean()).
_ALIASES: dict[str, tuple[str, ...]] = {
    "EA": ("ea", "each", "unit", "units", "pc", "pcs", "piece", "pieces"),
    "LF": (
        "lf", "l f", "lft", "ft", "feet", "foot", "lin ft", "lin feet", "lin foot",
        "linear ft", "linear feet", "linear foot", "lineal ft", "lineal feet",
    ),
    "SF": ("sf", "s f", "sqft", "sq ft", "sq feet", "square ft", "square feet", "square foot"),
    "LB": ("lb", "lbs", "pound", "pounds"),
    "LS": ("ls", "l s", "lump sum", "lumpsum", "lot", "job"),
    "HR": ("hr", "hrs", "hour", "hours"),
    "DAY": ("day", "days"),
}  # fmt: skip
_CANONICAL = {alias: unit for unit, aliases in _ALIASES.items() for alias in aliases}


def _clean(unit: str) -> str:
    """'Lin. Ft.' -> 'lin ft': lower case, punctuation and extra spaces removed."""
    return re.sub(r"[\s._/-]+", " ", unit.casefold()).strip()


def normalize_unit(unit: str) -> str:
    """'each' -> 'EA', 'lin. ft' -> 'LF'. Unknown units come back upper-cased.

    A unit that is not in the table only matches itself (ignoring case and
    punctuation). Nothing is converted between units.
    """
    cleaned = _clean(unit)
    return _CANONICAL.get(cleaned, cleaned.upper())


def units_match(a: str, b: str) -> bool:
    """True if both spell the same unit. A blank unit matches nothing."""
    return bool(_clean(a)) and normalize_unit(a) == normalize_unit(b)
