"""Parsed bid documents: raw rows and text, each with its source location."""

from typing import Literal

from pydantic import BaseModel, Field

CELL_SEPARATOR = " | "


class DocumentParseError(Exception):
    """The bid document could not be parsed."""


class UnsupportedFileTypeError(DocumentParseError):
    """The file extension is not one we can parse."""


class NoTextError(DocumentParseError):
    """The document has no extractable text, e.g. a scanned PDF."""


class SourceBlock(BaseModel):
    """One table row or one line of text, exactly as found in the document."""

    # Unique within the document, and what the LLM cites as its source:
    # "p2-t1-r4" (PDF page 2, table 1, row 4), "p2-l7" (PDF page 2, text
    # line 7), "Base Bid!R5" (Excel sheet + row) or "R5" (CSV row).
    ref: str
    kind: Literal["row", "text"]
    text: str  # cells joined with " | " for rows
    cells: list[str] = Field(default_factory=list)
    page: int | None = None  # PDF, 1-based
    sheet: str | None = None  # Excel
    row: int | None = None  # 1-based: spreadsheet row, or row within a PDF table


class ParsedDocument(BaseModel):
    filename: str
    file_type: Literal["pdf", "excel", "csv"]
    blocks: list[SourceBlock]

    def block(self, ref: str) -> SourceBlock | None:
        """Look up a block by ref, tolerating case and surrounding brackets."""
        wanted = _normalize_ref(ref)
        for block in self.blocks:
            if _normalize_ref(block.ref) == wanted:
                return block
        return None


def _normalize_ref(ref: str) -> str:
    return ref.strip().strip("[]").strip().casefold()
