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
    # Production rates: company data, clearly marked as made up.
    assert len(card.production_rates) == 15
    assert "ILLUSTRATIVE" in card.production_rates_note
    assert all("Illustrative" in rate.notes for rate in card.production_rates)
    spiral = next(r for r in card.production_rates if r.code == "PR-DUCT-SPIRAL-12")
    assert spiral.unit == "LF"
    assert [(c.type, c.rate_card_code, c.quantity_per_unit) for c in spiral.components] == [
        ("material", "MAT-DUCT-SPIRAL-12", D("1")),
        ("labor", "LAB-SHMT", D("0.18")),
    ]


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


def with_production_rate(rate_card, components, code="PR-TSTAT"):
    data = rate_card.model_dump()
    data["production_rates"] = [
        {"code": code, "description": "Thermostat, installed", "unit": "EA", "components": components}
    ]
    return data


def test_production_rate_with_known_codes_is_accepted(rate_card):
    data = with_production_rate(
        rate_card,
        [
            {"type": "material", "rate_card_code": "M-TSTAT", "quantity_per_unit": "1"},
            {"type": "labor", "rate_card_code": "L-TECH", "quantity_per_unit": "1.25"},
        ],
    )

    card = RateCard.model_validate(data)

    assert card.production_rates[0].components[1].quantity_per_unit == D("1.25")


def test_production_rate_with_an_unknown_code_is_rejected(rate_card):
    data = with_production_rate(
        rate_card, [{"type": "labor", "rate_card_code": "L-NOPE", "quantity_per_unit": "1"}]
    )

    with pytest.raises(ValidationError, match="'PR-TSTAT' uses labor code 'L-NOPE'"):
        RateCard.model_validate(data)


def test_production_rate_with_a_code_of_the_wrong_type_is_rejected(rate_card):
    # M-TSTAT exists, but as a material, not as labor.
    data = with_production_rate(
        rate_card, [{"type": "labor", "rate_card_code": "M-TSTAT", "quantity_per_unit": "1"}]
    )

    with pytest.raises(ValidationError, match="not a labor entry"):
        RateCard.model_validate(data)


def test_duplicate_production_rate_codes_are_rejected(rate_card):
    data = with_production_rate(
        rate_card, [{"type": "labor", "rate_card_code": "L-TECH", "quantity_per_unit": "1"}]
    )
    data["production_rates"].append(data["production_rates"][0])

    with pytest.raises(ValidationError, match="duplicate code 'PR-TSTAT' in production_rates"):
        RateCard.model_validate(data)


def test_production_rate_needs_at_least_one_component(rate_card):
    with pytest.raises(ValidationError):
        RateCard.model_validate(with_production_rate(rate_card, []))
