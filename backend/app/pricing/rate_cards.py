"""Rate card loading. Kept apart from engine.py so the engine stays I/O-free."""

from pathlib import Path

from app.schemas import RateCard


def load_rate_card(path: str | Path) -> RateCard:
    """Read a rate card JSON file and validate it into a RateCard.

    Raises FileNotFoundError if the file is missing and
    pydantic.ValidationError if its contents are not a valid rate card.
    """
    return RateCard.model_validate_json(Path(path).read_text(encoding="utf-8"))
