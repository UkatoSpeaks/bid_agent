"use client";

import { ChevronDownIcon } from "lucide-react";
import { useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { formatMoney, formatTime } from "@/lib/format";
import type { AuditEntry, Estimate, SkippedRow } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Rows of the document that were not treated as bid items. */
export function SkippedRows({ rows }: { rows: SkippedRow[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-lg border border-line bg-page"
    >
      <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left hover:bg-surface focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand">
        <span>
          <span className="block text-lg font-medium text-ink">
            Skipped rows <span className="text-subtle tabular-nums">({rows.length})</span>
          </span>
          <span className="block text-sm text-subtle">
            Rows the agent did not treat as bid items, with the reason
          </span>
        </span>
        <ChevronDownIcon
          className={cn("size-4 shrink-0 text-subtle transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        {rows.length === 0 ? (
          <p className="border-t border-line px-5 py-4 text-sm text-body">
            No rows were skipped: every row the agent returned was priced as a bid item.
          </p>
        ) : (
          <div className="relative overflow-x-auto border-t border-line">
            <table className="w-full min-w-[32rem] text-sm">
              <thead>
                <tr className="border-b border-line bg-surface text-left">
                  <th scope="col" className="eyebrow px-5 py-2.5 text-subtle">
                    Source
                  </th>
                  <th scope="col" className="eyebrow px-5 py-2.5 text-subtle">
                    Text
                  </th>
                  <th scope="col" className="eyebrow px-5 py-2.5 text-subtle">
                    Reason
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((row, index) => (
                  <tr key={`${row.source_ref}-${index}`}>
                    <td className="px-5 py-2.5 font-mono text-xs text-subtle">{row.source_ref}</td>
                    <td className="px-5 py-2.5 text-ink">{row.description || "(blank)"}</td>
                    <td className="px-5 py-2.5 text-body">{row.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

/** The totals exactly as the backend returns them, in the order they add up. */
export function TotalsCard({ estimate }: { estimate: Estimate }) {
  const { totals, currency } = estimate;
  const rows: { label: string; value: string; kind?: "sum" | "grand" }[] = [
    { label: "Direct labor", value: totals.direct_labor },
    { label: "Materials", value: totals.direct_material },
    { label: "Material markup", value: totals.material_markup },
    { label: "Sales tax on materials", value: totals.sales_tax },
    { label: "Equipment", value: totals.direct_equipment },
    { label: "Subtotal", value: totals.subtotal, kind: "sum" },
    { label: "Overhead", value: totals.overhead },
    { label: "Profit", value: totals.profit },
    { label: "Grand total", value: totals.grand_total, kind: "grand" },
  ];
  return (
    <section aria-labelledby="totals-title" className="rounded-lg border border-line bg-page">
      <h3 id="totals-title" className="border-b border-line px-5 py-4 text-lg font-medium">
        Totals
      </h3>
      <dl className="px-5 py-2">
        {rows.map((row) => (
          <div
            key={row.label}
            className={cn(
              "flex items-baseline justify-between gap-4 py-2 text-sm",
              row.kind && "border-t border-line font-medium text-ink",
              row.kind === "grand" && "border-ink py-3 text-lg",
            )}
          >
            <dt>{row.label}</dt>
            <dd className="num text-ink">{formatMoney(row.value, currency)}</dd>
          </div>
        ))}
      </dl>
      <p className="border-t border-line px-5 py-3 text-xs text-subtle">
        Calculated by the pricing engine. Each sum is the exact total of the figures above it.
      </p>
    </section>
  );
}

/** What the reviewer did, newest first. */
export function AuditLog({ entries }: { entries: AuditEntry[] }) {
  const newestFirst = [...entries].reverse();
  return (
    <section aria-labelledby="audit-title" className="rounded-lg border border-line bg-page">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-5 py-4">
        <h3 id="audit-title" className="text-lg font-medium">
          Audit log
        </h3>
        <p className="text-sm text-subtle">
          {entries.length} {entries.length === 1 ? "entry" : "entries"}, newest first
        </p>
      </div>
      {newestFirst.length === 0 ? (
        <p className="px-5 py-4 text-sm text-body">No actions yet.</p>
      ) : (
        <ol className="max-h-[26rem] divide-y divide-line overflow-y-auto">
          {newestFirst.map((item) => (
            <li key={item.id} className="px-5 py-3 text-sm">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium text-ink">{item.action}</span>
                {item.item_number && (
                  <span className="font-mono text-xs text-subtle">item {item.item_number}</span>
                )}
              </p>
              {(item.before || item.after) && (
                <p className="mt-0.5 text-body">
                  <span className="text-subtle line-through">{item.before}</span>
                  {" → "}
                  <span className="font-medium text-ink">{item.after}</span>
                </p>
              )}
              {item.note && <p className="mt-0.5 text-body">{item.note}</p>}
              <p className="mt-1 font-mono text-[0.6875rem] text-subtle">
                {item.who} · <time dateTime={item.timestamp}>{formatTime(item.timestamp)}</time>
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
