"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { exportEstimate, reprice } from "@/lib/api";
import { formatMoney, formatQuantity } from "@/lib/format";
import { canApprove, patchEdit, type EditMap } from "@/lib/review";
import type { AuditEntry, Estimate, LineEdit, PricedLine, ReviewStatus } from "@/lib/types";

export const REVIEWER = "Estimator";
const AGENT = "Bid Draft Agent";

/** One bid under review. Lives in memory only: there is no database yet. */
export interface ReviewSession {
  sourceName: string;
  /** The estimate as the agent drafted it. Its source_lines go into every reprice. */
  draft: Estimate;
  /** The estimate with the reviewer's edits, as last priced by the backend. */
  estimate: Estimate;
  edits: EditMap;
  audit: AuditEntry[];
  approvedAt: string | null;
}

type AuditFields = Omit<AuditEntry, "id" | "timestamp" | "who">;

function entry(who: string, fields: AuditFields): AuditEntry {
  return { id: crypto.randomUUID(), timestamp: new Date().toISOString(), who, ...fields };
}

function findLine(estimate: Estimate, lineId: string): PricedLine {
  const line = estimate.lines.find((candidate) => candidate.id === lineId);
  if (!line) throw new Error(`No line ${lineId}`);
  return line;
}

/** "Line subtotal $0.00 -> $1,290.00. Grand total ..." from two backend results. */
function priceNote(before: Estimate, after: Estimate, lineId: string): string {
  const currency = after.currency;
  const was = findLine(before, lineId).line_subtotal;
  const now = findLine(after, lineId).line_subtotal;
  return (
    `Line subtotal ${formatMoney(was, currency)} → ${formatMoney(now, currency)}. ` +
    `Grand total ${formatMoney(before.totals.grand_total, currency)} → ` +
    `${formatMoney(after.totals.grand_total, currency)}.`
  );
}

function rateLabel(line: PricedLine): string {
  if (line.production_rate_code) return line.production_rate_code;
  return line.rate_basis === "assumed" ? "Assumed by the LLM" : "Not mapped";
}

const STATUS_LABEL: Record<ReviewStatus, string> = {
  open: "Open",
  reviewed: "Reviewed",
  excluded: "Excluded",
};

export function useReviewSession() {
  const [session, setSession] = useState<ReviewSession | null>(null);
  const [busy, setBusy] = useState(false);
  // The latest session, for callbacks that run after an await.
  const latest = useRef<ReviewSession | null>(null);
  useEffect(() => {
    latest.current = session;
  }, [session]);

  const start = useCallback((sourceName: string, draft: Estimate) => {
    const review = draft.review;
    setSession({
      sourceName,
      draft,
      estimate: draft,
      edits: {},
      approvedAt: null,
      audit: [
        entry(AGENT, {
          action: "Drafted estimate",
          note:
            `${sourceName}: ${draft.lines.length} lines, grand total ` +
            `${formatMoney(draft.totals.grand_total, draft.currency)}, ` +
            `${review?.blocker_count ?? 0} blocker(s), ${review?.warning_count ?? 0} warning(s).`,
        }),
      ],
    });
  }, []);

  const reset = useCallback(() => setSession(null), []);

  /**
   * Apply a change to one line: send the draft lines and all edits to the
   * backend, and only on success store the new estimate and log the action.
   * Throws ApiError if the backend refuses; nothing changes in that case.
   */
  const applyEdit = useCallback(
    async (
      lineId: string,
      patch: Partial<LineEdit>,
      describe: (before: PricedLine, after: PricedLine, note: string) => AuditFields,
    ) => {
      const current = latest.current;
      if (!current) return;
      const edits = patchEdit(current.edits, lineId, patch);
      setBusy(true);
      try {
        const estimate = await reprice({
          lines: current.draft.source_lines,
          edits: Object.values(edits),
          skipped_rows: current.draft.skipped_rows,
        });
        const before = findLine(current.estimate, lineId);
        const after = findLine(estimate, lineId);
        const fields = describe(before, after, priceNote(current.estimate, estimate, lineId));
        const audit = [
          ...current.audit,
          entry(REVIEWER, { line_id: lineId, item_number: after.item_number, ...fields }),
        ];
        if (current.approvedAt) {
          audit.push(
            entry(REVIEWER, {
              action: "Approval withdrawn",
              note: "The estimate changed after it was approved.",
            }),
          );
        }
        setSession({ ...current, estimate, edits, audit, approvedAt: null });
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const setQuantity = useCallback(
    (lineId: string, quantity: string) =>
      applyEdit(lineId, { quantity }, (before, after, note) => ({
        action: "Changed quantity",
        before: `${formatQuantity(before.quantity)} ${before.unit}`,
        after: `${formatQuantity(after.quantity)} ${after.unit}`,
        note,
      })),
    [applyEdit],
  );

  const setProductionRate = useCallback(
    (lineId: string, code: string, suggested = false) =>
      applyEdit(lineId, { production_rate_code: code }, (before, after, note) => ({
        action: suggested ? "Applied suggested standard rate" : "Changed production rate",
        before: rateLabel(before),
        after: rateLabel(after),
        note,
      })),
    [applyEdit],
  );

  const setStatus = useCallback(
    (lineId: string, status: ReviewStatus, reason?: string) =>
      applyEdit(
        lineId,
        { status, exclusion_reason: status === "excluded" ? reason : null },
        (before, after, note) => {
          const action =
            status === "reviewed"
              ? "Marked reviewed"
              : status === "excluded"
                ? "Excluded line"
                : before.review_status === "excluded"
                  ? "Restored line"
                  : "Reopened line";
          const priced = status === "excluded" || before.review_status === "excluded";
          return {
            action,
            before: STATUS_LABEL[before.review_status],
            after: STATUS_LABEL[after.review_status],
            note: status === "excluded" ? `Reason: ${reason}. ${note}` : priced ? note : null,
          };
        },
      ),
    [applyEdit],
  );

  /** Drop the reviewer's quantity and rate for a line, keeping its status. */
  const resetLine = useCallback(
    (lineId: string) =>
      applyEdit(lineId, { quantity: null, production_rate_code: null }, (before, after, note) => ({
        action: "Reset line to the draft",
        before: `${formatQuantity(before.quantity)} ${before.unit}, ${rateLabel(before)}`,
        after: `${formatQuantity(after.quantity)} ${after.unit}, ${rateLabel(after)}`,
        note,
      })),
    [applyEdit],
  );

  const approve = useCallback(() => {
    setSession((current) => {
      if (!current || current.approvedAt || !canApprove(current.estimate)) return current;
      const approved = entry(REVIEWER, {
        action: "Approved estimate",
        note: `Grand total ${formatMoney(current.estimate.totals.grand_total, current.estimate.currency)}.`,
      });
      return { ...current, approvedAt: approved.timestamp, audit: [...current.audit, approved] };
    });
  }, []);

  /** Ask the backend for the .xlsx and return it for download. */
  const exportXlsx = useCallback(async () => {
    const current = latest.current;
    if (!current) return null;
    const exported = entry(REVIEWER, {
      action: "Exported estimate",
      note: current.approvedAt ? "Approved estimate." : "Not approved yet.",
    });
    const audit = [...current.audit, exported];
    setBusy(true);
    try {
      const file = await exportEstimate({
        lines: current.draft.source_lines,
        edits: Object.values(current.edits),
        skipped_rows: current.draft.skipped_rows,
        audit_log: audit.map((item) => ({
          timestamp: item.timestamp,
          who: item.who,
          action: item.action,
          line_id: item.line_id ?? null,
          item_number: item.item_number ?? null,
          before: item.before ?? null,
          after: item.after ?? null,
          note: item.note ?? null,
        })),
        source_filename: current.sourceName,
      });
      setSession((latestSession) => (latestSession ? { ...latestSession, audit } : latestSession));
      return file;
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    session,
    busy,
    start,
    reset,
    setQuantity,
    setProductionRate,
    setStatus,
    resetLine,
    approve,
    exportXlsx,
  };
}

export type ReviewActions = Pick<
  ReturnType<typeof useReviewSession>,
  "setQuantity" | "setProductionRate" | "setStatus" | "resetLine"
>;
