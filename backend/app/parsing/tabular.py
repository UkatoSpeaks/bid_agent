"""Excel and CSV parsing with pandas. Every cell is read as text, untouched."""

import csv
from pathlib import Path

import pandas as pd

from app.parsing.models import CELL_SEPARATOR, NoTextError, ParsedDocument, SourceBlock


def parse_excel(path: Path) -> ParsedDocument:
    # header=None: we do not know which row is the header, so keep them all.
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine="openpyxl")
    blocks: list[SourceBlock] = []
    for sheet_name, frame in sheets.items():
        blocks.extend(_frame_blocks(frame, sheet=str(sheet_name)))
    return _document(path, "excel", blocks)


def parse_csv(path: Path) -> ParsedDocument:
    # Rows may have different lengths (titles, notes), which read_csv rejects
    # unless it is told the widest row up front.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        width = max((len(row) for row in csv.reader(handle)), default=0)
    if width == 0:
        raise NoTextError(f"{path.name} is empty.")
    frame = pd.read_csv(
        path,
        header=None,
        names=list(range(width)),
        dtype=str,
        keep_default_na=False,
        skip_blank_lines=False,
        encoding="utf-8-sig",
    )
    return _document(path, "csv", _frame_blocks(frame, sheet=None))


def _frame_blocks(frame: pd.DataFrame, sheet: str | None) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    for index, values in enumerate(frame.itertuples(index=False, name=None)):
        cells = [_clean(value) for value in values]
        if not any(cells):
            continue
        row_number = index + 1  # matches the row number shown in the spreadsheet
        blocks.append(
            SourceBlock(
                ref=f"{sheet}!R{row_number}" if sheet else f"R{row_number}",
                kind="row",
                text=CELL_SEPARATOR.join(cells),
                cells=cells,
                sheet=sheet,
                row=row_number,
            )
        )
    return blocks


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return ""
    return " ".join(str(value).split())


def _document(path: Path, file_type: str, blocks: list[SourceBlock]) -> ParsedDocument:
    if not blocks:
        raise NoTextError(f"{path.name} contains no data.")
    return ParsedDocument(filename=path.name, file_type=file_type, blocks=blocks)
