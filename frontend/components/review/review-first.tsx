"use client";

import { ArrowRightIcon, CircleCheckIcon } from "lucide-react";

import { FlagBadge, SEVERITY_LABEL, SeverityIcon } from "@/components/review/flag-badge";
import { formatMoney, formatPct } from "@/lib/format";
import { reviewFirst } from "@/lib/review";
import type { Estimate } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ReviewFirst({
  estimate,
  onOpenLine,
}: {
  estimate: Estimate;
  onOpenLine: (lineId: string) => void;
}) {
  const items = reviewFirst(estimate);

  return (
    <section aria-labelledby="review-first-title" className="rounded-lg border border-line bg-page">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-5 py-4">
        <h3 id="review-first-title" className="text-lg font-medium">
          Review first
        </h3>
        <p className="text-sm text-subtle">Blockers, then warnings, biggest line first</p>
      </div>

      {items.length === 0 ? (
        <p className="flex items-center gap-2 px-5 py-6 text-sm text-body">
          <CircleCheckIcon className="size-4 text-ok" aria-hidden="true" />
          Nothing is waiting for review. Every blocker and warning has been dealt with.
        </p>
      ) : (
        <ol className="divide-y divide-line">
          {items.map(({ line, flags, severity }) => (
            <li key={line.id}>
              <button
                type="button"
                onClick={() => onOpenLine(line.id)}
                className="group flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-surface focus-visible:bg-surface focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand"
              >
                <SeverityIcon
                  severity={severity}
                  className={cn(
                    "mt-0.5 size-4",
                    severity === "blocker" ? "text-blocker" : "text-warning",
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-mono text-xs text-subtle">
                      {line.item_number || line.id}
                    </span>
                    <span className="font-medium text-ink">{line.description}</span>
                    <span className="sr-only">{SEVERITY_LABEL[severity]}</span>
                  </span>
                  <span className="mt-1.5 flex flex-wrap gap-1">
                    {flags.map((flag, index) => (
                      <FlagBadge key={`${flag.code}-${index}`} flag={flag} />
                    ))}
                  </span>
                  <span className="mt-1.5 block text-sm text-body">{flags[0].message}</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block font-medium text-ink tabular-nums">
                    {formatMoney(line.line_subtotal, estimate.currency)}
                  </span>
                  <span className="block text-xs text-subtle tabular-nums">
                    {formatPct(line.subtotal_share_pct)} of subtotal
                  </span>
                </span>
                <ArrowRightIcon
                  className="mt-1 size-4 shrink-0 text-subtle transition-transform group-hover:translate-x-0.5 group-hover:text-brand"
                  aria-hidden="true"
                />
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
