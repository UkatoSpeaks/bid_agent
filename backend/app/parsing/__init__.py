"""Bid document parsing: file in, raw rows and text with source locations out."""

from pathlib import Path

from app.parsing.models import (
    DocumentParseError,
    NoTextError,
    ParsedDocument,
    SourceBlock,
    UnsupportedFileTypeError,
)

__all__ = [
    "DocumentParseError",
    "NoTextError",
    "ParsedDocument",
    "SourceBlock",
    "SUPPORTED_EXTENSIONS",
    "UnsupportedFileTypeError",
    "parse_bid_document",
]

SUPPORTED_EXTENSIONS = (".pdf", ".xlsx", ".xlsm", ".csv")


def parse_bid_document(path: str | Path) -> ParsedDocument:
    """Parse a bid schedule into raw rows / text lines, no interpretation.

    Raises FileNotFoundError if the file is missing, UnsupportedFileTypeError
    for anything other than PDF, Excel (.xlsx/.xlsm) or CSV, and NoTextError
    for a document with nothing to read (e.g. a scanned PDF).
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{suffix or path.name}'. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    if not path.is_file():
        raise FileNotFoundError(f"Bid document not found: {path}")

    # Imported here so that pdfplumber / pandas load only when needed.
    if suffix == ".pdf":
        from app.parsing.pdf import parse_pdf

        return parse_pdf(path)
    if suffix == ".csv":
        from app.parsing.tabular import parse_csv

        return parse_csv(path)
    from app.parsing.tabular import parse_excel

    return parse_excel(path)
