import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseTable } from "@/components/evals/case-table";
import { FailureList } from "@/components/evals/failure-list";
import { Headline } from "@/components/evals/headline";
import { ModelComparison } from "@/components/evals/model-comparison";
import type { EvalCase, EvalMetrics, EvalResult, EvalSummary, Ratio } from "@/lib/evals";

const ratio = (num: number, den: number): Ratio => ({ num, den, rate: den ? num / den : null });

const metrics: EvalMetrics = {
  bids: 3,
  line_recall: ratio(30, 30),
  line_precision: ratio(30, 30),
  quantity_exact: ratio(30, 30),
  unit_match: ratio(30, 30),
  skipped_rows: ratio(15, 15),
  code_accuracy: ratio(28, 30),
  false_none: ratio(2, 27),
  false_rate: ratio(0, 3),
  wrong_code: 0,
  flag_recall: ratio(5, 6),
  extra_flags: 3,
  extra_flags_per_bid: 1,
};

const cost = {
  runs: 3,
  mean_seconds: 20,
  mean_active_seconds: 8.5,
  llm_calls: 9,
  prompt_tokens: 15000,
  completion_tokens: 6000,
  total_tokens: 21000,
  mean_tokens_per_bid: 7000,
  tokens_reported: true,
};

const money = {
  runs: 3,
  exact_runs: 1,
  mean_abs_error_pct: 2.345,
  max_abs_error_pct: 4.1,
  standard_only_exact_runs: 2,
  standard_only_mean_abs_error_pct: 0.5,
};

const summary: EvalSummary = {
  cases: 1,
  hand_verified: 0,
  runs_scored: 3,
  runs_total: 3,
  runs_failed: 0,
  stability_cases: 1,
  metrics,
  money,
  stability: {
    codes_identical: ratio(0, 1),
    totals_identical: ratio(0, 1),
    mean_code_agreement: 2 / 3,
    mean_total_agreement: 2 / 3,
  },
  cost,
};

const messy: EvalCase = {
  id: "messy_bid",
  title: "Messy bid",
  bid_file: "messy_bid.pdf",
  verified_by_hand: false,
  planted_problems: ["a vague lump sum"],
  expected_lines: [
    {
      item_number: "B4",
      description: "Supply registers",
      quantity: "64",
      unit: "Each",
      production_rate: "PR-REG-SUP",
      required_flags: [],
      allowed_flags: [],
      problem: null,
      gold_subtotal: "2816.00",
    },
  ],
  gold_total: "156036.69",
  runs_requested: 3,
  accuracy_runs: 3,
  runs: [1, 2, 3].map((run) => ({
    run,
    status: "ok" as const,
    error: null,
    seconds: 20,
    total_tokens: 7000,
    grand_total: "156036.69",
    extra_flag_codes: [],
    lines: [
      {
        item_number: "B4",
        description: "Supply registers",
        quantity: "64",
        unit: "Each",
        source_ref: "p1-t1-r12",
        production_rate_code: run === 2 ? null : "PR-REG-SUP",
        rate_basis: run === 2 ? "assumed" : "standard",
        line_subtotal: "2816.00",
        flags: [],
      },
    ],
  })),
  metrics,
  money,
  cost,
  code_stability: { runs: 3, distinct: 2, agreement: 2 / 3, identical: false },
  total_stability: { runs: 3, distinct: 2, agreement: 2 / 3, identical: false },
  failures: [
    {
      id: "messy_bid-1",
      kind: "false_none",
      severity: "error",
      item_number: "B4",
      problem: null,
      expected: "production rate PR-REG-SUP",
      runs: [2],
      actual: { "2": "production rate none (components assumed by the LLM)" },
      dollar_delta: null,
    },
    {
      id: "messy_bid-2",
      kind: "total_off_assumed",
      severity: "note",
      item_number: null,
      problem: null,
      expected: "grand total $156,036.69",
      runs: [1, 2, 3],
      actual: { "1": "$157,000.00", "2": "$157,100.00", "3": "$157,000.00" },
      dollar_delta: "963.31",
    },
  ],
};

const result = (model: string, complete = true): EvalResult => ({
  meta: {
    run_id: `20261004T000000Z-${model}`,
    model,
    temperature: 0.2,
    reasoning_effort: "medium",
    runs_per_case: 1,
    stability_runs: 3,
    stability_cases: ["clean_bid", "messy_bid", "tricky_bid"],
    started_at: "2026-10-04T00:00:00+00:00",
    finished_at: "2026-10-04T00:30:00+00:00",
    complete,
    stopped_because: complete ? null : "daily rate limit",
  },
  dataset: { synthetic: true, note: "Synthetic dataset.", cases: 1, hand_verified: 0 },
  summary,
  cases: [messy],
  known_weaknesses: [],
});

describe("Headline", () => {
  it("shows the four headline numbers as the backend computed them", () => {
    render(<Headline summary={summary} />);

    expect(screen.getByTestId("flag-recall")).toHaveTextContent("83.3%");
    expect(screen.getByTestId("code-accuracy")).toHaveTextContent("93.3%");
    expect(screen.getByTestId("total-error")).toHaveTextContent("2.35%");
    expect(screen.getByTestId("stability")).toHaveTextContent("0.0%");
    expect(screen.getByText(/5 of 6 required flags raised/)).toBeInTheDocument();
    expect(screen.getByText(/exact in 1 of 3 runs/)).toBeInTheDocument();
  });
});

describe("CaseTable and FailureList", () => {
  it("links each failure to its expected-vs-returned detail", () => {
    render(
      <>
        <CaseTable cases={[messy]} />
        <FailureList cases={[messy]} />
      </>,
    );

    expect(screen.getByText("Not hand-verified")).toBeInTheDocument();
    expect(screen.getByText("1 failure, 1 note")).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /Rate not used · B4/ });
    expect(link).toHaveAttribute("href", "#messy_bid-1");

    const detail = document.getElementById("messy_bid-1");
    expect(detail).not.toBeNull();
    const card = within(detail as HTMLElement);
    expect(card.getByText("production rate PR-REG-SUP")).toBeInTheDocument();
    expect(card.getByText(/production rate none \(components assumed by the LLM\)/)).toBeInTheDocument();
    expect(card.getByText("in 1 of 3 runs")).toBeInTheDocument();
    // The line as expected, then as each of the three runs returned it.
    expect(card.getAllByRole("row")).toHaveLength(1 + 1 + 3);
    expect(card.getByText("assumed by the LLM")).toBeInTheDocument();
  });

  it("says so plainly when a case has no failures", () => {
    const clean = { ...messy, failures: [] };
    render(
      <>
        <CaseTable cases={[clean]} />
        <FailureList cases={[clean]} />
      </>,
    );

    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.getByText(/every run matched its expected answers/)).toBeInTheDocument();
  });
});

describe("ModelComparison", () => {
  it("puts the models side by side and marks an eval that stopped early", () => {
    render(<ModelComparison results={[result("openai/gpt-oss-120b"), result("openai/gpt-oss-20b", false)]} />);

    expect(screen.getByRole("columnheader", { name: "openai/gpt-oss-120b" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /openai\/gpt-oss-20b.*stopped early/ })).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Rate-mapping accuracy/ });
    expect(within(row).getAllByText("93.3%")).toHaveLength(2);
    expect(screen.getAllByText("0 of 1")).not.toHaveLength(0);
  });
});
