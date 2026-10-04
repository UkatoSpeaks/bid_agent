"""Regenerate the six synthetic eval bid schedules in evals/cases/bids/.

    uv run python evals/make_eval_bids.py

All of them are fictional HVAC bid schedules written to fit
data/rate_cards/hvac_rate_card.json. Each has problems planted on purpose;
the expected answers are in evals/cases/<case>.yaml.

    units_in_words.xlsx       units written in words, quantities with commas
                              and decimals
    split_and_duplicate.xlsx  a description continued on a second row, and an
                              item listed twice
    mismatch_allowance.pdf    a unit that does not fit its standard rate, an
                              allowance line and a total row mid-table
    per_plans_no_rate.pdf     a "per plans" line, an item with no standard
                              rate and item numbers that change format
    split_quantity.xlsx       a line whose quantity is on its second row, a
                              subtotal mid-table, an allowance, units in words
    format_change.pdf         item numbers that change format twice, a
                              duplicate and a bare lump sum

The three sample bids in data/bids/ are the other three eval cases; they are
made by scripts/make_sample_bids.py.
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BIDS_DIR = Path(__file__).resolve().parent / "cases" / "bids"

HEADER = ["Item No.", "Description", "Qty", "Unit"]


def make_units_in_words(path: Path) -> None:
    rows = [
        ["Northline Mechanical - Bid Schedule", None, None, None],
        ["Project: Riverside Branch Library, HVAC Replacement", None, None, None],
        [None, None, None, None],
        HEADER,
        ["1", "Furnish and install 3-ton condensing unit", 3, "each"],
        ["2", "Furnish and install 3-ton air handler", 3, "each"],
        # Quantities with a thousands separator are typed as text, as they
        # are in schedules pasted from a document.
        ["3", "12 in. spiral round duct, installed", "1,240", "linear feet"],
        ["4", "8 in. insulated flexible duct, installed", 312.5, "lin. feet"],
        ["5", "Duct wrap insulation, R-6 foil-faced", "2,150.75", "square feet"],
        ["6", "Refrigerant R-454B, system charge", 18.5, "pounds"],
        ["7", "Programmable thermostat, installed and wired", 3, "units"],
    ]
    _save_workbook(path, "Bid Schedule", rows, header_row=4)


def make_split_and_duplicate(path: Path) -> None:
    rows = [
        HEADER,
        ["101", "Packaged rooftop unit, 10 ton, furnish and install,", 2, "EA"],
        # The description of item 101 runs on into the next row.
        [None, "set by crane (crane by mechanical contractor)", None, None],
        ["102", "Volume control damper, 12 in", 16, "EA"],
        ["103", "Return air grille, 20 x 20", 10, "EA"],
        ["104", "Supply register, 10 x 6", 40, "EA"],
        # Item 103 again, word for word.
        ["103", "Return air grille, 20 x 20", 10, "EA"],
        ["105", "Programmable thermostat, installed and wired", 4, "EA"],
    ]
    _save_workbook(path, "Bid Form", rows, header_row=1)


def make_split_quantity(path: Path) -> None:
    rows = [
        ["Bid Schedule - Maple Court Apartments, Building C", None, None, None],
        [None, None, None, None],
        ["Item", "Description of Work", "Quantity", "Unit of Measure"],
        ["A1", "Split system condensing unit, 3 ton", 5, "Each"],
        ["A2", "Split system air handler, 3 ton", 5, "Each"],
        # Item A3 is split: number and first half here, quantity and unit on
        # the next row.
        ["A3", "Refrigerant line set, 3/8 x 7/8, 50 ft,", None, None],
        [None, "insulated, installed", 5, "Each"],
        [None, "Subtotal - Section A", 15, None],
        ["B1", "Insulated flexible duct, 8 in", 425.5, "Linear Feet"],
        ["B2", "Rectangular galvanized ductwork, fabricated and installed", "4,650", "Pounds"],
        ["B3", "Testing, adjusting and balancing allowance", 1, "Lump Sum"],
    ]
    _save_workbook(path, "Schedule", rows, header_row=3)


def make_mismatch_allowance(path: Path) -> None:
    rows = [
        ["ITEM", "DESCRIPTION", "QTY", "UNIT"],
        ["M-1", "5-ton condensing unit, furnish and install", "2", "EA"],
        ["M-2", "5-ton air handler, furnish and install", "2", "EA"],
        ["M-3", "Refrigerant line set, 3/8 x 7/8, 50 ft, insulated", "2", "EA"],
        # A total in the middle of the table, not worded "Total ..." first.
        ["", "Equipment items total", "6", ""],
        # Duct wrap is priced per SF; this line is in LF.
        ["M-4", "Duct wrap insulation, R-6 foil-faced", "900", "LF"],
        ["M-5", "Galvanized sheet metal ductwork, fabricated and installed", "1,800", "LB"],
        ["M-6", "Controls wiring allowance", "1", "LS"],
        ["M-7", "Supply register, 10 x 6", "24", "EA"],
    ]
    _save_pdf(
        path,
        "Bid Schedule - Oakfield Medical Office, Tenant Improvement",
        "Bid No. 2026-131",
        rows,
        italic_rows=[4],
    )


def make_per_plans_no_rate(path: Path) -> None:
    rows = [
        ["ITEM", "DESCRIPTION OF WORK", "QTY", "UNIT"],
        ["1", "Packaged rooftop unit, 10 ton, set by crane", "1", "EA"],
        ["2", 'Spiral duct, 12" round', "640", "LF"],
        ["3", 'Volume control dampers, 12"', "8", "EA"],
        # From here the item numbers change format.
        ["H-04", "Hydronic unit heater, 60 MBH, furnish and install", "4", "EA"],
        ["H-05", "Ductwork modifications per plans", "1", "LS"],
        ["H-06", "Return air grilles, 20 x 20", "14", "EA"],
        ["7.a", "Thermostats, programmable", "5", "EA"],
        ["7.b", "Refrigerant R-454B, system charge", "22", "LB"],
    ]
    _save_pdf(
        path,
        "Bid Schedule - Fire Station No. 4, Apparatus Bay Heating and Cooling",
        "Bid No. 2026-140",
        rows,
    )


def make_format_change(path: Path) -> None:
    rows = [
        ["NO.", "DESCRIPTION", "QUANTITY", "UNIT"],
        ["1.01", "3-ton condensing unit, furnish and install", "2", "EA"],
        ["1.02", "3-ton air handler, furnish and install", "2", "EA"],
        ["1.03", "Line sets, 50 ft, insulated", "2", "EA"],
        ["Item 4", "Spiral round duct, 12 in", "1,075", "linear feet"],
        ["Item 5", "Flex duct, 8 in, insulated", "260", "linear feet"],
        # Item 5 again, word for word.
        ["Item 5", "Flex duct, 8 in, insulated", "260", "linear feet"],
        ["F", "Supply registers, 10 x 6", "36", "each"],
        # A lump sum with no vague phrase for the code check to find.
        ["G", "Remove and dispose of existing ductwork", "1", "LS"],
    ]
    _save_pdf(
        path,
        "Bid Schedule - Cedar Park Community Center, Gym HVAC",
        "Bid No. 2026-152",
        rows,
    )


def _save_workbook(path: Path, title: str, rows: list[list], header_row: int) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
    sheet.column_dimensions["A"].width = 10
    sheet.column_dimensions["B"].width = 60
    workbook.save(path)


def _save_pdf(
    path: Path,
    heading: str,
    subheading: str,
    rows: list[list[str]],
    italic_rows: list[int] | None = None,
) -> None:
    styles = getSampleStyleSheet()
    story = [
        Paragraph("NORTHLINE MECHANICAL", styles["Title"]),
        Paragraph(heading, styles["Heading3"]),
        Paragraph(subheading, styles["Normal"]),
        Spacer(1, 0.2 * inch),
    ]
    table = Table(rows, colWidths=[0.8 * inch, 4.1 * inch, 0.9 * inch, 1.0 * inch])
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]
    for index in italic_rows or []:
        style.append(("FONTNAME", (0, index), (-1, index), "Helvetica-Oblique"))
    table.setStyle(TableStyle(style))
    story.append(table)

    # invariant=1 keeps the file byte-identical between runs (no timestamps).
    SimpleDocTemplate(str(path), pagesize=letter, invariant=1, title="Bid Schedule").build(story)


BIDS = {
    "units_in_words.xlsx": make_units_in_words,
    "split_and_duplicate.xlsx": make_split_and_duplicate,
    "mismatch_allowance.pdf": make_mismatch_allowance,
    "per_plans_no_rate.pdf": make_per_plans_no_rate,
    "split_quantity.xlsx": make_split_quantity,
    "format_change.pdf": make_format_change,
}


def main() -> None:
    BIDS_DIR.mkdir(parents=True, exist_ok=True)
    for name, make in BIDS.items():
        make(BIDS_DIR / name)
        print(f"wrote {BIDS_DIR / name}")


if __name__ == "__main__":
    main()
