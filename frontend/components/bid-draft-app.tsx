"use client";

import { ArrowDownIcon, FileTextIcon, ShieldCheckIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Container, Eyebrow, Logo, SectionHeading } from "@/components/brand";
import { Handoff, type Loadable } from "@/components/handoff";
import { Pipeline, type PipelineState } from "@/components/pipeline";
import { AuditLog, SkippedRows, TotalsCard } from "@/components/review/details";
import { EstimateTable } from "@/components/review/estimate-table";
import { LinePanel } from "@/components/review/line-panel";
import { ReviewFirst } from "@/components/review/review-first";
import { SummaryHeader } from "@/components/review/summary-header";
import { Button } from "@/components/ui/button";
import { ApiError, draftFromFile, draftFromSample, getRateCard, getSamples } from "@/lib/api";
import type { Estimate, RateCard, SampleBid } from "@/lib/types";
import { useReviewSession } from "@/lib/use-review-session";

/** What was handed off, kept so a failed run can be retried. */
type Source = { name: string; draft: () => Promise<Estimate> };

function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError("Something went wrong", error instanceof Error ? error.message : "");
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function BidDraftApp() {
  const [samples, setSamples] = useState<Loadable<SampleBid[]>>({ state: "loading" });
  const [rateCard, setRateCard] = useState<Loadable<RateCard>>({ state: "loading" });
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null);
  const review = useReviewSession();
  const { session } = review;
  const workSection = useRef<HTMLElement>(null);
  const reviewSection = useRef<HTMLElement>(null);

  const load = useCallback(() => {
    getSamples()
      .then((value) => setSamples({ state: "ready", value }))
      .catch((error) => setSamples({ state: "error", error: asApiError(error) }));
    getRateCard()
      .then((value) => setRateCard({ state: "ready", value }))
      .catch((error) => setRateCard({ state: "error", error: asApiError(error) }));
  }, []);

  useEffect(load, [load]);

  const retryLoad = () => {
    setSamples({ state: "loading" });
    setRateCard({ state: "loading" });
    load();
  };

  const { start } = review;
  const run = useCallback(
    async (next: Source) => {
      const startedAt = Date.now();
      setSource(next);
      setSelectedLineId(null);
      setPipeline({ status: "running", sourceName: next.name, startedAt });
      requestAnimationFrame(() => workSection.current?.scrollIntoView({ block: "start" }));
      try {
        const estimate = await next.draft();
        setPipeline({
          status: "done",
          sourceName: next.name,
          seconds: (Date.now() - startedAt) / 1000,
          estimate,
        });
        start(next.name, estimate);
      } catch (error) {
        setPipeline({ status: "failed", sourceName: next.name, error: asApiError(error) });
      }
    },
    [start],
  );

  const startOver = () => {
    review.reset();
    setPipeline(null);
    setSource(null);
    setSelectedLineId(null);
    window.scrollTo({ top: 0 });
  };

  const onExport = async () => {
    try {
      const file = await review.exportXlsx();
      if (file) {
        download(file.blob, file.filename);
        toast.success("Estimate exported", { description: file.filename });
      }
    } catch (error) {
      const apiError = asApiError(error);
      toast.error(apiError.title, { description: apiError.message });
    }
  };

  const selectedLine = session?.estimate.lines.find((line) => line.id === selectedLineId) ?? null;
  const handedOff = pipeline !== null;

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-line bg-page/95 backdrop-blur">
        <Container className="flex h-16 items-center justify-between gap-4">
          <Logo />
          <nav aria-label="Steps" className="hidden items-center gap-7 text-sm text-body md:flex">
            <a href="#hand-off" className="hover:text-ink">
              You hand off
            </a>
            <a href="#agent-works" className="hover:text-ink">
              The agent works
            </a>
            <a href="#what-comes-back" className="hover:text-ink">
              What comes back
            </a>
            <Link href="/evals" className="hover:text-ink">
              Evals
            </Link>
          </nav>
          {handedOff ? (
            <Button size="lg" className="h-9 px-4" onClick={startOver}>
              New bid
            </Button>
          ) : (
            <span className="eyebrow hidden text-subtle sm:block">Draft, then review</span>
          )}
        </Container>
      </header>

      <main className="flex-1">
        {/* 01 You hand off */}
        <section id="hand-off" className="scroll-mt-16">
          {handedOff ? (
            <Container className="flex flex-col gap-3 py-6 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <Eyebrow>01 / You handed off</Eyebrow>
                <p className="mt-2 flex flex-wrap items-center gap-x-2 text-lg font-medium text-ink">
                  <FileTextIcon className="size-4 text-subtle" aria-hidden="true" />
                  {pipeline.sourceName}
                  {rateCard.state === "ready" && (
                    <span className="text-base font-normal text-body">
                      priced with the {rateCard.value.company_name} rate card
                    </span>
                  )}
                </p>
              </div>
              <Button variant="outline" size="lg" onClick={startOver}>
                Hand off another bid
              </Button>
            </Container>
          ) : (
            <>
              <Container className="pt-14 pb-12 text-center sm:pt-20">
                <Eyebrow className="text-subtle">Bid Draft / Review</Eyebrow>
                <h1 className="mx-auto mt-6 max-w-5xl text-4xl leading-[1.05] font-medium sm:text-6xl">
                  A draft estimate from your bid schedule.
                  <span className="block text-brand">Priced with your rates.</span>
                </h1>
                <p className="mx-auto mt-6 max-w-xl text-lg leading-relaxed text-body">
                  Hand off a bid schedule. The agent reads it, maps each line to your company
                  standards and prices it in code. Your estimator reviews what matters most.
                </p>
                <a
                  href="#hand-off-form"
                  className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-ink hover:text-brand"
                >
                  Start with a bid schedule
                  <ArrowDownIcon className="size-4" aria-hidden="true" />
                </a>
              </Container>
              <Container className="pb-20">
                <div id="hand-off-form" className="scroll-mt-24">
                  <SectionHeading eyebrow="01 / You hand off" title="One bid schedule.">
                    Upload yours, or pick a sample. The estimate is priced against the rate card
                    shown below.
                  </SectionHeading>
                  <div className="mt-8">
                    <Handoff
                      samples={samples}
                      rateCard={rateCard}
                      onRetry={retryLoad}
                      onFile={(file) =>
                        run({ name: file.name, draft: () => draftFromFile(file) })
                      }
                      onSample={(sample) =>
                        run({ name: sample.filename, draft: () => draftFromSample(sample.id) })
                      }
                    />
                  </div>
                </div>
              </Container>
            </>
          )}
        </section>

        {/* 02 The agent works */}
        {pipeline && (
          <section
            id="agent-works"
            ref={workSection}
            className="scroll-mt-16 bg-night py-14 sm:py-20"
          >
            <Container>
              <Pipeline
                state={pipeline}
                onRetry={() => source && run(source)}
                onBack={startOver}
              />
            </Container>
          </section>
        )}

        {/* 03 What comes back */}
        {session && (
          <section
            id="what-comes-back"
            ref={reviewSection}
            className="scroll-mt-16 bg-surface py-14 sm:py-20"
          >
            <Container className="space-y-6">
              <SectionHeading
                eyebrow="03 / What comes back"
                title="A draft estimate."
                muted="With the reasons to check it."
              >
                Every line carries its source row, its calculation and its assumptions. Open a
                line to see them and to step in.
              </SectionHeading>

              <SummaryHeader
                estimate={session.estimate}
                approvedAt={session.approvedAt}
                busy={review.busy}
                onApprove={review.approve}
                onExport={onExport}
              />

              <ReviewFirst estimate={session.estimate} onOpenLine={setSelectedLineId} />

              <div>
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-lg font-medium">
                    Estimate{" "}
                    <span className="text-subtle tabular-nums">
                      ({session.estimate.lines.length} lines)
                    </span>
                  </h3>
                  <p className="text-sm text-subtle">Select a line to review it</p>
                </div>
                <EstimateTable
                  estimate={session.estimate}
                  selectedLineId={selectedLineId}
                  onOpenLine={setSelectedLineId}
                />
              </div>

              <SkippedRows rows={session.estimate.skipped_rows} />

              <div className="grid items-start gap-6 lg:grid-cols-[1fr_1.2fr]">
                <TotalsCard estimate={session.estimate} />
                <div>
                  <AuditLog entries={session.audit} />
                  <p className="mt-3 flex items-start gap-2 text-sm text-body">
                    <ShieldCheckIcon
                      className="mt-0.5 size-4 shrink-0 text-subtle"
                      aria-hidden="true"
                    />
                    Where your people step in: the estimator sets quantities and rates, reviews
                    or excludes lines, and approves. Every change is repriced by the backend and
                    recorded here.
                  </p>
                </div>
              </div>
            </Container>
          </section>
        )}
      </main>

      <footer className="border-t border-line">
        <Container className="flex flex-col gap-2 py-6 text-xs text-subtle sm:flex-row sm:justify-between">
          <p>Bid Draft Agent. The LLM extracts and classifies; company data and code price.</p>
          <p>
            Sample data is for a fictional company.{" "}
            <Link href="/evals" className="underline underline-offset-2 hover:text-ink">
              How it is evaluated
            </Link>
          </p>
        </Container>
      </footer>

      <LinePanel
        line={selectedLine}
        currency={session?.estimate.currency ?? "USD"}
        rateCard={rateCard.state === "ready" ? rateCard.value : null}
        busy={review.busy}
        actions={review}
        onClose={() => setSelectedLineId(null)}
      />
    </>
  );
}
