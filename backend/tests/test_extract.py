"""Extraction checks. The LLM is always a fake returning fixtures."""

from decimal import Decimal as D

import pytest

from app.extraction import ExtractedLines, extract_line_items
from app.extraction.extract import parse_quantity, quantity_in_source
from app.parsing import parse_bid_document

from tests.conftest import BIDS_DIR, FakeLLMClient


def extracted(item_number, description, quantity, unit, source_ref, notes=None):
    return {
        "item_number": item_number,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "source_ref": source_ref,
        "notes": notes,
    }


def run_extraction(filename, lines):
    document = parse_bid_document(BIDS_DIR / filename)
    llm = FakeLLMClient({ExtractedLines: [{"lines": lines}]})
    return extract_line_items(document, llm), llm


def codes(line):
    return [(flag.severity, flag.code) for flag in line.flags]


def test_clean_line_is_extracted_without_flags():
    result, llm = run_extraction(
        "clean_bid.xlsx",
        [extracted("6", "12 in. spiral round duct, installed", "480", "LF", "Bid Schedule!R7")],
    )

    line = result.lines[0]
    assert (line.id, line.item_number, line.quantity, line.unit) == ("L001", "6", D("480"), "LF")
    assert line.source_ref == "Bid Schedule!R7"
    assert line.components == []
    assert line.flags == []
    # The prompt shows each row with the reference the LLM must cite.
    _schema, prompt = llm.calls[0]
    assert "[Bid Schedule!R7] 6 | 12 in. spiral round duct, installed | 480 | LF" in prompt


def test_made_up_quantity_is_caught_as_not_in_source():
    # The row says 480 LF; the fake LLM claims 520.
    result, _ = run_extraction(
        "clean_bid.xlsx",
        [extracted("6", "12 in. spiral round duct, installed", "520", "LF", "Bid Schedule!R7")],
    )

    line = result.lines[0]
    assert codes(line) == [("blocker", "QUANTITY_NOT_IN_SOURCE")]
    assert "520" in line.flags[0].message
    assert "Bid Schedule!R7" in line.flags[0].message


def test_quantity_taken_from_another_row_is_caught():
    # 480 is a real number in the document, but not in the row cited (R8: 350).
    result, _ = run_extraction(
        "clean_bid.xlsx",
        [extracted("7", "8 in. insulated flexible duct", "480", "LF", "Bid Schedule!R8")],
    )

    assert codes(result.lines[0]) == [("blocker", "QUANTITY_NOT_IN_SOURCE")]


def test_quantity_must_match_a_whole_number_not_part_of_one():
    # Row R11 is "10 | Return air grille, 20 x 20 | 12 | EA": "2" and "1"
    # appear only inside other numbers.
    result, _ = run_extraction(
        "clean_bid.xlsx",
        [extracted("10", "Return air grille, 20 x 20", "2", "EA", "Bid Schedule!R11")],
    )

    assert codes(result.lines[0]) == [("blocker", "QUANTITY_NOT_IN_SOURCE")]


def test_source_ref_that_does_not_exist_is_a_blocker():
    result, _ = run_extraction(
        "clean_bid.xlsx",
        [extracted("99", "Chiller, 200 ton", "1", "EA", "Bid Schedule!R99")],
    )

    assert codes(result.lines[0]) == [("blocker", "UNKNOWN_SOURCE_REF")]


def test_tbd_quantity_becomes_a_blocker_and_prices_at_zero():
    result, _ = run_extraction(
        "tricky_bid.xlsx",
        [extracted("B-5", "Refrigerant R-454B, system charge", "TBD", "LB", "Base Bid!R9")],
    )

    line = result.lines[0]
    assert line.quantity == D("0")
    # "TBD" is in the source row, so it is not a hallucination, only unusable.
    assert codes(line) == [("blocker", "QUANTITY_NOT_NUMERIC")]
    assert "TBD" in line.flags[0].message


def test_thousands_separator_quantity_parses_and_is_found_in_source():
    result, _ = run_extraction(
        "messy_bid.pdf",
        [extracted("B1", 'Spiral duct, 12" round', "1,150", "LF", "p1-t1-r9")],
    )

    line = result.lines[0]
    assert line.quantity == D("1150")
    assert line.flags == []


def test_notes_become_info_flags():
    result, _ = run_extraction(
        "messy_bid.pdf",
        [
            extracted(
                "B5",
                "Misc. ductwork modifications as required",
                "1",
                "LS",
                "p1-t1-r13",
                notes="Scope is vague: 'as required' is not quantified.",
            )
        ],
    )

    line = result.lines[0]
    assert codes(line) == [("info", "EXTRACTION_NOTE")]
    assert line.flags[0].message == "Scope is vague: 'as required' is not quantified."


def test_header_and_subtotal_rows_returned_by_the_llm_are_not_priced():
    # The prompt says to skip these; here the fake LLM returns them anyway.
    result, _ = run_extraction(
        "messy_bid.pdf",
        [
            extracted("ITEM", "DESCRIPTION OF WORK", "QTY", "UNIT", "p1-t1-r1"),
            extracted("A1", "Packaged rooftop unit, 10 ton, set by crane", "3", "EA", "p1-t1-r3"),
            extracted("", "Subtotal Section A", "9", "", "p1-t1-r7"),
        ],
    )

    assert [line.item_number for line in result.lines] == ["A1"]
    assert result.lines[0].id == "L001"
    assert [(s.line.source_ref, s.reason) for s in result.skipped] == [
        ("p1-t1-r1", "column header row"),
        ("p1-t1-r7", "subtotal / total row"),
    ]


def test_section_title_returned_as_an_item_is_blocked_not_priced():
    # Not recognisable as a header or total, so it is kept, but with no
    # numeric quantity it carries a blocker and quantity 0.
    result, _ = run_extraction(
        "messy_bid.pdf",
        [extracted("", "SECTION A - EQUIPMENT", "", "", "p1-t1-r2")],
    )

    line = result.lines[0]
    assert line.quantity == D("0")
    assert ("blocker", "QUANTITY_NOT_NUMERIC") in codes(line)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("480", D("480")),
        ("1,200", D("1200")),
        ("1,850.5", D("1850.5")),
        (" 12.50 ", D("12.50")),
        ("TBD", None),
        ("", None),
        ("2 x 4", None),
        ("12 EA", None),
        ("1,20", None),  # not a thousands separator
        ("1e3", None),
        ("NaN", None),
    ],
)
def test_parse_quantity(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize(
    ("quantity", "source", "expected"),
    [
        ("12", "10 | Return air grille, 20 x 20 | 12 | EA", True),
        ("2", "10 | Return air grille, 20 x 20 | 12 | EA", False),
        ("1,150", "B1 | Spiral duct | 1,150 | LF", True),
        ("1150", "B1 | Spiral duct | 1,150 | LF", True),  # same number, other spelling
        ("480", "6 | Spiral duct | 480.0 | LF", True),
        ("5", "B-5 | Refrigerant | 5 | LB", True),
        ("2", "A | Duct | 2.5 | LF", False),
        ("TBD", "B-5 | Refrigerant | tbd | LB", True),
        ("TBD", "B-5 | Refrigerant | 40 | LB", False),
        ("", "B-5 | Refrigerant |  | LB", False),
    ],
)
def test_quantity_in_source(quantity, source, expected):
    assert quantity_in_source(quantity, source) is expected
