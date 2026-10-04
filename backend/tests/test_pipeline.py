"""End-to-end pipeline and API tests with a fake LLM, plus one live test."""

from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.extraction import ExtractedLines, LineMappings
from app.main import app, llm_client
from app.pipeline import draft_estimate

from tests.conftest import BIDS_DIR, FakeLLMClient


def extracted(item_number, description, quantity, unit, source_ref):
    return {
        "item_number": item_number,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "source_ref": source_ref,
        "notes": None,
        "scope_clarity": "clear",
        "scope_reason": None,
    }


def fake_llm() -> FakeLLMClient:
    """Fixtures for three rows of clean_bid.xlsx: two items and the header."""
    return FakeLLMClient(
        {
            ExtractedLines: [
                {
                    "lines": [
                        # The header row, returned by mistake.
                        extracted("Item No.", "Description", "Qty", "Unit", "Bid Schedule!R1"),
                        extracted(
                            "8",
                            "Programmable thermostat, installed and wired",
                            "6",
                            "EA",
                            "Bid Schedule!R9",
                        ),
                        # The document says 48.
                        extracted("9", "Supply register, 10 x 6", "50", "EA", "Bid Schedule!R10"),
                    ]
                }
            ],
            LineMappings: [
                {
                    "lines": [
                        {
                            "line_id": "L001",
                            "production_rate_code": "PR-TSTAT-PROG",
                            "confidence": "high",
                            "rationale": "Direct match.",
                            "proposed_components": [],
                            "no_match_reason": None,
                        },
                        {
                            # No production rate: the LLM's own numbers.
                            "line_id": "L002",
                            "production_rate_code": None,
                            "confidence": "high",
                            "rationale": "No standard rate chosen.",
                            "proposed_components": [
                                {
                                    "rate_card_code": "MAT-REG-SUP",
                                    "type": "material",
                                    "quantity_per_unit": "1",
                                    "rationale": "One register each.",
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
    # L001 (PR-TSTAT-PROG): 6 x 1 x $145.00 = 870.00 material
    #                       6 x 1.25 x $92.00 = 690.00 labor
    # L002 (assumed):       50 x 1 x $18.50 = 925.00 material
    assert [line.line_subtotal for line in estimate.lines] == [D("1560.00"), D("925.00")]
    assert [line.rate_basis for line in estimate.lines] == ["standard", "assumed"]
    assert estimate.lines[0].source_ref == "Bid Schedule!R9"
    assert len(estimate.lines[0].assumptions) == 3  # the rate and its 2 components

    # Both lines are far above 15% of the subtotal, so L002's assumed rate is
    # a blocker even though the LLM called it "high" confidence.
    assert [(f.line_id, f.severity, f.code) for f in estimate.all_flags] == [
        ("L001", "warning", "HIGH_IMPACT_LINE"),
        ("L002", "blocker", "QUANTITY_NOT_IN_SOURCE"),
        ("L002", "blocker", "ASSUMED_PRODUCTION_RATE"),
        # The company has a rate for supply registers that the LLM did not use.
        ("L002", "warning", "STANDARD_RATE_DECLINED"),
        ("L002", "warning", "HIGH_IMPACT_LINE"),
    ]
    assert estimate.all_flags[3].suggested_production_rate_code == "PR-REG-SUP"

    # direct labor 690.00, direct material 870.00 + 925.00 = 1,795.00
    # markup = 1,795.00 x 15%                = 269.25
    # tax    = (1,795.00 + 269.25) x 7.25%   = 149.658125 -> 149.66
    # subtotal = 690.00 + 1,795.00 + 269.25 + 149.66 = 2,903.91
    totals = estimate.totals
    assert totals.subtotal == D("2903.91")
    assert_foots(estimate)

    # Loaded with markup and tax (x 1.15 x 1.0725 = 1.233375):
    #   L001 = 690.00 + 870.00 x 1.233375 = 1,763.03625
    #   L002 =          925.00 x 1.233375 = 1,140.871875
    #   standard share = 1,763.03625 / 2,903.908125 = 60.71% -> 60.7
    review = estimate.review
    assert (review.standard_rate_pct, review.assumed_rate_pct) == (D("60.7"), D("39.3"))
    assert (review.blocker_count, review.warning_count) == (2, 3)
    assert review.ready_to_approve is False
    assert review.high_impact_line_ids == ["L001", "L002"]

    assert [(row.source_ref, row.reason) for row in estimate.skipped_rows] == [
        ("Bid Schedule!R1", "column header row")
    ]
    # The mapped lines travel with the estimate: they are what a reprice takes.
    assert estimate.source_lines == result.lines


def assert_foots(estimate):
    """Every displayed figure is the exact sum of the figures above it."""
    totals = estimate.totals
    for line in estimate.lines:
        assert line.labor_cost + line.material_cost + line.equipment_cost == line.line_subtotal
    assert sum(line.labor_cost for line in estimate.lines) == totals.direct_labor
    assert sum(line.material_cost for line in estimate.lines) == totals.direct_material
    assert sum(line.equipment_cost for line in estimate.lines) == totals.direct_equipment
    assert (
        totals.direct_labor
        + totals.direct_material
        + totals.material_markup
        + totals.sales_tax
        + totals.direct_equipment
        == totals.subtotal
    )
    assert totals.subtotal + totals.overhead + totals.profit == totals.grand_total
    # Nothing is displayed with more than 2 decimals.
    for amount in totals.model_dump().values():
        assert amount == amount.quantize(D("0.01"))


def test_high_impact_threshold_is_passed_through_the_pipeline(sample_rate_card):
    result = draft_estimate(
        BIDS_DIR / "clean_bid.xlsx", sample_rate_card, fake_llm(), high_impact_pct=D("70")
    )

    estimate = result.estimate
    assert estimate.review.high_impact_line_ids == []
    # Not high-impact any more, so the assumed rate stays a warning.
    assert ("L002", "warning", "ASSUMED_PRODUCTION_RATE") in [
        (f.line_id, f.severity, f.code) for f in estimate.all_flags
    ]


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
    assert [line["line_subtotal"] for line in body["lines"]] == ["1560.00", "925.00"]
    assert body["lines"][0]["production_rate_code"] == "PR-TSTAT-PROG"
    assert "QUANTITY_NOT_IN_SOURCE" in [flag["code"] for flag in body["all_flags"]]
    # The review summary and the rows not treated as bid items are in the API too.
    assert body["review"]["standard_rate_pct"] == "60.7"
    assert body["review"]["assumed_rate_pct"] == "39.3"
    assert body["review"]["blocker_count"] == 2
    assert body["skipped_rows"] == [
        {
            "source_ref": "Bid Schedule!R1",
            "description": "Description",
            "reason": "column header row",
        }
    ]


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
    # Every item in the clean bid has a company production rate.
    assert all(line.rate_basis == "standard" for line in estimate.lines)
    assert estimate.review.standard_rate_pct == D("100.0")
    assert_foots(estimate)
