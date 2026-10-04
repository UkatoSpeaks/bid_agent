"""FastAPI application entry point."""

import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile

from app.config import get_settings
from app.llm import LLMClient, LLMConfigError, LLMError, LLMRateLimitError, get_llm_client
from app.parsing import SUPPORTED_EXTENSIONS, DocumentParseError, UnsupportedFileTypeError
from app.pipeline import draft_estimate
from app.pricing import load_rate_card
from app.schemas import Estimate

settings = get_settings()

app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def llm_client() -> LLMClient:
    """Dependency, so tests can swap in a fake client."""
    try:
        return get_llm_client()
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/estimates/draft")
def create_draft_estimate(file: UploadFile, llm: LLMClient = Depends(llm_client)) -> Estimate:
    """Upload a bid schedule (PDF, Excel or CSV) and get back a draft estimate.

    Priced against the default sample rate card for now. The response also
    carries the review summary (`review`) and the rows that were not treated
    as bid items (`skipped_rows`).
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
            ),
        )

    rate_card = load_rate_card(settings.resolved_rate_card_path)
    with tempfile.TemporaryDirectory() as directory:
        # Keep the uploaded name: it appears in the extraction prompt.
        path = Path(directory) / Path(file.filename or f"upload{suffix}").name
        path.write_bytes(file.file.read())
        try:
            result = draft_estimate(path, rate_card, llm, settings.high_impact_line_pct)
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        except DocumentParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LLMRateLimitError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result.estimate
