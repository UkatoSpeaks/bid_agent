"""Mapping checks. The LLM is always a fake returning fixtures."""

from decimal import Decimal as D

from app.extraction import LineMappings, map_line_items
from app.extraction.map import (
    LINES_PER_CALL,
    candidates_for,
    production_rates_for,
    shortlist,
    shortlist_production_rates,
)
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


def component(code, type_, quantity_per_unit, rationale="Assumes a typical install."):
    return {
        "rate_card_code": code,
        "type": type_,
        "quantity_per_unit": quantity_per_unit,
        "rationale": rationale,
    }


def standard(line_id, code, confidence="high", rationale="Direct match.", proposed=()):
    """The LLM picked a production rate."""
    return {
        "line_id": line_id,
        "production_rate_code": code,
        "confidence": confidence,
        "rationale": rationale,
        "proposed_components": list(proposed),
        "no_match_reason": None,
    }


def assumed(line_id, components, confidence="medium", rationale="No standard rate fits.",
            no_match_reason=None):  # fmt: skip
    """The LLM found no production rate and proposed its own components."""
    return {
        "line_id": line_id,
        "production_rate_code": None,
        "confidence": confidence,
        "rationale": rationale,
        "proposed_components": components,
        "no_match_reason": no_match_reason,
    }


def run_mapping(lines, mappings, rate_card):
    llm = FakeLLMClient({LineMappings: [{"lines": mappings}]})
    return map_line_items(lines, rate_card, llm), llm


def codes(line):
    return [(flag.severity, flag.code) for flag in line.flags]


def test_production_rate_is_expanded_into_the_companys_components(sample_rate_card):
    # The LLM only names PR-TSTAT-PROG. The components come from the rate
    # card: 1 EA of MAT-TSTAT-PROG and 1.25 hrs of LAB-ELEC per thermostat.
    mapped, llm = run_mapping(
        [bid_line()], [standard("L001", "PR-TSTAT-PROG")], sample_rate_card
    )

    line = mapped[0]
    assert line.production_rate_code == "PR-TSTAT-PROG"
    assert [(c.type, c.rate_card_code, c.quantity_per_unit) for c in line.components] == [
        ("material", "MAT-TSTAT-PROG", D("1")),
        ("labor", "LAB-ELEC", D("1.25")),
    ]
    assert line.flags == []
    assert line.assumptions == [
        "Standard production rate PR-TSTAT-PROG (Programmable thermostat, installed "
        "and wired), per EA [high confidence] Direct match.",
        "Material MAT-TSTAT-PROG (Programmable thermostat): 1 EA per EA "
        "[company standard PR-TSTAT-PROG]",
        "Labor LAB-ELEC (Electrician): 1.25 hrs per EA [company standard PR-TSTAT-PROG]",
    ]

    # The prompt lists production rates by code, description and unit. It
    # never shows a price or the hours inside a production rate.
    _schema, prompt = llm.calls[0]
    assert "PR-TSTAT-PROG | Programmable thermostat, installed and wired | EA" in prompt
    assert "material | MAT-TSTAT-PROG | Programmable thermostat | EA" in prompt
    assert "145.00" not in prompt and "92.00" not in prompt
    assert "1.25" not in prompt

    # Ready for the pricing engine: 6 x 1 x $145.00 + 6 x 1.25 x $92.00 = 1,560.00
    estimate = price_estimate(mapped, sample_rate_card)
    assert estimate.lines[0].line_subtotal == D("1560.00")
    assert estimate.lines[0].rate_basis == "standard"
    assert estimate.lines[0].production_rate_code == "PR-TSTAT-PROG"
    assert estimate.lines[0].assumptions == line.assumptions


def test_multi_component_production_rate_expands_every_component(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Packaged rooftop unit, 10 ton, set by crane", quantity="3")],
        [standard("L001", "PR-RTU-10T-CRANE")],
        sample_rate_card,
    )

    assert [(c.rate_card_code, c.quantity_per_unit) for c in mapped[0].components] == [
        ("MAT-RTU-10T", D("1")),
        ("LAB-TECH", D("12")),
        ("LAB-APPR", D("8")),
        ("LAB-ELEC", D("4")),
        ("LAB-SUPV", D("2")),
        ("EQ-CRANE-40T", D("3")),
    ]


def test_quantities_proposed_alongside_a_production_rate_are_ignored(sample_rate_card):
    # A chosen standard rate wins: the LLM's own 4 hours never reach pricing.
    mapped, _ = run_mapping(
        [bid_line()],
        [
            standard(
                "L001", "PR-TSTAT-PROG", proposed=[component("LAB-ELEC", "labor", "4")]
            )
        ],
        sample_rate_card,
    )

    line = mapped[0]
    assert [(c.rate_card_code, c.quantity_per_unit) for c in line.components] == [
        ("MAT-TSTAT-PROG", D("1")),
        ("LAB-ELEC", D("1.25")),
    ]
    assert codes(line) == [("info", "PROPOSED_COMPONENTS_IGNORED")]


def test_unknown_production_rate_is_a_blocker_and_nothing_is_priced(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line()],
        [
            standard(
                "L001",
                "PR-TSTAT-WIFI",  # invented
                proposed=[component("LAB-ELEC", "labor", "1")],
            )
        ],
        sample_rate_card,
    )

    line = mapped[0]
    assert line.components == []
    assert line.production_rate_code is None
    assert codes(line) == [("blocker", "UNKNOWN_PRODUCTION_RATE")]
    assert "PR-TSTAT-WIFI" in line.flags[0].message


def test_medium_confidence_in_a_standard_rate_is_not_flagged(sample_rate_card):
    # "medium" now only says the bid line left a detail open. The numbers are
    # the company's either way, and the confidence is shown in the assumptions.
    mapped, _ = run_mapping(
        [bid_line(description="Supply registers", quantity="64", unit="Each")],
        [standard("L001", "PR-REG-SUP", confidence="medium", rationale="No size stated.")],
        sample_rate_card,
    )

    assert mapped[0].flags == []
    assert "[medium confidence] No size stated." in mapped[0].assumptions[0]


def test_low_confidence_in_a_standard_rate_gives_a_warning(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Thermostat", quantity="2")],
        [standard("L001", "PR-TSTAT-PROG", confidence="low", rationale="Type not stated.")],
        sample_rate_card,
    )

    line = mapped[0]
    assert len(line.components) == 2
    assert codes(line) == [("warning", "LOW_CONFIDENCE_MAPPING")]
    assert "Type not stated." in line.flags[0].message


def test_assumed_production_rate_is_flagged_even_at_high_confidence(sample_rate_card):
    # No standard rate for refrigerant recovery, so the LLM proposes its own
    # numbers. "high" confidence does not make them company data.
    for confidence in ("high", "medium", "low"):
        mapped, _ = run_mapping(
            [bid_line(description="Recover refrigerant from existing unit", quantity="3")],
            [
                assumed(
                    "L001",
                    [
                        component("LAB-TECH", "labor", "1.5"),
                        component("EQ-RECOVERY", "equipment", "0.125"),
                    ],
                    confidence=confidence,
                )
            ],
            sample_rate_card,
        )

        line = mapped[0]
        assert line.production_rate_code is None
        assert [(c.rate_card_code, c.quantity_per_unit) for c in line.components] == [
            ("LAB-TECH", D("1.5")),
            ("EQ-RECOVERY", D("0.125")),
        ]
        assert ("warning", "ASSUMED_PRODUCTION_RATE") in codes(line)
        # The flag lists each guessed number.
        message = next(f.message for f in line.flags if f.code == "ASSUMED_PRODUCTION_RATE")
        assert "1.5 hrs per EA of LAB-TECH (HVAC Technician)" in message
        assert "0.125 day per EA of EQ-RECOVERY (Refrigerant recovery machine)" in message
        assert all("[ASSUMED by the LLM" in a for a in line.assumptions)
        # Low confidence adds its own warning on top.
        assert (("warning", "LOW_CONFIDENCE_MAPPING") in codes(line)) == (confidence == "low")

        assert price_estimate(mapped, sample_rate_card).lines[0].rate_basis == "assumed"


def test_unit_mismatch_is_a_blocker_and_the_components_are_not_priced(sample_rate_card):
    # PR-DUCT-SPIRAL-12 is per LF; the bid line is a lump sum.
    mapped, _ = run_mapping(
        [bid_line(description="Spiral duct, 12 in round", quantity="1", unit="LS")],
        [standard("L001", "PR-DUCT-SPIRAL-12")],
        sample_rate_card,
    )

    line = mapped[0]
    assert line.components == []
    assert line.production_rate_code == "PR-DUCT-SPIRAL-12"  # the choice is kept
    assert codes(line) == [("blocker", "UNIT_MISMATCH")]
    assert "'LS'" in line.flags[0].message and "per LF" in line.flags[0].message

    estimate = price_estimate(mapped, sample_rate_card)
    assert estimate.lines[0].line_subtotal == D("0.00")
    assert estimate.lines[0].rate_basis == "none"


def test_differently_spelled_units_are_not_a_mismatch(sample_rate_card):
    lines = [
        bid_line("L001", "Spiral duct, 12 in round", "100", unit="lin. ft"),
        bid_line("L002", "Thermostats, programmable", "11", unit="Each"),
        bid_line("L003", "Refrigerant line sets, 50 ft", "2", unit="ea."),
    ]
    mapped, _ = run_mapping(
        lines,
        [
            standard("L001", "PR-DUCT-SPIRAL-12"),
            standard("L002", "PR-TSTAT-PROG"),
            standard("L003", "PR-LINESET-50"),
        ],
        sample_rate_card,
    )

    assert all(line.flags == [] and line.components for line in mapped)
    # 100 x 1 x $11.50 + 100 x 0.18 x $78.00 = 1,150.00 + 1,404.00 = 2,554.00
    assert price_estimate(mapped, sample_rate_card).lines[0].line_subtotal == D("2554.00")


def test_unknown_code_is_dropped_with_a_blocker(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line()],
        [
            assumed(
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
    assert codes(line) == [
        ("blocker", "UNKNOWN_RATE_CODE"),
        ("warning", "ASSUMED_PRODUCTION_RATE"),
        # "Programmable thermostat" has a company rate the LLM did not use.
        ("warning", "STANDARD_RATE_DECLINED"),
    ]
    assert "MAT-TSTAT-WIFI" in line.flags[0].message
    assert len(line.assumptions) == 1  # only the component that was kept


def test_code_under_the_wrong_type_is_dropped_with_a_blocker(sample_rate_card):
    # LAB-ELEC exists, but it is labor, not material.
    mapped, _ = run_mapping(
        [bid_line()],
        [assumed("L001", [component("LAB-ELEC", "material", "1")])],
        sample_rate_card,
    )

    assert mapped[0].components == []
    assert codes(mapped[0]) == [
        ("blocker", "UNKNOWN_RATE_CODE"),
        ("warning", "STANDARD_RATE_DECLINED"),
    ]


def test_no_match_keeps_the_reason_and_the_engine_blocks_the_line(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Kitchen exhaust hood fire suppression system", quantity="1")],
        [assumed("L001", [], no_match_reason="No fire suppression entries in the rate card.")],
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
            assumed(
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
        ("warning", "STANDARD_RATE_DECLINED"),
    ]


def test_line_missing_from_the_llm_reply_gets_a_blocker(sample_rate_card):
    lines = [bid_line("L001"), bid_line("L002")]
    mapped, _ = run_mapping(lines, [standard("L002", "PR-TSTAT-PROG")], sample_rate_card)

    assert codes(mapped[0]) == [("blocker", "MAPPING_MISSING")]
    assert mapped[1].flags == []


def test_existing_flags_are_kept_and_input_lines_are_not_modified(sample_rate_card):
    line = bid_line()
    line.flags.append(Flag(severity="info", code="EXTRACTION_NOTE", message="check"))

    mapped, _ = run_mapping(
        [line], [standard("L001", "PR-TSTAT-PROG", confidence="low")], sample_rate_card
    )

    assert [f.code for f in mapped[0].flags] == ["EXTRACTION_NOTE", "LOW_CONFIDENCE_MAPPING"]
    assert [f.code for f in line.flags] == ["EXTRACTION_NOTE"]
    assert line.components == []
    assert line.production_rate_code is None


def test_lines_are_mapped_in_batches(sample_rate_card):
    lines = [bid_line(f"L{n:03d}") for n in range(1, LINES_PER_CALL + 2)]

    def reply(prompt):
        # Answer for whichever lines this prompt contains.
        return {
            "lines": [
                standard(line.id, "PR-TSTAT-PROG")
                for line in lines
                if f"\n{line.id} | " in prompt
            ]
        }

    llm = FakeLLMClient({LineMappings: [reply, reply]})
    mapped = map_line_items(lines, sample_rate_card, llm)

    assert len(llm.calls) == 2
    assert [line.id for line in mapped] == [line.id for line in lines]
    assert all(len(line.components) == 2 for line in mapped)


def test_small_rate_card_is_sent_whole(sample_rate_card):
    assert len(candidates_for([bid_line()], sample_rate_card)) == 24  # 5 + 15 + 4
    assert len(production_rates_for([bid_line()], sample_rate_card)) == 15


def test_shortlist_ranks_similar_entries_first(sample_rate_card):
    top = shortlist("Programmable thermostat, installed and wired", sample_rate_card, per_type=3)

    materials = [c.code for c in top if c.type == "material"]
    assert len(materials) == 3
    assert materials[0] == "MAT-TSTAT-PROG"
    assert len([c for c in top if c.type == "labor"]) == 3


def test_production_rate_shortlist_ranks_similar_descriptions_first(sample_rate_card):
    top = shortlist_production_rates('Spiral duct, 12" round', sample_rate_card, limit=3)

    assert len(top) == 3
    assert top[0].code == "PR-DUCT-SPIRAL-12"


def test_large_rate_card_is_shortlisted(sample_rate_card):
    data = sample_rate_card.model_dump()
    data["materials"] += [
        {"code": f"MAT-PIPE-{n}", "name": f"Copper pipe, type L, size {n}", "unit": "LF", "unit_cost": "9"}
        for n in range(30)
    ]
    data["production_rates"] += [
        {
            "code": f"PR-PIPE-{n}",
            "description": f"Copper pipe, type L, size {n}, installed",
            "unit": "LF",
            "components": [
                {"type": "material", "rate_card_code": f"MAT-PIPE-{n}", "quantity_per_unit": "1"}
            ],
        }
        for n in range(30)
    ]
    big_card = RateCard.model_validate(data)

    candidates = candidates_for([bid_line()], big_card)

    materials = [c.code for c in candidates if c.type == "material"]
    assert len(materials) == 8
    assert "MAT-TSTAT-PROG" in materials
    # Small sections still come through whole.
    assert len([c for c in candidates if c.type == "labor"]) == 5

    production_rates = [rate.code for rate in production_rates_for([bid_line()], big_card)]
    assert len(production_rates) == 8
    assert "PR-TSTAT-PROG" in production_rates


# STANDARD_RATE_DECLINED: the LLM used no production rate although one matches.


def declined_flags(line):
    return [flag for flag in line.flags if flag.code == "STANDARD_RATE_DECLINED"]


def test_declined_standard_rate_is_flagged_with_the_rate_to_apply(sample_rate_card):
    # The case from the consistency check: "Supply registers" has a company
    # rate (PR-REG-SUP), but the LLM guessed its own numbers instead.
    mapped, _ = run_mapping(
        [bid_line(description="Supply registers", quantity="64", unit="Each")],
        [
            assumed(
                "L001",
                [
                    component("MAT-REG-SUP", "material", "1"),
                    component("LAB-TECH", "labor", "0.5"),
                ],
            )
        ],
        sample_rate_card,
    )

    line = mapped[0]
    assert codes(line) == [
        ("warning", "ASSUMED_PRODUCTION_RATE"),
        ("warning", "STANDARD_RATE_DECLINED"),
    ]
    flag = declined_flags(line)[0]
    assert flag.suggested_production_rate_code == "PR-REG-SUP"
    assert "PR-REG-SUP (Supply register, 10 x 6, installed), per EA" in flag.message
    assert "score 100 of 100, threshold 85" in flag.message
    # The flag only suggests: the line still carries the LLM's own numbers.
    assert line.production_rate_code is None
    assert [c.quantity_per_unit for c in line.components] == [D("1"), D("0.5")]


def test_declined_flag_is_raised_when_the_llm_maps_nothing_at_all(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Return air grille, 20 x 20")],
        [assumed("L001", [], no_match_reason="Not sure which rate applies.")],
        sample_rate_card,
    )

    assert codes(mapped[0]) == [
        ("warning", "STANDARD_RATE_DECLINED"),
        ("warning", "NO_RATE_CARD_MATCH"),
    ]
    assert declined_flags(mapped[0])[0].suggested_production_rate_code == "PR-GRILLE-RET"


def test_no_declined_flag_when_no_production_rate_is_close(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Recover refrigerant from existing rooftop units", quantity="3")],
        [assumed("L001", [component("LAB-TECH", "labor", "2")])],
        sample_rate_card,
    )

    assert codes(mapped[0]) == [("warning", "ASSUMED_PRODUCTION_RATE")]


def test_no_declined_flag_when_the_llm_chose_a_production_rate(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line(description="Supply registers", quantity="64")],
        [standard("L001", "PR-REG-SUP")],
        sample_rate_card,
    )

    assert mapped[0].flags == []


def test_declined_flag_ignores_rates_in_another_unit(sample_rate_card):
    # PR-REG-SUP is per EA. Applied to a lump sum it would only be a
    # UNIT_MISMATCH, so it is not suggested.
    mapped, _ = run_mapping(
        [bid_line(description="Supply registers", quantity="1", unit="LS")],
        [assumed("L001", [component("MAT-REG-SUP", "material", "64")])],
        sample_rate_card,
    )

    assert declined_flags(mapped[0]) == []


def test_declined_score_threshold_is_configurable(sample_rate_card):
    # "Add return air grille, 20 x 20, at corridor" scores 81 against
    # PR-GRILLE-RET: under the default threshold of 85, over one of 80.
    line = bid_line(description="Add return air grille, 20 x 20, at corridor")
    mapping = assumed("L001", [component("MAT-GRILLE-RET", "material", "1")])

    default = map_line_items(
        [line], sample_rate_card, FakeLLMClient({LineMappings: [{"lines": [mapping]}]})
    )
    lowered = map_line_items(
        [line],
        sample_rate_card,
        FakeLLMClient({LineMappings: [{"lines": [mapping]}]}),
        declined_rate_score=80,
    )

    assert declined_flags(default[0]) == []
    assert declined_flags(lowered[0])[0].suggested_production_rate_code == "PR-GRILLE-RET"


def test_llm_confidence_and_rationale_are_kept_on_the_line(sample_rate_card):
    mapped, _ = run_mapping(
        [bid_line()],
        [standard("L001", "PR-TSTAT-PROG", confidence="medium", rationale="No model stated.")],
        sample_rate_card,
    )

    assert mapped[0].mapping_confidence == "medium"
    assert mapped[0].mapping_rationale == "No model stated."
