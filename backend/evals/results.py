"""Eval files: the raw output of every run, and the scores computed from it.

Two files per eval, both named after its run id ("<timestamp>-<model>"):

    results/raw/<run_id>.json   what the pipeline returned in every run
                                (lines, chosen rate codes, flags, totals).
                                Written after each run and never scored.
    results/<run_id>.json       the scores, computed from the raw file
    results/<run_id>.md         the same, readable

The scores can be recomputed from the raw file at any time (--rescore).
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas import RateCard
from evals.cases import RESULTS_DIR, EvalCase
from evals.scoring import (
    CaseResult,
    RunOutput,
    Summary,
    Weakness,
    known_weaknesses,
    score_case,
    summarize,
)

DATASET_NOTE = (
    "Synthetic dataset: every bid schedule was written for this eval, for a fictional "
    "company, with problems planted on purpose. The scores say how the pipeline does on "
    "these cases, not how it does on real bids."
)
RAW_DIRNAME = "raw"


class Dataset(BaseModel):
    synthetic: bool = True
    note: str = DATASET_NOTE
    cases: int
    hand_verified: int


class RunMeta(BaseModel):
    run_id: str  # "<timestamp>-<model>", also the file name
    model: str
    temperature: float
    reasoning_effort: str | None
    # The plan. Every case runs `runs_per_case` times; the accuracy metrics
    # are computed from those runs. The cases in `stability_cases` run
    # `stability_runs` times in all, so that stability can be measured.
    runs_per_case: int
    stability_runs: int = 0
    stability_cases: list[str] = Field(default_factory=list)
    started_at: str
    finished_at: str | None = None
    # False if the eval stopped early (rate limit, token budget): some
    # planned runs are missing.
    complete: bool = False
    stopped_because: str | None = None

    def planned_runs(self, case_id: str) -> int:
        """How many times a case is to be run."""
        if case_id in self.stability_cases:
            return max(self.runs_per_case, self.stability_runs)
        return self.runs_per_case


class RawRuns(BaseModel):
    """What every run returned, unscored. Written after every run."""

    meta: RunMeta
    runs: dict[str, list[RunOutput]]  # case id -> runs

    def missing(self, case_ids: list[str]) -> list[tuple[str, int]]:
        """The planned (case, run) pairs that have not been run, round by round."""
        rounds = max((self.meta.planned_runs(case_id) for case_id in case_ids), default=0)
        return [
            (case_id, run)
            for run in range(1, rounds + 1)
            for case_id in case_ids
            if run <= self.meta.planned_runs(case_id)
            and not any(output.run == run for output in self.runs.get(case_id, []))
        ]


class EvalResult(BaseModel):
    schema_version: int = 2
    meta: RunMeta
    dataset: Dataset
    summary: Summary
    cases: list[CaseResult]
    known_weaknesses: list[Weakness]


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def model_slug(model: str) -> str:
    """'openai/gpt-oss-120b' -> 'openai-gpt-oss-120b', safe in a file name."""
    return re.sub(r"[^A-Za-z0-9.]+", "-", model).strip("-")


def build_result(raw: RawRuns, cases: list[EvalCase], rate_card: RateCard) -> EvalResult:
    """Score every case that has at least one run. No LLM involved."""
    meta = raw.meta
    scored = [
        score_case(
            case,
            sorted(raw.runs[case.id], key=lambda run: run.run),
            rate_card,
            accuracy_runs=meta.runs_per_case,
            runs_planned=meta.planned_runs(case.id),
        )
        for case in cases
        if raw.runs.get(case.id)
    ]
    return EvalResult(
        meta=meta,
        dataset=Dataset(
            cases=len(scored),
            hand_verified=sum(1 for case in scored if case.verified_by_hand),
        ),
        summary=summarize(scored),
        cases=scored,
        known_weaknesses=known_weaknesses(scored),
    )


def result_path(run_id: str, directory: Path = RESULTS_DIR) -> Path:
    return directory / f"{run_id}.json"


def raw_path(run_id: str, directory: Path = RESULTS_DIR) -> Path:
    return directory / RAW_DIRNAME / f"{run_id}.json"


def save_raw(raw: RawRuns, directory: Path = RESULTS_DIR) -> Path:
    path = raw_path(raw.meta.run_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_raw(run_id: str, directory: Path = RESULTS_DIR) -> RawRuns:
    """Raises FileNotFoundError if there is no such run."""
    return RawRuns.model_validate_json(raw_path(run_id, directory).read_text(encoding="utf-8"))


def raw_run_ids(directory: Path = RESULTS_DIR) -> list[str]:
    """Every run id with saved raw output, oldest first."""
    return sorted(path.stem for path in (directory / RAW_DIRNAME).glob("*.json"))


def save_result(result: EvalResult, directory: Path = RESULTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = result_path(result.meta.run_id, directory)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_result(path: Path) -> EvalResult:
    return EvalResult.model_validate_json(path.read_text(encoding="utf-8"))


def latest_results(directory: Path = RESULTS_DIR) -> list[EvalResult]:
    """The newest scored result of each model, newest first.

    File names start with a UTC timestamp, so sorting by name sorts by time.
    """
    latest: dict[str, EvalResult] = {}
    for path in sorted(directory.glob("*.json"), reverse=True):
        result = load_result(path)
        latest.setdefault(result.meta.model, result)
    return list(latest.values())
