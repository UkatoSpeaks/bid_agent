"""FastAPI application entry point."""

import re
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import get_settings
from app.export import AuditEntry, build_workbook
from app.llm import LLMClient, LLMConfigError, LLMError, LLMRateLimitError, get_llm_client
from app.parsing import SUPPORTED_EXTENSIONS, DocumentParseError, UnsupportedFileTypeError
from app.pipeline import draft_estimate
from app.pricing import LineEdit, ReviewerEditError, apply_reviewer_edits, load_rate_card
from app.samples import SAMPLE_BIDS, SampleBid, sample_bid_path
from app.schemas import BidLineItem, Estimate, RateCard, SkippedRow

settings = get_settings()

# Sent with 502/503 responses so a client can tell the causes apart without
# parsing the message.
ERROR_CODE_HEADER = "X-Error-Code"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=[ERROR_CODE_HEADER, "Content-Disposition"],
)


class RepriceRequest(BaseModel):
    """The draft's lines, unchanged, plus everything the reviewer has edited."""

    # Estimate.source_lines of the draft.
    lines: list[BidLineItem]
    edits: list[LineEdit] = Field(default_factory=list)
    # Passed through so the response is a complete Estimate.
    skipped_rows: list[SkippedRow] = Field(default_factory=list)


class ExportRequest(RepriceRequest):
    audit_log: list[AuditEntry] = Field(default_factory=list)
    source_filename: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def llm_client() -> LLMClient:
    """Dependency, so tests can swap in a fake client."""
    try:
        return get_llm_client()
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
            headers={ERROR_CODE_HEADER: "llm_not_configured"},
        ) from exc


def rate_card() -> RateCard:
    """Dependency: the rate card every estimate is priced against."""
    return load_rate_card(settings.resolved_rate_card_path)


@app.get("/rate-card")
def get_rate_card(card: RateCard = Depends(rate_card)) -> RateCard:
    """The rate card in use, including its production rates."""
    return card


@app.get("/samples")
def list_samples() -> list[SampleBid]:
    """The sample bid schedules that can be drafted without an upload."""
    return SAMPLE_BIDS


@app.post("/estimates/draft")
def create_draft_estimate(
    file: UploadFile,
    llm: LLMClient = Depends(llm_client),
    card: RateCard = Depends(rate_card),
) -> Estimate:
    """Upload a bid schedule (PDF, Excel or CSV) and get back a draft estimate.

    Priced against the default sample rate card for now. The response also
    carries the review summary (`review`), the rows that were not treated as
    bid items (`skipped_rows`) and the mapped lines before pricing
    (`source_lines`), which POST /estimates/reprice takes back.
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

    with tempfile.TemporaryDirectory() as directory:
        # Keep the uploaded name: it appears in the extraction prompt.
        path = Path(directory) / Path(file.filename or f"upload{suffix}").name
        path.write_bytes(file.file.read())
        return _draft(path, card, llm)


@app.post("/estimates/draft/sample/{sample_id}")
def create_draft_estimate_from_sample(
    sample_id: str,
    llm: LLMClient = Depends(llm_client),
    card: RateCard = Depends(rate_card),
) -> Estimate:
    """Draft an estimate from one of the sample bid schedules (see GET /samples)."""
    path = sample_bid_path(sample_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No sample bid '{sample_id}'.")
    return _draft(path, card, llm)


def _draft(path: Path, card: RateCard, llm: LLMClient) -> Estimate:
    try:
        result = draft_estimate(
            path,
            card,
            llm,
            settings.high_impact_line_pct,
            settings.standard_rate_declined_score,
        )
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except DocumentParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMRateLimitError as exc:
        raise HTTPException(
            status_code=503, detail=str(exc), headers={ERROR_CODE_HEADER: "llm_rate_limited"}
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=502, detail=str(exc), headers={ERROR_CODE_HEADER: "llm_failed"}
        ) from exc
    return result.estimate


@app.post("/estimates/reprice")
def reprice_estimate(request: RepriceRequest, card: RateCard = Depends(rate_card)) -> Estimate:
    """Apply the reviewer's edits to the draft lines and price them again.

    No LLM call: only the pricing engine and the review checks run. Send the
    draft's `source_lines` as `lines`, unchanged, with one edit per line the
    reviewer has touched. Errors: 422 for an edit that cannot be applied.
    """
    return _reprice(request, card)


@app.post("/estimates/export")
def export_estimate(request: ExportRequest, card: RateCard = Depends(rate_card)) -> Response:
    """The reviewed estimate as an .xlsx workbook.

    Takes the same lines and edits as /estimates/reprice and prices them
    again here, so every figure in the file comes from the engine. Sheets:
    the estimate, its flags and assumptions, and the reviewer audit log.
    """
    estimate = _reprice(request, card)
    content = build_workbook(estimate, request.audit_log, card, request.source_filename)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(request.source_filename or "bid").stem)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{stem}_estimate.xlsx"'},
    )


def _reprice(request: RepriceRequest, card: RateCard) -> Estimate:
    try:
        estimate = apply_reviewer_edits(
            request.lines, request.edits, card, settings.high_impact_line_pct
        )
    except ReviewerEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return estimate.model_copy(update={"skipped_rows": request.skipped_rows})
