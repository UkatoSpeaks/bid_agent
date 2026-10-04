"""The synthetic sample bid schedules in data/bids/ (see scripts/make_sample_bids.py)."""

from pathlib import Path

from pydantic import BaseModel

from app.config import BACKEND_DIR

BIDS_DIR = BACKEND_DIR / "data" / "bids"


class SampleBid(BaseModel):
    id: str
    filename: str
    title: str
    description: str


SAMPLE_BIDS = [
    SampleBid(
        id="clean",
        filename="clean_bid.xlsx",
        title="Clean bid",
        description="A tidy Excel table of 10 items, each with a company production rate.",
    ),
    SampleBid(
        id="messy",
        filename="messy_bid.pdf",
        title="Messy bid",
        description=(
            "A PDF with section titles, a subtotal row, inconsistent units and one vague item."
        ),
    ),
    SampleBid(
        id="tricky",
        filename="tricky_bid.xlsx",
        title="Tricky bid",
        description=(
            'Two Excel sheets, an item with no rate card match and a quantity written as "TBD".'
        ),
    ),
]


def sample_bid_path(sample_id: str) -> Path | None:
    """The file of a sample bid, or None if there is no such sample."""
    for sample in SAMPLE_BIDS:
        if sample.id == sample_id:
            return BIDS_DIR / sample.filename
    return None
