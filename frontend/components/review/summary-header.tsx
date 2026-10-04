"use client";

import {
  CircleCheckIcon,
  DownloadIcon,
  LockIcon,
  OctagonAlertIcon,
  TriangleAlertIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatMoney, formatPct, formatTime } from "@/lib/format";
import { canApprove } from "@/lib/review";
import type { Estimate } from "@/lib/types";
import { cn } from "@/lib/utils";

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 p-5 sm:p-6">
      <p className="eyebrow text-subtle">{label}</p>
      {children}
    </div>
  );
}

export function SummaryHeader({
  estimate,
  approvedAt,
  busy = false,
  onApprove,
  onExport,
}: {
  estimate: Estimate;
  approvedAt: string | null;
  busy?: boolean;
  onApprove: () => void;
  onExport: () => void;
}) {
  const review = estimate.review;
  if (!review) return null;

  const ready = canApprove(estimate);
  const standard = Number(review.standard_rate_pct);
  const blockers = review.blocker_count;
  const priced = review.lines_on_standard_rates + review.lines_on_assumed_rates;

  return (
    <section
      aria-label="Estimate summary"
      className="overflow-hidden rounded-lg border border-line bg-page"
    >
      <div className="grid divide-y divide-line md:grid-cols-[1.1fr_1.4fr_1fr] md:divide-x md:divide-y-0">
        <Stat label="Grand total">
          <p
            data-testid="grand-total"
            className="mt-3 text-3xl font-medium tracking-tight text-ink tabular-nums sm:text-4xl"
          >
            {formatMoney(estimate.totals.grand_total, estimate.currency)}
          </p>
          <p className="mt-2 text-sm text-subtle">
            Subtotal {formatMoney(estimate.totals.subtotal, estimate.currency)} before overhead
            and profit
            {blockers > 0 && ". Incomplete while blockers are open."}
          </p>
        </Stat>

        <Stat label="Priced from company standard rates">
          <p className="mt-3 flex items-baseline gap-2">
            <span
              data-testid="standard-rate-pct"
              className="text-5xl font-medium tracking-tight text-ink tabular-nums sm:text-6xl"
            >
              {formatPct(review.standard_rate_pct)}
            </span>
            <span className="text-sm text-subtle">of the subtotal</span>
          </p>
          {/* One bar, two labelled parts: standard (brand) and assumed (hatched). */}
          <div
            className="mt-4 flex h-2 gap-0.5"
            role="img"
            aria-label={`${review.standard_rate_pct}% on company standard rates, ${review.assumed_rate_pct}% on rates assumed by the LLM`}
          >
            {standard > 0 && (
              <div className="rounded-sm bg-brand" style={{ width: `${standard}%` }} />
            )}
            {standard < 100 && (
              <div className="min-w-1 flex-1 rounded-sm bg-[repeating-linear-gradient(135deg,var(--line)_0_3px,var(--subtle)_3px_4px)]" />
            )}
          </div>
          <p className="mt-2 text-sm text-subtle">
            {review.lines_on_standard_rates} of {priced} priced lines on standard rates
            {" · "}
            <span className={cn(review.lines_on_assumed_rates > 0 && "font-medium text-ink")}>
              {formatPct(review.assumed_rate_pct)} assumed by the LLM
            </span>
            {review.lines_not_priced > 0 && ` · ${review.lines_not_priced} not priced`}
            {review.lines_excluded > 0 && ` · ${review.lines_excluded} excluded`}
          </p>
        </Stat>

        <Stat label="Open flags">
          <div className="mt-3 flex gap-6">
            <div>
              <p
                data-testid="blocker-count"
                className="flex items-center gap-1.5 text-3xl font-medium text-ink tabular-nums"
              >
                <OctagonAlertIcon
                  className={cn("size-5", blockers > 0 ? "text-blocker" : "text-subtle")}
                  aria-hidden="true"
                />
                {blockers}
              </p>
              <p className="mt-1 text-sm text-subtle">{blockers === 1 ? "blocker" : "blockers"}</p>
            </div>
            <div>
              <p
                data-testid="warning-count"
                className="flex items-center gap-1.5 text-3xl font-medium text-ink tabular-nums"
              >
                <TriangleAlertIcon
                  className={cn(
                    "size-5",
                    review.warning_count > 0 ? "text-warning" : "text-subtle",
                  )}
                  aria-hidden="true"
                />
                {review.warning_count}
              </p>
              <p className="mt-1 text-sm text-subtle">
                {review.warning_count === 1 ? "warning" : "warnings"}
              </p>
            </div>
          </div>
        </Stat>
      </div>

      <div className="flex flex-col gap-3 border-t border-line bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p
          data-testid="approve-status"
          className={cn(
            "flex items-center gap-2 text-sm font-medium",
            approvedAt || ready ? "text-ok" : "text-ink",
          )}
        >
          {approvedAt ? (
            <>
              <CircleCheckIcon className="size-4" aria-hidden="true" />
              Approved by Estimator at {formatTime(approvedAt)}
            </>
          ) : ready ? (
            <>
              <CircleCheckIcon className="size-4" aria-hidden="true" />
              Ready to approve: no unresolved blockers
            </>
          ) : (
            <>
              <LockIcon className="size-4 text-blocker" aria-hidden="true" />
              Not ready to approve: {blockers} unresolved{" "}
              {blockers === 1 ? "blocker" : "blockers"}
            </>
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="lg" onClick={onExport} disabled={busy}>
            <DownloadIcon data-icon="inline-start" />
            Export .xlsx
          </Button>
          <Button size="lg" onClick={onApprove} disabled={!ready || busy || approvedAt !== null}>
            {approvedAt ? "Approved" : "Approve estimate"}
          </Button>
        </div>
      </div>
    </section>
  );
}
