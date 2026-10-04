"""End-to-end pipeline and API tests with a fake LLM, plus one live test."""

from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.extraction import ExtractedLines, LineMappings
from app.main import app, llm_client
from app.pipeline import draft_estimate

from tests.conftest import BIDS_DIR, FakeLLMClient


def fake_llm() -> FakeLLMClient:
    """Fixtures for two lines of clean_bid.xlsx."""
    return FakeLLMClient(
        {
            ExtractedLines: [
                {
                    "lines": [
                        {
                            "item_number": "8",
                            "description": "Programmable thermostat, installed and wired",
                            "quantity": "6",
                            "unit": "EA",
                            "source_ref": "Bid Schedule!R9",
                            "notes": None,
                        },
                        {
                            "item_number": "9",
                            "description": "Supply register, 10 x 6",
                            "quantity": "50",  # the document says 48
                            "unit": "EA",
                            "source_ref": "Bid Schedule!R10",
                            "notes": None,
                        },
                    ]
                }
            ],
            LineMappings: [
                {
                    "lines": [
                        {
                            "line_id": "L001",
                            "components": [
                                {
                                    "rate_card_code": "MAT-TSTAT-PROG",
                                    "type": "material",
                                    "quantity_per_unit": "1",
                                    "confidence": "high",
                                    "rationale": "Direct match.",
                                },
                                {
                                    "rate_card_code": "LAB-ELEC",
                                    "type": "labor",
                                    "quantity_per_unit": "1.5",
                                    "confidence": "medium",
                                    "rationale": "Assumes 1.5 hours each.",
                                },
                            ],
                            "no_match_reason": None,
                        },
                        {
                            "line_id": "L002",
                            "components": [
                                {
                                    "rate_card_code": "MAT-REG-SUP",
                                    "type": "material",
                                    "quantity_per_unit": "1",
                                    "confidence": "high",
                                    "rationale": "Direct match.",
                                }
                            ],
                            "no_match_reason": None,
                        },
                    ]
                }
            ],
        }
    )


def test_pipeline_parses_extracts_maps_and_prices(sample_rate_card):
    result = draft_estimate(BIDS_DIR / "clean_bid.xlsx", sample_rate_card, fake_llm())

    estimate = result.estimate
    # L001: 6 x 1 x $145.00 = 870.00 material; 6 x 1.5 x $92.00 = 828.00 labor
    # L002: 50 x 1 x $18.50 = 925.00 material
    assert [line.line_subtotal for line in estimate.lines] == [D("1698.00"), D("925.00")]
    assert estimate.lines[0].source_ref == "Bid Schedule!R9"
    assert len(estimate.lines[0].assumptions) == 2
    assert [(f.line_id, f.code) for f in estimate.all_flags] == [
        ("L002", "QUANTITY_NOT_IN_SOURCE")
    ]
    totals = estimate.totals
    assert totals.subtotal + totals.overhead + totals.profit == totals.grand_total


def test_api_draft_estimate_returns_estimate_json():
    app.dependency_overrides[llm_client] = fake_llm
    try:
        with (BIDS_DIR / "clean_bid.xlsx").open("rb") as handle:
            response = TestClient(app).post(
                "/estimates/draft", files={"file": ("clean_bid.xlsx", handle)}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "USD"
    assert [line["line_subtotal"] for line in body["lines"]] == ["1698.00", "925.00"]
    assert body["all_flags"][0]["code"] == "QUANTITY_NOT_IN_SOURCE"


def test_api_rejects_unsupported_file_type():
    app.dependency_overrides[llm_client] = fake_llm
    try:
        response = TestClient(app).post(
            "/estimates/draft", files={"file": ("bid.docx", b"not a bid")}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 415
    assert ".docx" in response.json()["detail"]


@pytest.mark.live
def test_live_clean_bid(sample_rate_card):
    """Calls the real API. Run with: uv run pytest -m live"""
    from app.config import get_settings
    from app.llm import get_llm_client

    # Bypass the response cache, so this really exercises the API.
    llm = get_llm_client(get_settings().model_copy(update={"llm_cache": False}))
    result = draft_estimate(BIDS_DIR / "clean_bid.xlsx", sample_rate_card, llm)

    estimate = result.estimate
    assert len(estimate.lines) == 10
    assert [line.quantity for line in estimate.lines] == [
        D(q) for q in ("4", "4", "2", "2", "6", "480", "350", "6", "48", "12")
    ]
    # A clean document must not trip the hallucination checks.
    assert not [f for f in estimate.all_flags if f.code.startswith("QUANTITY_")]
    assert all(line.line_subtotal > 0 for line in estimate.lines)
    totals = estimate.totals
    assert totals.subtotal + totals.overhead + totals.profit == totals.grand_total
