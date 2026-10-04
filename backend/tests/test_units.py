import pytest

from app.units import normalize_unit, units_match


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("EA", "EA"),
        ("each", "EA"),
        ("Each", "EA"),
        ("ea.", "EA"),
        ("LF", "LF"),
        ("lin. ft", "LF"),
        ("lin ft", "LF"),
        ("Linear Feet", "LF"),
        ("L.F.", "LF"),
        ("SF", "SF"),
        ("sq. ft.", "SF"),
        ("lbs", "LB"),
        ("LS", "LS"),
        ("Lump Sum", "LS"),
        ("hrs", "HR"),
        (" day ", "DAY"),
        ("ton", "TON"),  # not in the table: only upper-cased
        ("", ""),
    ],
)
def test_normalize_unit(unit, expected):
    assert normalize_unit(unit) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("each", "EA", True),
        ("lin. ft", "LF", True),
        ("LS", "LF", False),
        ("SF", "LF", False),
        ("ton", "TON", True),
        ("", "", False),  # a missing unit never matches
        ("", "EA", False),
    ],
)
def test_units_match(a, b, expected):
    assert units_match(a, b) is expected
