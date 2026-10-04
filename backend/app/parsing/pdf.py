"""PDF parsing with pdfplumber: tables where found, page text otherwise."""

from pathlib import Path

import pdfplumber

from app.parsing.models import CELL_SEPARATOR, NoTextError, ParsedDocument, SourceBlock


def parse_pdf(path: Path) -> ParsedDocument:
    blocks: list[SourceBlock] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_blocks = _table_blocks(page, page_number)
            if not page_blocks:
                page_blocks = _text_blocks(page, page_number)
            blocks.extend(page_blocks)

    if not blocks:
        raise NoTextError(
            f"{path.name} has no extractable text. It is probably a scanned PDF, "
            "which is not supported yet."
        )
    return ParsedDocument(filename=path.name, file_type="pdf", blocks=blocks)


def _table_blocks(page: "pdfplumber.page.Page", page_number: int) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    for table_number, table in enumerate(page.extract_tables(), start=1):
        for row_number, row in enumerate(table, start=1):
            cells = [_clean(cell) for cell in row]
            if not any(cells):
                continue
            blocks.append(
                SourceBlock(
                    ref=f"p{page_number}-t{table_number}-r{row_number}",
                    kind="row",
                    text=CELL_SEPARATOR.join(cells),
                    cells=cells,
                    page=page_number,
                    row=row_number,
                )
            )
    return blocks


def _text_blocks(page: "pdfplumber.page.Page", page_number: int) -> list[SourceBlock]:
    """One block per line of text, so a source ref stays specific."""
    blocks: list[SourceBlock] = []
    lines = (page.extract_text() or "").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        blocks.append(
            SourceBlock(
                ref=f"p{page_number}-l{line_number}",
                kind="text",
                text=line.strip(),
                page=page_number,
            )
        )
    return blocks


def _clean(cell: str | None) -> str:
    # Cells of merged or empty columns come back as None; wrapped cell text
    # contains newlines.
    return " ".join((cell or "").split())
