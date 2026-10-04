import { formatCounts, formatNumber, formatRatio, type EvalSummary } from "@/lib/evals";

function Stat({
  label,
  value,
  testId,
  children,
}: {
  label: string;
  value: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0 bg-page p-5 sm:p-6">
      <p className="eyebrow text-subtle">{label}</p>
      <p
        data-testid={testId}
        className="mt-3 text-4xl font-medium tracking-tight text-ink tabular-nums sm:text-5xl"
      >
        {value}
      </p>
      <p className="mt-2 text-sm text-subtle">{children}</p>
    </div>
  );
}

/** Flag recall, rate-mapping accuracy, total error and stability for one model. */
export function Headline({ summary }: { summary: EvalSummary }) {
  const { metrics: m, money, stability } = summary;
  return (
    <section
      aria-label="Headline numbers"
      className="overflow-hidden rounded-lg border border-line bg-page"
    >
      {/* The 1px gaps over the line colour draw the dividers at every breakpoint. */}
      <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Flag recall" value={formatRatio(m.flag_recall)} testId="flag-recall">
          {formatCounts(m.flag_recall)} required flags raised: did every planted problem get
          caught? Plus {formatNumber(m.extra_flags_per_bid, 2)} extra flags per bid.
        </Stat>
        <Stat
          label="Rate-mapping accuracy"
          value={formatRatio(m.code_accuracy)}
          testId="code-accuracy"
        >
          {formatCounts(m.code_accuracy)} lines on the expected production rate.{" "}
          {m.false_none.num} used no rate although one existed, {m.false_rate.num} picked a rate
          although none exists, {m.wrong_code} picked the wrong one.
        </Stat>
        <Stat
          label="Grand total error"
          value={formatNumber(money.mean_abs_error_pct, 2, "%")}
          testId="total-error"
        >
          Mean distance from the gold total, which the pricing engine computes from the expected
          answers. Worst {formatNumber(money.max_abs_error_pct, 2, "%")}; exact in{" "}
          {money.exact_runs} of {money.runs} runs.{" "}
          {formatNumber(money.standard_only_mean_abs_error_pct, 2, "%")} when lines priced on
          rates guessed by the LLM are left out.
        </Stat>
        <Stat
          label="Stability"
          value={formatRatio(stability.codes_identical)}
          testId="stability"
        >
          {formatCounts(stability.codes_identical)} bids that were run more than once got
          identical production rate codes in every run;{" "}
          {formatCounts(stability.totals_identical)} got an identical grand total.
        </Stat>
      </div>
    </section>
  );
}
