"""Mapping checks. The LLM is always a fake returning fixtures."""

from decimal import Decimal as D

from app.extraction import LineMappings, map_line_items
from app.extraction.map import LINES_PER_CALL, candidates_for, shortlist
from app.pricing import price_estimate
from app.schemas import BidLineItem, Flag, RateCard

from tests.conftest import FakeLLMClient


def bid_line(line_id="L001", description="Programmable thermostat", quantity="6", unit="EA"):
    return BidLineItem(
        id=line_id,
        item_number=line_id[-1],
        description=description,
        quantity=D(quantity),
        unit=unit,
    )


def component(code, type_, quantity_per_unit, confidence="high", rationale="Direct match."):
    return {
        "rate_card_code": code,
        "type": type_,
        "quantity_per_unit": quantity_per_unit,
        "confidence": confidence,
        "rationale": rationale,
    }


def mapping(line_id, components, no_match_reason=None):
    return {"line_id": line_id, "components": components, "no_match_reason": no_match_reason}


def run_mapping(lines, mappings, rate_card):
    llm = FakeLLMClient({LineMappings: [{"lines": mappings}]})
    return map_line_items(lines, rate_card, llm), llm


def codes(line):
    return [(flag.severity, flag.code) for flag in line.flags]


def test_valid_mapping_gives_components_and_records_assumptions(sample_rate_card):
    mapped, llm = run_mapping(
        [bid_line()],
        [
            mapping(
                "L001",
                [
                    component("MAT-TSTAT-PROG", "material", "1"),
                    component(
                        "LAB-ELEC",
                        "labor",
                        "1.5",
                        confidence="medium",
                        rationale="Assumes 1.5 hours to mount and wire each thermostat.",
                    ),
                ],
            )
        ],
        sample_rate_card,
    )

    line = mapped[0]
    assert [(c.type, c.rate_card_code, c.quantity_per_unit) for c in line.components] == [
        ("material", "MAT-TSTAT-PROG", D("1")),
        ("labor", "LAB-ELEC", D("1.5")),
    ]
    assert line.flags == []
    assert line.assumptions == [
        "Material MAT-TSTAT-PROG (Programmable thermostat): 1 EA per EA "
        "[high confidence] Direct match.",
        "Labor LAB-ELEC (Electrician): 1.5 hrs per EA "
        "[medium confidence] Assumes 1.5 hours to mount and wire each thermostat.",
    ]

    # The prompt lists codes and names, never prices.
    _schema, prompt = llm.calls[0]
    assert "material | MAT-TSTAT-PROG | Programmable thermostat | EA" in prompt
    assert "145.00" not in prompt and "92.00" not in prompt

    # Ready for the pricing engine: 6 x 1 x $145.00 + 6 x 1.5 x $92.00 = 1,698.00
    estimate = price_estimate(mapped, sample_rate_card)
    assert estimate.lines[0].line_subtotal == D("1698.00")
    assert estimate.lines[0].assumptions == line.assumptions


def test_unknown_code_is_dropped_with_a_blocker(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line()],
        [
            mapping(
                "L001",
                [
                    component("MAT-TSTAT-WIFI", "material", "1"),  # invented
                    component("LAB-ELEC", "labor", "1.5"),
                ],
            )
        ],
        sample_rate_card,
    )

    line = mapped[0]
    assert [c.rate_card_code for c in line.components] == ["LAB-ELEC"]
    assert codes(line) == [("blocker", "UNKNOWN_RATE_CODE")]
    assert "MAT-TSTAT-WIFI" in line.flags[0].message
    assert len(line.assumptions) == 1  # only the component that was kept


def test_code_under_the_wrong_type_is_dropped_with_a_blocker(sample_rate_card):
    # LAB-ELEC exists, but it is labor, not material.
    mapped, _ = run_mapping(
        [bid_line()],
        [mapping("L001", [component("LAB-ELEC", "material", "1")])],
        sample_rate_card,
    )

    assert mapped[0].components == []
    assert codes(mapped[0]) == [("blocker", "UNKNOWN_RATE_CODE")]


def test_low_confidence_gives_a_warning_and_keeps_the_component(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Misc. ductwork modifications as required", quantity="1", unit="LS")],
        [
            mapping(
                "L001",
                [
                    component(
                        "LAB-SHMT",
                        "labor",
                        "16",
                        confidence="low",
                        rationale="Scope is undefined; assumes two days of sheet metal work.",
                    )
                ],
            )
        ],
        sample_rate_card,
    )

    line = mapped[0]
    assert [c.quantity_per_unit for c in line.components] == [D("16")]
    assert codes(line) == [("warning", "LOW_CONFIDENCE_MAPPING")]
    assert "two days" in line.flags[0].message
    assert "[low confidence]" in line.assumptions[0]


def test_no_match_keeps_the_reason_and_the_engine_blocks_the_line(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Kitchen exhaust hood fire suppression system", quantity="1")],
        [mapping("L001", [], no_match_reason="No fire suppression entries in the rate card.")],
        sample_rate_card,
    )

    line = mapped[0]
    assert line.components == []
    assert codes(line) == [("warning", "NO_RATE_CARD_MATCH")]

    estimate = price_estimate(mapped, sample_rate_card)
    assert [(f.severity, f.code) for f in estimate.all_flags] == [
        ("warning", "NO_RATE_CARD_MATCH"),
        ("blocker", "NO_COMPONENTS"),
    ]
    assert estimate.totals.grand_total == D("0.00")


def test_invalid_quantity_per_unit_is_dropped_with_a_blocker(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line()],
        [
            mapping(
                "L001",
                [
                    component("MAT-TSTAT-PROG", "material", "one"),
                    component("LAB-ELEC", "labor", "-2"),
                ],
            )
        ],
        sample_rate_card,
    )

    assert mapped[0].components == []
    assert codes(mapped[0]) == [
        ("blocker", "INVALID_QUANTITY_PER_UNIT"),
        ("blocker", "INVALID_QUANTITY_PER_UNIT"),
    ]


def test_line_missing_from_the_llm_reply_gets_a_blocker(sample_rate_card):
    lines = [bid_line("L001"), bid_line("L002")]
    mapped, _ = run_mapping(
        lines,
        [mapping("L002", [component("MAT-TSTAT-PROG", "material", "1")])],
        sample_rate_card,
    )

    assert codes(mapped[0]) == [("blocker", "MAPPING_MISSING")]
    assert mapped[1].flags == []


def test_existing_flags_are_kept_and_input_lines_are_not_modified(sample_rate_card):
    line = bid_line()
    line.flags.append(Flag(severity="info", code="EXTRACTION_NOTE", message="check"))

    mapped, _ = run_mapping(
        [line],
        [mapping("L001", [component("MAT-TSTAT-PROG", "material", "1", confidence="low")])],
        sample_rate_card,
    )

    assert [f.code for f in mapped[0].flags] == ["EXTRACTION_NOTE", "LOW_CONFIDENCE_MAPPING"]
    assert [f.code for f in line.flags] == ["EXTRACTION_NOTE"]
    assert line.components == []


def test_lines_are_mapped_in_batches(sample_rate_card):
    lines = [bid_line(f"L{n:03d}") for n in range(1, LINES_PER_CALL + 2)]

    def reply(prompt):
        # Answer for whichever lines this prompt contains.
        return {
            "lines": [
                mapping(line.id, [component("MAT-TSTAT-PROG", "material", "1")])
                for line in lines
                if f"\n{line.id} | " in prompt
            ]
        }

    llm = FakeLLMClient({LineMappings: [reply, reply]})
    mapped = map_line_items(lines, sample_rate_card, llm)

    assert len(llm.calls) == 2
    assert [line.id for line in mapped] == [line.id for line in lines]
    assert all(len(line.components) == 1 for line in mapped)


def test_small_rate_card_is_sent_whole(sample_rate_card):
    candidates = candidates_for([bid_line()], sample_rate_card)

    assert len(candidates) == 24  # 5 labor + 15 materials + 4 equipment


def test_shortlist_ranks_similar_entries_first(sample_rate_card):
    top = shortlist("Programmable thermostat, installed and wired", sample_rate_card, per_type=3)

    materials = [c.code for c in top if c.type == "material"]
    assert len(materials) == 3
    assert materials[0] == "MAT-TSTAT-PROG"
    assert len([c for c in top if c.type == "labor"]) == 3


def test_large_rate_card_is_shortlisted(sample_rate_card):
    data = sample_rate_card.model_dump()
    data["materials"] += [
        {"code": f"MAT-PIPE-{n}", "name": f"Copper pipe, type L, size {n}", "unit": "LF", "unit_cost": "9"}
        for n in range(30)
    ]
    big_card = RateCard.model_validate(data)

    candidates = candidates_for([bid_line()], big_card)

    materials = [c.code for c in candidates if c.type == "material"]
    assert len(materials) == 8
    assert "MAT-TSTAT-PROG" in materials
    # Small sections still come through whole.
    assert len([c for c in candidates if c.type == "labor"]) == 5
