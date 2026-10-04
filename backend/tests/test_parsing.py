import pytest
from reportlab.pdfgen import canvas

from app.parsing import (
    NoTextError,
    UnsupportedFileTypeError,
    parse_bid_document,
)

from tests.conftest import BIDS_DIR


def test_clean_bid_xlsx_keeps_every_row_with_sheet_and_row():
    document = parse_bid_document(BIDS_DIR / "clean_bid.xlsx")

    assert document.file_type == "excel"
    assert len(document.blocks) == 11  # header + 10 items
    header, first = document.blocks[0], document.blocks[1]
    assert header.cells == ["Item No.", "Description", "Qty", "Unit"]
    assert first.ref == "Bid Schedule!R2"
    assert (first.sheet, first.row, first.page) == ("Bid Schedule", 2, None)
    assert first.cells == ["1", "Furnish and install 3-ton condensing unit", "4", "EA"]
    assert first.text == "1 | Furnish and install 3-ton condensing unit | 4 | EA"
    # Whole numbers are read as written, not as floats ("480.0").
    assert document.block("Bid Schedule!R7").cells[2] == "480"


def test_messy_bid_pdf_uses_table_rows_with_page_numbers():
    document = parse_bid_document(BIDS_DIR / "messy_bid.pdf")

    assert document.file_type == "pdf"
    assert all(block.kind == "row" and block.page == 1 for block in document.blocks)
    texts = [block.text for block in document.blocks]
    assert "A2 | 5-ton split system: condensing unit | 2 | each" in texts
    assert 'B1 | Spiral duct, 12" round | 1,150 | LF' in texts
    # Section titles and the subtotal row are kept: parsing does not interpret.
    assert any(text.startswith("SECTION A - EQUIPMENT") for text in texts)
    assert any("Subtotal Section A" in text for text in texts)
    block = document.block("p1-t1-r3")
    assert block.cells == ["A1", "Packaged rooftop unit, 10 ton, set by crane", "3", "EA"]
    assert block.row == 3


def test_tricky_bid_xlsx_reads_both_sheets():
    document = parse_bid_document(BIDS_DIR / "tricky_bid.xlsx")

    assert {block.sheet for block in document.blocks} == {"Base Bid", "Alternates"}
    # The blank row 3 is skipped, and row numbers still match the spreadsheet.
    assert document.block("Base Bid!R3") is None
    assert document.block("Base Bid!R9").cells == [
        "B-5",
        "Refrigerant R-454B, system charge",
        "TBD",
        "LB",
    ]
    assert document.block("Base Bid!R7").cells[2] == "1850.5"
    assert document.block("Alternates!R3").cells[0] == "ALT-1"


def test_block_lookup_tolerates_brackets_and_case():
    document = parse_bid_document(BIDS_DIR / "tricky_bid.xlsx")

    assert document.block("[base bid!r5]").ref == "Base Bid!R5"
    assert document.block("Nope!R1") is None


def test_csv_with_ragged_rows(tmp_path):
    path = tmp_path / "bid.csv"
    path.write_text(
        "Bid Schedule\n\nItem,Description,Qty,Unit\n1,\"Thermostat, programmable\",6,EA\n",
        encoding="utf-8",
    )

    document = parse_bid_document(path)

    assert document.file_type == "csv"
    assert [block.ref for block in document.blocks] == ["R1", "R3", "R4"]
    assert document.block("R4").cells == ["1", "Thermostat, programmable", "6", "EA"]


def test_pdf_without_tables_falls_back_to_text_lines(tmp_path):
    path = tmp_path / "text_only.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(72, 720, "1  Programmable thermostat  6 EA")
    pdf.drawString(72, 700, "2  Supply register  48 EA")
    pdf.save()

    document = parse_bid_document(path)

    assert [(block.ref, block.kind, block.page) for block in document.blocks] == [
        ("p1-l1", "text", 1),
        ("p1-l2", "text", 1),
    ]
    assert document.blocks[1].text == "2 Supply register 48 EA"


def test_scanned_pdf_with_no_text_raises_clear_error(tmp_path):
    path = tmp_path / "scan.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.rect(72, 600, 200, 100, fill=1)  # ink, but no text layer
    pdf.save()

    with pytest.raises(NoTextError, match="scanned PDF"):
        parse_bid_document(path)


def test_unsupported_file_type_raises_clear_error(tmp_path):
    path = tmp_path / "bid.docx"
    path.write_bytes(b"not a bid")

    with pytest.raises(UnsupportedFileTypeError, match=r"\.docx"):
        parse_bid_document(path)


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_bid_document(BIDS_DIR / "does_not_exist.xlsx")
