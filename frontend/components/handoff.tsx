"use client";

import { ArrowRightIcon, FileSpreadsheetIcon, FileTextIcon, UploadIcon } from "lucide-react";
import { useRef, useState } from "react";

import { StepNumber } from "@/components/brand";
import { RateCardDialog } from "@/components/rate-card-dialog";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";
import type { RateCard, SampleBid } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPT = ".pdf,.xlsx,.xlsm,.csv";

/** A value that is still loading, has loaded, or failed to load. */
export type Loadable<T> =
  | { state: "loading" }
  | { state: "ready"; value: T }
  | { state: "error"; error: ApiError };

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface", className)} />;
}

function LoadError({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-line bg-blocker-soft p-4 text-sm">
      <p className="font-medium text-blocker">{error.title}</p>
      <p className="mt-1 text-body">{error.message}</p>
      <Button variant="outline" size="lg" className="mt-3" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function UploadCard({ onFile }: { onFile: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files[0];
        if (file) onFile(file);
      }}
      className={cn(
        "flex h-full flex-col items-start justify-between gap-6 rounded-lg border border-dashed border-input bg-page p-6 transition-colors",
        dragging && "border-brand bg-brand-soft",
      )}
    >
      <div>
        <UploadIcon className="size-5 text-brand" aria-hidden="true" />
        <h3 className="mt-4 text-xl font-medium">Upload a bid schedule</h3>
        <p className="mt-2 text-sm leading-relaxed text-body">
          Drop a file here or choose one. PDF, Excel (.xlsx) or CSV. Scanned PDFs without a text
          layer cannot be read.
        </p>
      </div>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        aria-label="Bid schedule file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = "";
        }}
      />
      <Button size="lg" className="h-10 px-4" onClick={() => input.current?.click()}>
        Choose a file
        <ArrowRightIcon data-icon="inline-end" />
      </Button>
    </div>
  );
}

export function Handoff({
  samples,
  rateCard,
  onFile,
  onSample,
  onRetry,
}: {
  samples: Loadable<SampleBid[]>;
  rateCard: Loadable<RateCard>;
  onFile: (file: File) => void;
  onSample: (sample: SampleBid) => void;
  onRetry: () => void;
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.25fr]">
      <UploadCard onFile={onFile} />

      <div className="rounded-lg border border-line bg-surface p-6">
        <p className="eyebrow text-subtle">Or start from a sample bid</p>
        {samples.state === "loading" && (
          <div className="mt-4 space-y-2" aria-label="Loading sample bids">
            <Skeleton className="h-[4.5rem] bg-page" />
            <Skeleton className="h-[4.5rem] bg-page" />
            <Skeleton className="h-[4.5rem] bg-page" />
          </div>
        )}
        {samples.state === "error" && (
          <div className="mt-4">
            <LoadError error={samples.error} onRetry={onRetry} />
          </div>
        )}
        {samples.state === "ready" && samples.value.length === 0 && (
          <p className="mt-4 text-sm text-body">The backend has no sample bids. Upload a file.</p>
        )}
        {samples.state === "ready" && (
          <ul className="mt-4 space-y-2">
            {samples.value.map((sample, index) => {
              const Icon = sample.filename.endsWith(".pdf") ? FileTextIcon : FileSpreadsheetIcon;
              return (
                <li key={sample.id}>
                  <button
                    type="button"
                    onClick={() => onSample(sample)}
                    className="group flex w-full items-start gap-3 rounded-md border border-line bg-page p-4 text-left transition-colors hover:border-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                  >
                    <StepNumber n={index + 1} className="mt-1" />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-2 font-medium text-ink">
                        {sample.title}
                        <span className="inline-flex items-center gap-1 font-mono text-xs font-normal text-subtle">
                          <Icon className="size-3.5" aria-hidden="true" />
                          {sample.filename}
                        </span>
                      </span>
                      <span className="mt-1 block text-sm text-body">{sample.description}</span>
                    </span>
                    <ArrowRightIcon
                      className="mt-1 size-4 shrink-0 text-subtle transition-transform group-hover:translate-x-0.5 group-hover:text-brand"
                      aria-hidden="true"
                    />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-line bg-page p-6 lg:col-span-2">
        <p className="eyebrow text-subtle">Rate card in use</p>
        {rateCard.state === "loading" && <Skeleton className="mt-4 h-16" />}
        {rateCard.state === "error" && (
          <div className="mt-4">
            <LoadError error={rateCard.error} onRetry={onRetry} />
          </div>
        )}
        {rateCard.state === "ready" && (
          <div className="mt-3 flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div>
              <h3 className="text-xl font-medium">{rateCard.value.company_name}</h3>
              <p className="mt-1 text-sm text-body">
                {rateCard.value.trade} · prices in {rateCard.value.currency}
              </p>
            </div>
            <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
              {[
                ["Labor rates", rateCard.value.labor_rates.length],
                ["Materials", rateCard.value.materials.length],
                ["Equipment", rateCard.value.equipment.length],
                ["Production rates", rateCard.value.production_rates.length],
              ].map(([label, count]) => (
                <div key={label}>
                  <dd className="text-2xl font-medium text-ink tabular-nums">{count}</dd>
                  <dt className="text-xs text-subtle">{label}</dt>
                </div>
              ))}
            </dl>
            <RateCardDialog rateCard={rateCard.value} />
          </div>
        )}
      </div>
    </div>
  );
}
