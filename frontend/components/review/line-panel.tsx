"use client";

import { CheckIcon, RotateCcwIcon, SparklesIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Eyebrow } from "@/components/brand";
import { RateCell } from "@/components/review/estimate-table";
import { Pill, SEVERITY_LABEL, SeverityIcon } from "@/components/review/flag-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { flagLabel, formatMoney, formatPct, formatQuantity } from "@/lib/format";
import { openFlags, parseQuantityInput, sortFlags, suggestedRate } from "@/lib/review";
import type { PricedLine, RateCard } from "@/lib/types";
import type { ReviewActions } from "@/lib/use-review-session";
import { cn } from "@/lib/utils";

function PanelSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line px-5 py-5">
      <h3 className="eyebrow mb-3 text-subtle">{title}</h3>
      {children}
    </section>
  );
}

const CONFIDENCE_TONE = { high: "ok", medium: "neutral", low: "warning" } as const;

/** Run a reviewer action and show the backend's message if it refuses. */
async function run(action: () => Promise<void>, done?: string) {
  try {
    await action();
    if (done) toast.success(done);
  } catch (error) {
    if (error instanceof ApiError) toast.error(error.title, { description: error.message });
    else throw error;
  }
}

function ReviewerActions({
  line,
  rateCard,
  busy,
  actions,
}: {
  line: PricedLine;
  rateCard: RateCard | null;
  busy: boolean;
  actions: ReviewActions;
}) {
  const [quantity, setQuantity] = useState(line.quantity);
  const [excluding, setExcluding] = useState(false);
  const [reason, setReason] = useState("");

  const excluded = line.review_status === "excluded";
  const reviewed = line.review_status === "reviewed";
  const parsed = parseQuantityInput(quantity);
  const quantityChanged = parsed !== null && Number(parsed) !== Number(line.quantity);
  const suggestion = suggestedRate(line);
  const suggested = rateCard?.production_rates.find((rate) => rate.code === suggestion);
  const hardBlockers = openFlags(line).filter((flag) => flag.severity === "blocker");

  if (excluded) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-body">
          Excluded from the estimate. Reason:{" "}
          <span className="font-medium text-ink">{line.exclusion_reason}</span>
        </p>
        <Button
          variant="outline"
          size="lg"
          disabled={busy}
          onClick={() => run(() => actions.setStatus(line.id, "open"), "Line restored")}
        >
          <RotateCcwIcon data-icon="inline-start" />
          Restore line
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {suggestion && (
        <div className="rounded-md border border-brand/30 bg-brand-soft p-3">
          <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
            <SparklesIcon className="size-4 text-brand" aria-hidden="true" />
            A company standard rate matches this line
          </p>
          <p className="mt-1 text-sm text-body">
            <span className="font-mono text-xs text-ink">{suggestion}</span>
            {suggested && ` · ${suggested.description}, per ${suggested.unit}`}
          </p>
          <Button
            className="mt-3"
            size="lg"
            disabled={busy}
            onClick={() =>
              run(
                () => actions.setProductionRate(line.id, suggestion, true),
                `Applied ${suggestion}`,
              )
            }
          >
            Apply {suggestion}
          </Button>
        </div>
      )}

      <form
        className="space-y-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          if (parsed !== null && quantityChanged) {
            void run(() => actions.setQuantity(line.id, parsed), "Quantity updated and repriced");
          }
        }}
      >
        <Label htmlFor="line-quantity">Quantity ({line.unit || "no unit"})</Label>
        <div className="flex gap-2">
          <Input
            id="line-quantity"
            inputMode="decimal"
            className="num h-9"
            value={quantity}
            aria-invalid={parsed === null}
            aria-describedby={parsed === null ? "line-quantity-error" : undefined}
            onChange={(event) => setQuantity(event.target.value)}
          />
          <Button type="submit" variant="outline" size="lg" disabled={busy || !quantityChanged}>
            Reprice
          </Button>
        </div>
        {parsed === null && (
          <p id="line-quantity-error" className="text-xs text-blocker">
            Enter a number that is zero or more, for example 40 or 1,850.5.
          </p>
        )}
      </form>

      <div className="space-y-1.5">
        <Label htmlFor="line-rate">Production rate</Label>
        <Select
          value={line.production_rate_code ?? ""}
          disabled={busy || !rateCard}
          onValueChange={(code) => {
            if (code !== line.production_rate_code) {
              void run(() => actions.setProductionRate(line.id, code), `Repriced with ${code}`);
            }
          }}
        >
          <SelectTrigger id="line-rate" className="h-9 w-full">
            <SelectValue
              placeholder={
                line.rate_basis === "assumed"
                  ? "Assumed by the LLM. Choose a company rate"
                  : "Choose a company rate"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {rateCard?.production_rates.map((rate) => (
              <SelectItem key={rate.code} value={rate.code}>
                <span className="font-mono text-xs">{rate.code}</span>
                <span className="text-subtle">
                  {rate.description} · per {rate.unit}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-subtle">
          From the {rateCard?.company_name ?? "company"} rate card. The backend reprices the line.
        </p>
      </div>

      {excluding ? (
        <form
          className="space-y-2 rounded-md border border-line p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (reason.trim()) {
              void run(
                () => actions.setStatus(line.id, "excluded", reason.trim()),
                "Line excluded",
              );
            }
          }}
        >
          <Label htmlFor="exclusion-reason">Why is this line excluded? (required)</Label>
          <Textarea
            id="exclusion-reason"
            value={reason}
            autoFocus
            rows={2}
            placeholder="For example: by owner, or priced under another item"
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit" variant="destructive" size="lg" disabled={busy || !reason.trim()}>
              Exclude line
            </Button>
            <Button type="button" variant="ghost" size="lg" onClick={() => setExcluding(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          {reviewed ? (
            <Button
              variant="outline"
              size="lg"
              disabled={busy}
              onClick={() => run(() => actions.setStatus(line.id, "open"), "Line reopened")}
            >
              <RotateCcwIcon data-icon="inline-start" />
              Reopen
            </Button>
          ) : (
            <Button
              size="lg"
              disabled={busy}
              onClick={() => run(() => actions.setStatus(line.id, "reviewed"), "Marked reviewed")}
            >
              <CheckIcon data-icon="inline-start" />
              Mark reviewed
            </Button>
          )}
          <Button variant="outline" size="lg" disabled={busy} onClick={() => setExcluding(true)}>
            Exclude line
          </Button>
          {line.reviewer_edits.length > 0 && (
            <Button
              variant="ghost"
              size="lg"
              disabled={busy}
              onClick={() => run(() => actions.resetLine(line.id), "Line reset to the draft")}
            >
              Reset to draft
            </Button>
          )}
        </div>
      )}

      {reviewed && hardBlockers.length > 0 && (
        <p className="rounded-md bg-blocker-soft p-3 text-sm text-blocker">
          Marking the line reviewed does not clear{" "}
          {hardBlockers.map((flag) => flagLabel(flag.code)).join(", ")}: the line is not priced
          properly. Fix it above or exclude the line.
        </p>
      )}
    </div>
  );
}

export function LinePanel({
  line,
  currency,
  rateCard,
  busy,
  actions,
  onClose,
}: {
  line: PricedLine | null;
  currency: string;
  rateCard: RateCard | null;
  busy: boolean;
  actions: ReviewActions;
  onClose: () => void;
}) {
  return (
    <Sheet open={line !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
        {line && (
          <>
            <SheetHeader className="px-5 pt-5 pb-4">
              <Eyebrow>
                Line {line.id}
                {line.item_number && ` / Item ${line.item_number}`}
              </Eyebrow>
              <SheetTitle className="pr-8 text-xl leading-snug font-medium text-ink">
                {line.description}
              </SheetTitle>
              <SheetDescription className="sr-only">
                Source, calculation, assumptions and flags for this line, and the reviewer actions.
              </SheetDescription>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                {[
                  ["Quantity", `${formatQuantity(line.quantity)} ${line.unit}`],
                  ["Line subtotal", formatMoney(line.line_subtotal, currency)],
                  ["% of subtotal", formatPct(line.subtotal_share_pct)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs text-subtle">{label}</dt>
                    <dd className="mt-0.5 font-medium text-ink tabular-nums">{value}</dd>
                  </div>
                ))}
                <div>
                  <dt className="text-xs text-subtle">Production rate</dt>
                  <dd className="mt-0.5">
                    <RateCell line={line} />
                  </dd>
                </div>
              </dl>
            </SheetHeader>

            <PanelSection title="Where your people step in">
              {/* Keyed so the form starts from the repriced line's values. */}
              <ReviewerActions
                key={`${line.id}:${line.quantity}:${line.production_rate_code}:${line.review_status}`}
                line={line}
                rateCard={rateCard}
                busy={busy}
                actions={actions}
              />
            </PanelSection>

            <PanelSection title={`Flags (${openFlags(line).length} open)`}>
              {line.flags.length === 0 ? (
                <p className="text-sm text-body">No flags on this line.</p>
              ) : (
                <ul className="space-y-3">
                  {sortFlags(line.flags).map((flag, index) => (
                    <li
                      key={`${flag.code}-${index}`}
                      className={cn("flex gap-2.5", flag.resolved && "opacity-60")}
                    >
                      <SeverityIcon
                        severity={flag.severity}
                        className={cn(
                          "mt-0.5 size-4",
                          flag.severity === "blocker" && "text-blocker",
                          flag.severity === "warning" && "text-warning",
                        )}
                      />
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-x-2 text-sm font-medium text-ink">
                          {flagLabel(flag.code)}
                          <span className="font-normal text-subtle">
                            {SEVERITY_LABEL[flag.severity]}
                            {flag.resolved && ", resolved"}
                          </span>
                        </p>
                        <p className="mt-0.5 text-sm break-words text-body">{flag.message}</p>
                        <p className="mt-0.5 font-mono text-[0.6875rem] text-subtle">{flag.code}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </PanelSection>

            <PanelSection title="Source reference">
              <p className="text-sm text-body">
                {line.source_ref ? (
                  <>
                    Row <span className="font-mono text-xs text-ink">{line.source_ref}</span> of the
                    bid schedule
                    {line.item_number && `, item ${line.item_number}`}.
                  </>
                ) : (
                  "This line has no source reference."
                )}
              </p>
            </PanelSection>

            <PanelSection title="Calculation trace">
              <ol className="space-y-1.5 font-mono text-xs leading-relaxed text-ink">
                {line.calculation_trace.map((step, index) => (
                  <li key={index} className="break-words">
                    {step}
                  </li>
                ))}
              </ol>
            </PanelSection>

            <PanelSection title="The LLM's rationale and confidence">
              {line.mapping_rationale || line.mapping_confidence ? (
                <div className="space-y-2">
                  {line.mapping_confidence && (
                    <Pill tone={CONFIDENCE_TONE[line.mapping_confidence]}>
                      {line.mapping_confidence} confidence
                    </Pill>
                  )}
                  <p className="text-sm text-body">
                    {line.mapping_rationale ?? "The LLM gave no rationale."}
                  </p>
                  {line.reviewer_edits.includes("production_rate") && (
                    <p className="text-xs text-subtle">
                      This was the LLM&apos;s reasoning for the draft. The reviewer has since chosen
                      the production rate.
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-body">The LLM returned no mapping for this line.</p>
              )}
            </PanelSection>

            <PanelSection title={`Assumptions (${line.assumptions.length})`}>
              {line.assumptions.length === 0 ? (
                <p className="text-sm text-body">No assumptions were recorded.</p>
              ) : (
                <ul className="list-disc space-y-1.5 pl-4 text-sm text-body marker:text-subtle">
                  {line.assumptions.map((assumption, index) => (
                    <li key={index} className="break-words">
                      {assumption}
                    </li>
                  ))}
                </ul>
              )}
            </PanelSection>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
