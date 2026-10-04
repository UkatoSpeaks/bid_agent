"use client";

import { CheckIcon, Loader2Icon, XIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type { Estimate } from "@/lib/types";
import { cn } from "@/lib/utils";

export type PipelineState =
  | { status: "running"; sourceName: string; startedAt: number }
  | { status: "done"; sourceName: string; seconds: number; estimate: Estimate }
  | { status: "failed"; sourceName: string; error: ApiError };

const STEPS = [
  {
    eyebrow: "Document + source refs",
    title: "Parse",
    text: "Read every row of the bid schedule as written, each with a reference back to its place in the document.",
  },
  {
    eyebrow: "LLM call 1 + checks in code",
    title: "Extract",
    text: "Copy out the bid items. Every quantity is then checked against the row it was taken from.",
  },
  {
    eyebrow: "LLM call 2 + rate card",
    title: "Map to company standards",
    text: "Choose a company production rate for each line. The hours and materials come from the rate card, not the model.",
  },
  {
    eyebrow: "Code only",
    title: "Price",
    text: "The pricing engine does all of the arithmetic. The model never produces or sees a price.",
  },
  {
    eyebrow: "Code only",
    title: "Review checks",
    text: "Rank the lines by dollar impact and flag what an estimator must look at first.",
  },
];

/** What each step produced, taken from the estimate the backend returned. */
function results(estimate: Estimate, sourceName: string): string[] {
  const review = estimate.review;
  return [
    `Read ${sourceName}.`,
    `${estimate.lines.length} bid items extracted, ${estimate.skipped_rows.length} rows skipped.`,
    review
      ? `${review.lines_on_standard_rates} on company standard rates, ${review.lines_on_assumed_rates} assumed by the LLM, ${review.lines_not_priced} not priced.`
      : "",
    `Grand total ${formatMoney(estimate.totals.grand_total, estimate.currency)}.`,
    review ? `${review.blocker_count} blockers, ${review.warning_count} warnings.` : "",
  ];
}

function Elapsed({ startedAt }: { startedAt: number }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);
  return <span className="tabular-nums">{seconds}s</span>;
}

/**
 * The five pipeline steps. The backend answers once, when all of them are
 * done, so while it runs the steps are shown as one sequence in progress
 * (no per-step progress is invented) and they complete together.
 */
export function Pipeline({
  state,
  onRetry,
  onBack,
}: {
  state: PipelineState;
  onRetry: () => void;
  onBack: () => void;
}) {
  const done = state.status === "done" ? results(state.estimate, state.sourceName) : null;

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_1.3fr] lg:gap-16">
      <div>
        <p className="eyebrow text-on-night-soft">02 / The agent works</p>
        <h2 className="mt-4 text-3xl leading-[1.1] font-medium text-on-night sm:text-4xl">
          The model reads.
          <span className="block text-on-night-soft">Your rates and code do the pricing.</span>
        </h2>

        <div
          role="status"
          aria-live="polite"
          className="mt-8 rounded-md border border-white/15 p-4 text-sm text-on-night-soft"
        >
          {state.status === "running" && (
            <>
              <p className="flex items-center gap-2 font-medium text-on-night">
                <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
                Working on {state.sourceName} · <Elapsed startedAt={state.startedAt} />
              </p>
              <p className="mt-2">
                The backend answers once, when all five steps are done, so they are not ticked
                off one by one. A first run can pause on the free LLM tier&apos;s rate limit.
              </p>
            </>
          )}
          {state.status === "done" && (
            <p className="flex items-center gap-2 font-medium text-on-night">
              <CheckIcon className="size-4" aria-hidden="true" />
              Draft ready for {state.sourceName} in {state.seconds.toFixed(1)}s
            </p>
          )}
          {state.status === "failed" && (
            <>
              <p className="flex items-center gap-2 font-medium text-on-night">
                <XIcon className="size-4" aria-hidden="true" />
                {state.error.title}
              </p>
              <p className="mt-2">{state.error.message}</p>
              {state.error.status !== null && (
                <p className="mt-2 font-mono text-xs">
                  {state.sourceName} · HTTP {state.error.status}
                </p>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button size="lg" onClick={onRetry}>
                  Try again
                </Button>
                <Button
                  size="lg"
                  variant="outline"
                  className="border-white/25 bg-transparent text-on-night hover:bg-white/10 hover:text-on-night"
                  onClick={onBack}
                >
                  Hand off a different bid
                </Button>
              </div>
            </>
          )}
        </div>
      </div>

      <ol>
        {STEPS.map((step, index) => (
          <li key={step.title} className="flex gap-4 border-t border-white/15 py-5 last:pb-0">
            <span className="mt-1 font-mono text-xs text-on-night-soft tabular-nums">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className="min-w-0 flex-1">
              <p className="eyebrow text-on-night-soft">{step.eyebrow}</p>
              <h3 className="mt-1.5 text-xl font-medium text-on-night">{step.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-on-night-soft">{step.text}</p>
              {done?.[index] && (
                <p className="mt-2 text-sm font-medium text-on-night">{done[index]}</p>
              )}
            </div>
            <span
              className={cn(
                "mt-1 inline-flex h-6 shrink-0 items-center gap-1 rounded-sm px-2 text-[0.6875rem] font-medium",
                state.status === "done" && "bg-white text-night",
                state.status === "running" && "border border-white/25 text-on-night",
                state.status === "failed" && "border border-white/25 text-on-night-soft",
              )}
            >
              {state.status === "done" && (
                <>
                  <CheckIcon className="size-3" aria-hidden="true" />
                  Done
                </>
              )}
              {state.status === "running" && "In progress"}
              {state.status === "failed" && "Not completed"}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
