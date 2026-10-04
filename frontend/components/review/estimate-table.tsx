"use client";

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon, CheckIcon, PencilIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { FlagBadge, Pill } from "@/components/review/flag-badge";
import { formatMoney, formatPct, formatQuantity } from "@/lib/format";
import { sortFlags } from "@/lib/review";
import type { Estimate, PricedLine } from "@/lib/types";
import { cn } from "@/lib/utils";

const column = createColumnHelper<PricedLine>();
const MAX_BADGES = 3;

export function RateCell({ line }: { line: PricedLine }) {
  if (line.rate_basis === "standard" && line.production_rate_code) {
    return (
      <span className="font-mono text-xs whitespace-nowrap text-ink">
        {line.production_rate_code}
      </span>
    );
  }
  if (line.rate_basis === "assumed") return <Pill tone="warning">Assumed</Pill>;
  if (line.production_rate_code) {
    // A rate was chosen but could not be applied (unit mismatch).
    return (
      <span className="font-mono text-xs text-subtle line-through">
        {line.production_rate_code}
      </span>
    );
  }
  return <Pill tone="neutral">Not mapped</Pill>;
}

export function EstimateTable({
  estimate,
  selectedLineId,
  onOpenLine,
}: {
  estimate: Estimate;
  selectedLineId: string | null;
  onOpenLine: (lineId: string) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const currency = estimate.currency;

  const columns = useMemo(
    () => [
      column.accessor("item_number", {
        header: "Item",
        enableSorting: false,
        cell: (info) => (
          <span className="font-mono text-xs whitespace-nowrap text-subtle">
            {info.getValue() || "-"}
          </span>
        ),
      }),
      column.accessor("description", {
        header: "Description",
        enableSorting: false,
        cell: ({ row }) => {
          const line = row.original;
          return (
            <div className="min-w-56">
              <span
                className={cn(
                  "font-medium text-ink",
                  line.review_status === "excluded" && "text-subtle line-through",
                )}
              >
                {line.description}
              </span>
              <span className="mt-1 flex flex-wrap gap-1 empty:hidden">
                {line.review_status === "reviewed" && (
                  <Pill tone="ok">
                    <CheckIcon className="size-3" aria-hidden="true" />
                    Reviewed
                  </Pill>
                )}
                {line.review_status === "excluded" && <Pill tone="neutral">Excluded</Pill>}
                {line.reviewer_edits.length > 0 && (
                  <Pill tone="brand">
                    <PencilIcon className="size-3" aria-hidden="true" />
                    Edited
                  </Pill>
                )}
              </span>
            </div>
          );
        },
      }),
      column.accessor((line) => Number(line.quantity), {
        id: "quantity",
        header: "Qty",
        meta: { numeric: true },
        cell: ({ row }) => formatQuantity(row.original.quantity),
      }),
      column.accessor("unit", { header: "Unit", enableSorting: false }),
      column.display({
        id: "rate",
        header: "Production rate",
        cell: ({ row }) => <RateCell line={row.original} />,
      }),
      column.accessor((line) => Number(line.line_subtotal), {
        id: "line_subtotal",
        header: "Line subtotal",
        meta: { numeric: true },
        cell: ({ row }) => (
          <span className="font-medium text-ink">
            {formatMoney(row.original.line_subtotal, currency)}
          </span>
        ),
      }),
      column.accessor((line) => Number(line.subtotal_share_pct ?? -1), {
        id: "share",
        header: "% of subtotal",
        meta: { numeric: true },
        cell: ({ row }) => formatPct(row.original.subtotal_share_pct),
      }),
      column.display({
        id: "flags",
        header: "Flags",
        cell: ({ row }) => {
          const flags = sortFlags(row.original.flags);
          if (flags.length === 0) return <span className="text-subtle">None</span>;
          return (
            <span className="flex max-w-64 flex-wrap gap-1">
              {flags.slice(0, MAX_BADGES).map((flag, index) => (
                <FlagBadge key={`${flag.code}-${index}`} flag={flag} />
              ))}
              {flags.length > MAX_BADGES && (
                <Pill tone="neutral">+{flags.length - MAX_BADGES}</Pill>
              )}
            </span>
          );
        },
      }),
    ],
    [currency],
  );

  // TanStack Table returns functions the React Compiler cannot memoise; the
  // table is cheap to rebuild, so the directive just opts this component out.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: estimate.lines,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getRowId: (line) => line.id,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (estimate.lines.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-page px-5 py-10 text-center">
        <p className="font-medium text-ink">No bid items were found in this document.</p>
        <p className="mt-1 text-sm text-body">
          Check the skipped rows below, or hand off a different bid schedule.
        </p>
      </div>
    );
  }

  return (
    <div className="relative overflow-x-auto rounded-lg border border-line bg-page">
      <table className="w-full min-w-[56rem] border-collapse text-sm">
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b border-line bg-surface">
              {group.headers.map((header) => {
                const numeric = (header.column.columnDef.meta as { numeric?: boolean } | undefined)
                  ?.numeric;
                const sorted = header.column.getIsSorted();
                const SortIcon =
                  sorted === "asc" ? ArrowUpIcon : sorted === "desc" ? ArrowDownIcon : ArrowUpDownIcon;
                return (
                  <th
                    key={header.id}
                    scope="col"
                    aria-sort={
                      sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined
                    }
                    className={cn(
                      "eyebrow px-4 py-3 text-subtle",
                      numeric ? "text-right" : "text-left",
                    )}
                  >
                    {header.column.getCanSort() ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={cn(
                          "inline-flex items-center gap-1 tracking-[inherit] uppercase hover:text-ink",
                          numeric && "flex-row-reverse",
                        )}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <SortIcon
                          className={cn("size-3", sorted ? "text-brand" : "opacity-50")}
                          aria-hidden="true"
                        />
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              tabIndex={0}
              role="button"
              aria-label={`Open line ${row.original.item_number || row.original.id}: ${row.original.description}`}
              onClick={() => onOpenLine(row.original.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onOpenLine(row.original.id);
                }
              }}
              className={cn(
                "cursor-pointer border-b border-line align-top transition-colors last:border-b-0 hover:bg-surface focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand",
                selectedLineId === row.original.id && "bg-brand-soft hover:bg-brand-soft",
                row.original.review_status === "excluded" && "text-subtle",
              )}
            >
              {row.getVisibleCells().map((cell) => {
                const numeric = (cell.column.columnDef.meta as { numeric?: boolean } | undefined)
                  ?.numeric;
                return (
                  <td key={cell.id} className={cn("px-4 py-3", numeric && "num")}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
