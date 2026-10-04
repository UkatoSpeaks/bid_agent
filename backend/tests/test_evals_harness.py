"""The eval harness end to end with a fake LLM, the case files and GET /evals/latest.

No API calls.
"""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import get_settings
from app.eval_results import latest_eval_results
from app.extraction import ExtractedLines, LineMappings
from app.llm import (
    LLMClient,
    LLMRateLimitError,
    LLMResponseError,
    LLMUnavailableError,
    LLMUsage,
)
from app.parsing import parse_bid_document
from evals.cases import CASES_DIR, CaseError, EvalCase, check_case, load_case, load_cases
from evals.report import render_comparison, render_markdown
from evals.results import (
    RawRuns,
    RunMeta,
    build_result,
    latest_results,
    load_raw,
    load_result,
    raw_path,
)
from evals.run_evals import (
    DEFAULT_TOKENS_PER_RUN,
    StopEval,
    estimate_tokens,
    run_model,
    run_once,
    tokens_per_run,
    write_result,
)
from evals.scoring import gold_estimate

SETTINGS = get_settings()


class GoldLLM(LLMClient):
    """Answers every prompt with the case's expected answers.

    `fail` maps a call number (1-based) to an exception to raise instead.
    """

    def __init__(self, case: EvalCase, fail: dict[int, Exception] | None = None) -> None:
        self.case = case
        self.document = parse_bid_document(case.bid_path)
        self.fail = fail or {}
        self.usage = LLMUsage()
        self.calls = 0

    def structured(self, prompt, schema):
        self.calls += 1
        if self.calls in self.fail:
            raise self.fail[self.calls]
        self.usage.calls += 1
        self.usage.total_tokens += 100
        if schema is ExtractedLines:
            return ExtractedLines.model_validate({"lines": self._extracted()})
        assert schema is LineMappings
        return LineMappings.model_validate({"lines": self._mappings(prompt)})

    def _extracted(self) -> list[dict]:
        lines = []
        for expected in self.case.lines:
            block = next(b for b in self.document.blocks if b.cells[0] == expected.item_number)
            lines.append(
                {
                    "item_number": expected.item_number,
                    "description": block.cells[1],
                    "quantity": block.cells[2],
                    "unit": block.cells[3],
                    "source_ref": block.ref,
                    "notes": None,
                    "scope_clarity": "clear",
                    "scope_reason": None,
                }
            )
        return lines

    def _mappings(self, prompt: str) -> list[dict]:
        codes = {line.item_number: line.rate_code for line in self.case.lines}
        bid_lines = prompt.split("Bid lines (", 1)[1].splitlines()[1:]
        mappings = []
        for row in bid_lines:
            line_id, item_number = (cell.strip() for cell in row.split(" | ")[:2])
            mappings.append(
                {
                    "line_id": line_id,
                    "production_rate_code": codes[item_number],
                    "confidence": "high",
                    "rationale": "expected answer",
                    "proposed_components": [],
                    "no_match_reason": None,
                }
            )
        return mappings


def meta(runs: int = 1, model: str = "test/model") -> RunMeta:
    return RunMeta(
        run_id=f"20260101T000000Z-{model.replace('/', '-')}",
        model=model,
        temperature=0.2,
        reasoning_effort="medium",
        runs_per_case=runs,
        started_at="2026-01-01T00:00:00+00:00",
    )


def no_sleep(_seconds: float) -> None:
    pass


# --- the case files ---


def test_there_are_nine_cases_and_each_fits_its_bid(sample_rate_card):
    cases = load_cases()

    assert len(cases) == 9
    for case in cases:
        check_case(case, sample_rate_card)
        assert case.bid_path.is_file()
        # The engine can price the expected answers.
        assert gold_estimate(case, sample_rate_card).totals.grand_total > 0


def test_every_expected_file_starts_with_the_verified_marker():
    for path in CASES_DIR.glob("*.yaml"):
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first in ("# VERIFIED BY HAND: no", "# VERIFIED BY HAND: yes"), path.name


def test_check_case_rejects_answers_that_do_not_fit_the_document(sample_rate_card):
    case = load_case(CASES_DIR / "clean_bid.yaml")

    wrong_code = case.model_copy(deep=True)
    wrong_code.lines[0].production_rate = "PR-NOT-A-RATE"
    with pytest.raises(CaseError, match="not in the rate card"):
        check_case(wrong_code, sample_rate_card)

    wrong_item = case.model_copy(deep=True)
    wrong_item.lines[0].item_number = "99"
    with pytest.raises(CaseError, match="no row of the document"):
        check_case(wrong_item, sample_rate_card)

    wrong_row = case.model_copy(deep=True)
    wrong_row.skip_rows[0].text = "Something else"
    with pytest.raises(CaseError, match="the document reads"):
        check_case(wrong_row, sample_rate_card)


def test_load_cases_rejects_an_unknown_case_id():
    with pytest.raises(CaseError, match="unknown case"):
        load_cases(only=["no_such_case"])


# --- running and scoring ---


def test_a_run_with_the_expected_answers_scores_full_marks(sample_rate_card, tmp_path):
    case = load_case(CASES_DIR / "clean_bid.yaml")
    partial = RawRuns(meta=meta(runs=2), runs={})

    partial = run_model(
        partial, [case], sample_rate_card, GoldLLM(case), SETTINGS, 0, tmp_path, no_sleep
    )
    result = write_result(partial, [case], sample_rate_card, tmp_path)

    assert result.meta.complete
    summary = result.summary
    assert summary.runs_scored == 2
    assert summary.metrics.line_recall.rate == 1
    assert summary.metrics.code_accuracy.rate == 1
    assert summary.money.exact_runs == 2
    assert summary.stability.codes_identical.rate == 1
    assert summary.cost.total_tokens == 600  # 3 calls of 100 tokens, twice
    assert result.known_weaknesses == []
    assert result.dataset.synthetic
    assert (result.dataset.cases, result.dataset.hand_verified) == (1, 0)

    # The files: the scores, the report, and the raw output apart from both.
    run_id = result.meta.run_id
    assert load_result(tmp_path / f"{run_id}.json").summary == summary
    report = (tmp_path / f"{run_id}.md").read_text(encoding="utf-8")
    assert "Hand-verified cases: 0 of 1" in report
    assert "Synthetic dataset" in report
    assert raw_path(run_id, tmp_path) == tmp_path / "raw" / f"{run_id}.json"
    saved = load_raw(run_id, tmp_path)
    assert saved.meta.complete
    first = saved.runs["clean_bid"][0]
    assert (first.run, first.status, len(first.lines)) == (1, "ok", 10)
    assert first.lines[0].production_rate_code == "PR-CU-3T"
    assert first.totals.grand_total == first.grand_total == result.cases[0].gold_total
    # The raw file holds what came back, not how it scored.
    assert "metrics" not in raw_path(run_id, tmp_path).read_text(encoding="utf-8")


def test_a_model_failure_is_recorded_as_a_failed_run(sample_rate_card):
    case = load_case(CASES_DIR / "clean_bid.yaml")
    llm = GoldLLM(case, fail={1: LLMResponseError("no valid JSON after 2 attempts")})

    output = run_once(case, 1, sample_rate_card, llm, SETTINGS, no_sleep)

    assert output.status == "failed"
    assert "no valid JSON" in output.error
    assert output.lines == []


def test_an_unreachable_provider_is_retried_and_never_scored(sample_rate_card):
    case = load_case(CASES_DIR / "clean_bid.yaml")
    waits: list[float] = []

    # One connection error: the run is tried again and comes back complete.
    llm = GoldLLM(case, fail={2: LLMUnavailableError("Connection error.")})
    output = run_once(case, 1, sample_rate_card, llm, SETTINGS, waits.append)
    assert output.status == "ok"
    assert len(output.lines) == 10
    assert waits == [15.0]

    # Unreachable every time: the eval stops instead of recording a failed run.
    llm = GoldLLM(case, fail={n: LLMUnavailableError("Connection error.") for n in range(1, 9)})
    with pytest.raises(StopEval, match="provider unavailable"):
        run_once(case, 1, sample_rate_card, llm, SETTINGS, no_sleep)


def test_a_rate_limit_is_retried_and_then_stops_the_eval(sample_rate_card, tmp_path):
    case = load_case(CASES_DIR / "clean_bid.yaml")
    waits: list[float] = []

    # Limited once: the run is tried again after a wait.
    llm = GoldLLM(case, fail={1: LLMRateLimitError("429 tokens per minute")})
    output = run_once(case, 1, sample_rate_card, llm, SETTINGS, waits.append)
    assert output.status == "ok"
    assert waits == [60.0]

    # A daily limit stops at once.
    llm = GoldLLM(case, fail={1: LLMRateLimitError("429 on tokens per day (TPD)")})
    with pytest.raises(StopEval, match="daily rate limit"):
        run_once(case, 1, sample_rate_card, llm, SETTINGS, no_sleep)

    # In run_model the eval stops, keeps what it has, and can be resumed.
    llm = GoldLLM(case, fail={4: LLMRateLimitError("429 on tokens per day (TPD)")})
    partial = run_model(
        RawRuns(meta=meta(runs=2), runs={}),
        [case],
        sample_rate_card,
        llm,
        SETTINGS,
        0,
        tmp_path,
        no_sleep,
    )
    assert not partial.meta.complete
    assert "daily rate limit" in partial.meta.stopped_because
    assert [run.run for run in partial.runs["clean_bid"]] == [1]
    result = write_result(partial, [case], sample_rate_card, tmp_path)
    assert "INCOMPLETE" in render_markdown(result)

    resumed = load_raw(partial.meta.run_id, tmp_path)
    resumed = run_model(
        resumed, [case], sample_rate_card, GoldLLM(case), SETTINGS, 0, tmp_path, no_sleep
    )
    assert resumed.meta.complete
    assert [run.run for run in resumed.runs["clean_bid"]] == [1, 2]


def test_a_result_can_be_scored_again_from_its_stored_runs(sample_rate_card, tmp_path):
    case = load_case(CASES_DIR / "clean_bid.yaml")
    partial = run_model(
        RawRuns(meta=meta(), runs={}),
        [case],
        sample_rate_card,
        GoldLLM(case),
        SETTINGS,
        0,
        tmp_path,
        no_sleep,
    )
    result = write_result(partial, [case], sample_rate_card, tmp_path)

    # The expected file is corrected and marked as checked by hand.
    corrected = case.model_copy(deep=True)
    corrected.verified_by_hand = True
    corrected.lines[0].production_rate = "PR-CU-5T"
    saved = load_raw(result.meta.run_id, tmp_path)
    llm_calls = partial.runs["clean_bid"][0].llm_calls
    rescored = build_result(saved, [corrected], sample_rate_card)
    assert saved.runs["clean_bid"][0].llm_calls == llm_calls  # nothing was run again

    assert rescored.dataset.hand_verified == 1
    assert rescored.summary.metrics.code_accuracy.num == 9
    assert [f.kind for f in rescored.cases[0].failures] == ["wrong_code", "total_error"]


def test_comparison_puts_the_models_side_by_side(sample_rate_card, tmp_path):
    case = load_case(CASES_DIR / "clean_bid.yaml")
    results = []
    for model in ("test/model-a", "test/model-b"):
        partial = run_model(
            RawRuns(meta=meta(model=model), runs={}),
            [case],
            sample_rate_card,
            GoldLLM(case),
            SETTINGS,
            0,
            tmp_path,
            no_sleep,
        )
        results.append(write_result(partial, [case], sample_rate_card, tmp_path))

    comparison = render_comparison(results)

    assert "| Metric | `test/model-a` | `test/model-b` |" in comparison
    assert "| clean_bid | 0 failure(s), total error 0.00% | 0 failure(s), total error 0.00% |" in comparison
    assert {r.meta.model for r in latest_results(tmp_path)} == {"test/model-a", "test/model-b"}


# --- the plan and the token budget ---


def test_default_plan_runs_every_case_once_and_three_cases_three_times():
    plan = RunMeta(
        run_id="x",
        model="m",
        temperature=0.2,
        reasoning_effort=None,
        runs_per_case=1,
        stability_runs=3,
        stability_cases=["clean_bid", "messy_bid", "tricky_bid"],
        started_at="",
    )
    case_ids = [case.id for case in load_cases()]
    raw = RawRuns(meta=plan, runs={})

    todo = raw.missing(case_ids)

    assert len(todo) == 9 + 3 * 2  # 15 runs
    # Round by round: run 1 of all nine cases comes first.
    assert [run for _case, run in todo] == [1] * 9 + [2] * 3 + [3] * 3
    assert {case for case, run in todo if run > 1} == {"clean_bid", "messy_bid", "tricky_bid"}
    assert plan.planned_runs("format_change") == 1
    assert plan.planned_runs("messy_bid") == 3


def test_token_estimate_uses_measured_runs_where_there_are_any(sample_rate_card, tmp_path):
    todo = [("clean_bid", 1), ("clean_bid", 2), ("messy_bid", 1)]

    # Nothing measured yet: the default for every run.
    assert tokens_per_run(tmp_path) == {}
    assert estimate_tokens(todo, {}) == 3 * DEFAULT_TOKENS_PER_RUN

    # clean_bid has been run: 3 calls of 100 tokens by the fake LLM.
    case = load_case(CASES_DIR / "clean_bid.yaml")
    run_model(
        RawRuns(meta=meta(), runs={}), [case], sample_rate_card, GoldLLM(case), SETTINGS,
        0, tmp_path, no_sleep,
    )
    history = tokens_per_run(tmp_path)
    assert history == {"clean_bid": 300}
    assert estimate_tokens(todo, history) == 300 + 300 + DEFAULT_TOKENS_PER_RUN


def test_the_eval_stops_when_the_token_budget_is_used_up(sample_rate_card, tmp_path):
    case = load_case(CASES_DIR / "clean_bid.yaml")

    # Each run uses 300 tokens; the budget is spent after two of three runs.
    raw = run_model(
        RawRuns(meta=meta(runs=3), runs={}), [case], sample_rate_card, GoldLLM(case), SETTINGS,
        0, tmp_path, no_sleep, max_tokens=600,
    )

    assert [run.run for run in raw.runs["clean_bid"]] == [1, 2]
    assert not raw.meta.complete
    assert "token budget used up: 600 of 600" in raw.meta.stopped_because
    assert raw.missing(["clean_bid"]) == [("clean_bid", 3)]


# --- GET /evals/latest ---


def _write(directory, name: str, model: str, marker: str) -> None:
    (directory / name).write_text(
        json.dumps({"meta": {"model": model, "run_id": marker}}), encoding="utf-8"
    )


def test_latest_eval_results_takes_the_newest_file_of_each_model(tmp_path):
    _write(tmp_path, "20260101T000000Z-a.json", "a", "old a")
    _write(tmp_path, "20260102T000000Z-a.json", "a", "new a")
    _write(tmp_path, "20260101T120000Z-b.json", "b", "only b")
    # Raw run outputs live in a subfolder and are not results.
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", "20260103T000000Z-a.json", "a", "raw runs")
    (tmp_path / "20260104T000000Z-comparison.md").write_text("# not json", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    results = latest_eval_results(tmp_path)

    assert [r["meta"]["run_id"] for r in results] == ["new a", "only b"]


def test_evals_latest_endpoint(monkeypatch):
    client = TestClient(main_module.app)

    monkeypatch.setattr(main_module, "latest_eval_results", lambda: [])
    response = client.get("/evals/latest")
    assert response.status_code == 404
    assert "run_evals.py" in response.json()["detail"]

    stored = [{"meta": {"model": "a", "run_id": "x"}, "summary": {"cases": 9}}]
    monkeypatch.setattr(main_module, "latest_eval_results", lambda: stored)
    response = client.get("/evals/latest")
    assert response.status_code == 200
    assert response.json() == {"results": stored}
