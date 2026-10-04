// Mirrors the eval result written by backend/evals/run_evals.py and served by
// GET /evals/latest (backend/evals/results.py, scoring.py, metrics.py).

/** `num` out of `den`. `rate` is null when there was nothing to measure. */
export interface Ratio {
  num: number;
  den: number;
  rate: number | null;
}

export interface EvalMetrics {
  bids: number;
  line_recall: Ratio;
  line_precision: Ratio;
  quantity_exact: Ratio;
  unit_match: Ratio;
  skipped_rows: Ratio;
  code_accuracy: Ratio;
  false_none: Ratio;
  false_rate: Ratio;
  wrong_code: number;
  flag_recall: Ratio;
  extra_flags: number;
  extra_flags_per_bid: number | null;
}

export interface EvalMoney {
  runs: number;
  exact_runs: number;
  mean_abs_error_pct: number | null;
  max_abs_error_pct: number | null;
  standard_only_exact_runs: number;
  standard_only_mean_abs_error_pct: number | null;
}

export interface EvalCost {
  runs: number;
  mean_seconds: number | null;
  mean_active_seconds: number | null;
  llm_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  mean_tokens_per_bid: number | null;
  tokens_reported: boolean;
}

export interface EvalStability {
  runs: number;
  distinct: number;
  agreement: number | null;
  identical: boolean;
}

export interface EvalStabilitySummary {
  codes_identical: Ratio;
  totals_identical: Ratio;
  mean_code_agreement: number | null;
  mean_total_agreement: number | null;
}

export type FailureSeverity = "error" | "note";

export interface EvalFailure {
  /** Unique within a result, e.g. "messy_bid-3". Used as the link target. */
  id: string;
  kind: string;
  severity: FailureSeverity;
  item_number: string | null;
  problem: string | null;
  expected: string;
  runs: number[];
  /** Run number -> what came back in that run. */
  actual: Record<string, string>;
  dollar_delta: string | null;
}

export interface EvalFlagSpec {
  any_of: string[];
  message_matches: string | null;
}

export interface EvalExpectedLine {
  item_number: string;
  description: string;
  quantity: string;
  unit: string;
  production_rate: string;
  required_flags: EvalFlagSpec[];
  allowed_flags: string[];
  problem: string | null;
  gold_subtotal: string;
}

export interface EvalActualLine {
  item_number: string;
  description: string;
  quantity: string;
  unit: string;
  source_ref: string | null;
  production_rate_code: string | null;
  rate_basis: string;
  line_subtotal: string;
  flags: { code: string; severity: string; message: string }[];
}

export interface EvalRun {
  run: number;
  status: "ok" | "failed";
  error: string | null;
  seconds: number;
  total_tokens: number;
  grand_total: string;
  lines: EvalActualLine[];
  extra_flag_codes: string[];
}

export interface EvalCase {
  id: string;
  title: string;
  bid_file: string;
  verified_by_hand: boolean;
  planted_problems: string[];
  expected_lines: EvalExpectedLine[];
  gold_total: string;
  /** Runs planned for this case. */
  runs_requested: number;
  /** The accuracy metrics and money figures use runs 1 to this number. */
  accuracy_runs: number;
  runs: EvalRun[];
  metrics: EvalMetrics;
  money: EvalMoney;
  cost: EvalCost;
  code_stability: EvalStability;
  total_stability: EvalStability;
  failures: EvalFailure[];
}

export interface EvalWeakness {
  title: string;
  detail: string;
  kind: string;
  severity: FailureSeverity;
  occurrences: number;
  cases: string[];
  /** Ids of example failures. */
  examples: string[];
}

export interface EvalSummary {
  cases: number;
  hand_verified: number;
  /** Runs the accuracy metrics are computed from, and all runs made. */
  runs_scored: number;
  runs_total: number;
  runs_failed: number;
  /** Cases run more than once: what stability is measured on. */
  stability_cases: number;
  metrics: EvalMetrics;
  money: EvalMoney;
  stability: EvalStabilitySummary;
  cost: EvalCost;
}

export interface EvalResult {
  meta: {
    run_id: string;
    model: string;
    temperature: number;
    reasoning_effort: string | null;
    /** Every case runs this often; the stability cases run `stability_runs` times. */
    runs_per_case: number;
    stability_runs: number;
    stability_cases: string[];
    started_at: string;
    finished_at: string | null;
    complete: boolean;
    stopped_because: string | null;
  };
  dataset: { synthetic: boolean; note: string; cases: number; hand_verified: number };
  summary: EvalSummary;
  cases: EvalCase[];
  known_weaknesses: EvalWeakness[];
}

export interface LatestEvals {
  /** The newest result of each model, newest first. */
  results: EvalResult[];
}

// Display formatting. The rates come from the backend; nothing is recomputed.

/** A ratio as "94.4%", or "-" when there was nothing to measure. */
export function formatRatio(ratio: Ratio): string {
  return ratio.rate === null ? "-" : `${(ratio.rate * 100).toFixed(1)}%`;
}

/** "51 of 54". */
export function formatCounts(ratio: Ratio): string {
  return `${ratio.num} of ${ratio.den}`;
}

export function formatNumber(value: number | null, digits = 1, suffix = ""): string {
  return value === null ? "-" : `${value.toFixed(digits)}${suffix}`;
}

const KIND_LABELS: Record<string, string> = {
  flag_missed: "Flag missed",
  false_none: "Rate not used",
  false_rate: "Rate picked, none exists",
  wrong_code: "Wrong rate",
  line_missed: "Line missed",
  line_extra: "Extra line",
  row_not_skipped: "Row not skipped",
  quantity_wrong: "Wrong quantity",
  unit_wrong: "Wrong unit",
  total_error: "Total differs",
  total_off_assumed: "Guessed dollars in total",
  run_failed: "Run failed",
  unstable_codes: "Codes differ between runs",
  unstable_total: "Total differs between runs",
};

/** "flag_missed" -> "Flag missed". Unknown kinds are shown as written. */
export function failureLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind.replaceAll("_", " ");
}

/** A case's failures that are errors, not notes. */
export function errorsOf(evalCase: EvalCase): EvalFailure[] {
  return evalCase.failures.filter((failure) => failure.severity === "error");
}

/** True if every run of the case gave the same codes and the same total. */
export function isStable(evalCase: EvalCase): boolean | null {
  if (evalCase.runs.length < 2) return null;
  return evalCase.code_stability.identical && evalCase.total_stability.identical;
}

/** The overall metrics shown in the model comparison, in display order. */
export function comparisonRows(summary: EvalSummary): { label: string; value: string; note: string }[] {
  const { metrics: m, money, stability, cost } = summary;
  return [
    { label: "Required flags raised", value: formatRatio(m.flag_recall), note: formatCounts(m.flag_recall) },
    { label: "Extra flags per bid", value: formatNumber(m.extra_flags_per_bid, 2), note: `${m.extra_flags} in ${m.bids} runs` },
    { label: "Rate-mapping accuracy", value: formatRatio(m.code_accuracy), note: formatCounts(m.code_accuracy) },
    { label: "Used no rate although one existed", value: formatRatio(m.false_none), note: formatCounts(m.false_none) },
    { label: "Picked a rate although none exists", value: formatRatio(m.false_rate), note: formatCounts(m.false_rate) },
    { label: "Line recall", value: formatRatio(m.line_recall), note: formatCounts(m.line_recall) },
    { label: "Line precision", value: formatRatio(m.line_precision), note: formatCounts(m.line_precision) },
    { label: "Quantity exact match", value: formatRatio(m.quantity_exact), note: formatCounts(m.quantity_exact) },
    { label: "Rows correctly skipped", value: formatRatio(m.skipped_rows), note: formatCounts(m.skipped_rows) },
    { label: "Mean grand total error", value: formatNumber(money.mean_abs_error_pct, 2, "%"), note: `worst ${formatNumber(money.max_abs_error_pct, 2, "%")}` },
    { label: "Mean total error, standard-rate lines only", value: formatNumber(money.standard_only_mean_abs_error_pct, 2, "%"), note: `exact in ${money.standard_only_exact_runs} of ${money.runs} runs` },
    { label: "Repeated cases with identical codes in all runs", value: formatRatio(stability.codes_identical), note: formatCounts(stability.codes_identical) },
    { label: "Repeated cases with an identical total in all runs", value: formatRatio(stability.totals_identical), note: formatCounts(stability.totals_identical) },
    { label: "Seconds per bid", value: formatNumber(cost.mean_active_seconds, 1), note: `${formatNumber(cost.mean_seconds, 1)} with rate-limit waits` },
    { label: "Tokens per bid", value: cost.tokens_reported ? formatNumber(cost.mean_tokens_per_bid, 0) : "not reported", note: cost.tokens_reported ? `${cost.total_tokens.toLocaleString("en-US")} in total` : "" },
    { label: "Runs with no estimate", value: `${summary.runs_failed}`, note: `of ${summary.runs_total}` },
  ];
}
