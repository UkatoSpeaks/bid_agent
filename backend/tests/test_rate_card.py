from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.main import health
from app.pricing import load_rate_card, price_estimate
from app.schemas import RateCard

from tests.conftest import make_line


def test_sample_rate_card_loads_and_validates():
    card = load_rate_card(get_settings().resolved_rate_card_path)

    assert isinstance(card, RateCard)
    assert card.company_name == "Northline Mechanical"
    assert card.trade == "HVAC"
    assert card.currency == "USD"
    assert 4 <= len(card.labor_rates) <= 5
    assert 12 <= len(card.materials) <= 15
    assert 3 <= len(card.equipment) <= 4
    # Money is Decimal, never float.
    assert all(isinstance(r.hourly_rate, D) for r in card.labor_rates)
    assert isinstance(card.markups.sales_tax_pct_on_materials, D)


def test_sample_rate_card_prices_a_line():
    # labor:    2 x 6 hrs x $85.00   = 1,020.00  (LAB-TECH)
    # material: 2 x 1 EA  x $2,450.00 = 4,900.00  (MAT-CU-3T)
    card = load_rate_card(get_settings().resolved_rate_card_path)
    line = make_line("1", "2", [("labor", "LAB-TECH", "6"), ("material", "MAT-CU-3T", "1")])

    estimate = price_estimate([line], card)

    assert estimate.lines[0].line_subtotal == D("5920.00")
    assert estimate.all_flags == []


def test_duplicate_codes_are_rejected(rate_card):
    data = rate_card.model_dump()
    data["materials"].append(data["materials"][0])

    with pytest.raises(ValidationError, match="duplicate code"):
        RateCard.model_validate(data)


def test_health():
    assert health() == {"status": "ok"}
