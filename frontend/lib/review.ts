// Review logic that is not money: what blocks approval, what to look at
// first, and how the reviewer's edits are stored. Prices and counts always
// come from the backend.

import type { Estimate, Flag, LineEdit, PricedLine, Severity } from "@/lib/types";

const SEVERITY_RANK: Record<Severity, number> = { blocker: 0, warning: 1, info: 2 };

export function openFlags(line: PricedLine): Flag[] {
  return line.flags.filter((flag) => !flag.resolved);
}

/** Open flags first, then by severity. */
export function sortFlags(flags: Flag[]): Flag[] {
  return [...flags].sort(
    (a, b) =>
      Number(a.resolved) - Number(b.resolved) ||
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity],
  );
}

export function worstSeverity(flags: Flag[]): Severity | null {
  let worst: Severity | null = null;
  for (const flag of flags) {
    if (worst === null || SEVERITY_RANK[flag.severity] < SEVERITY_RANK[worst]) {
      worst = flag.severity;
    }
  }
  return worst;
}

/** Blockers nobody has resolved yet, across the whole estimate. */
export function unresolvedBlockerCount(estimate: Estimate): number {
  return estimate.all_flags.filter((flag) => flag.severity === "blocker" && !flag.resolved)
    .length;
}

/**
 * The approve gate. The backend decides (`review.ready_to_approve`); the
 * flags are checked as well, so an estimate with an open blocker can never
 * be approved even if the summary and the flags were to disagree.
 */
export function canApprove(estimate: Estimate | null): boolean {
  if (!estimate?.review) return false;
  return estimate.review.ready_to_approve && unresolvedBlockerCount(estimate) === 0;
}

export interface ReviewFirstItem {
  line: PricedLine;
  flags: Flag[]; // open blockers and warnings, worst first
  severity: Severity;
}

/**
 * Lines with an open blocker or warning: blockers before warnings, and
 * within a severity the biggest line subtotal first.
 */
export function reviewFirst(estimate: Estimate): ReviewFirstItem[] {
  const items: ReviewFirstItem[] = [];
  for (const line of estimate.lines) {
    if (line.review_status === "excluded") continue;
    const flags = sortFlags(openFlags(line).filter((flag) => flag.severity !== "info"));
    const severity = worstSeverity(flags);
    if (severity) items.push({ line, flags, severity });
  }
  return items.sort(
    (a, b) =>
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
      Number(b.line.line_subtotal) - Number(a.line.line_subtotal),
  );
}

/** The rate a STANDARD_RATE_DECLINED flag on this line suggests, if still open. */
export function suggestedRate(line: PricedLine): string | null {
  const flag = line.flags.find(
    (f) => f.code === "STANDARD_RATE_DECLINED" && !f.resolved && f.suggested_production_rate_code,
  );
  return flag?.suggested_production_rate_code ?? null;
}

export type EditMap = Record<string, LineEdit>;

function isEmpty(edit: LineEdit): boolean {
  return (
    (edit.quantity === null || edit.quantity === undefined) &&
    (edit.production_rate_code === null || edit.production_rate_code === undefined) &&
    edit.status === "open"
  );
}

/** The edits with `patch` applied to one line. An edit that changes nothing is dropped. */
export function patchEdit(edits: EditMap, lineId: string, patch: Partial<LineEdit>): EditMap {
  const current: LineEdit = edits[lineId] ?? { line_id: lineId, status: "open" };
  const next: LineEdit = { ...current, ...patch, line_id: lineId };
  if (next.status !== "excluded") next.exclusion_reason = null;
  const result = { ...edits };
  if (isEmpty(next)) delete result[lineId];
  else result[lineId] = next;
  return result;
}

/** A quantity typed by the reviewer, as a plain decimal string, or null if it is not one. */
export function parseQuantityInput(text: string): string | null {
  const cleaned = text.trim().replace(/,/g, "");
  return /^\d+(\.\d+)?$/.test(cleaned) ? cleaned : null;
}
