"use client";

import { CircleCheckIcon, FlaskConicalIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Container, Eyebrow, Logo, SectionHeading } from "@/components/brand";
import { CaseTable } from "@/components/evals/case-table";
import { FailureList } from "@/components/evals/failure-list";
import { Headline } from "@/components/evals/headline";
import { ModelComparison } from "@/components/evals/model-comparison";
import { Button } from "@/components/ui/button";
import { ApiError, getLatestEvals } from "@/lib/api";
import type { EvalResult } from "@/lib/evals";
import { cn } from "@/lib/utils";

type State =
  | { state: "loading" }
  | { state: "ready"; results: EvalResult[] }
  | { state: "empty"; message: string }
  | { state: "error"; error: ApiError };

export function EvalsApp() {
  const [data, setData] = useState<State>({ state: "loading" });
  const [model, setModel] = useState<string | null>(null);

  const load = useCallback(() => {
    getLatestEvals()
      .then(({ results }) => setData({ state: "ready", results }))
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) {
          setData({ state: "empty", message: error.message });
        } else {
          setData({
            state: "error",
            error:
              error instanceof ApiError
                ? error
                : new ApiError("Something went wrong", error instanceof Error ? error.message : ""),
          });
        }
      });
  }, []);

  useEffect(load, [load]);

  const results = data.state === "ready" ? data.results : [];
  const selected = results.find((result) => result.meta.model === model) ?? results[0] ?? null;

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-line bg-page/95 backdrop-blur">
        <Container className="flex h-16 items-center justify-between gap-4">
          <Link href="/" aria-label="Bid Draft Agent, home">
            <Logo />
          </Link>
          <nav aria-label="Sections" className="hidden items-center gap-7 text-sm text-body md:flex">
            <a href="#headline" className="hover:text-ink">
              Headline numbers
            </a>
            <a href="#comparison" className="hover:text-ink">
              Model comparison
            </a>
            <a href="#cases" className="hover:text-ink">
              Cases
            </a>
            <a href="#weaknesses" className="hover:text-ink">
              Known weaknesses
            </a>
          </nav>
          <Button asChild variant="outline" size="lg" className="h-9 px-4">
            <Link href="/">Draft a bid</Link>
          </Button>
        </Container>
      </header>

      <main className="flex-1">
        <Container className="pt-14 pb-10 sm:pt-20">
          <Eyebrow className="text-subtle">Bid Draft / Evals</Eyebrow>
          <h1 className="mt-6 max-w-4xl text-4xl leading-[1.05] font-medium sm:text-6xl">
            How well the agent reads a bid.
            <span className="block text-brand">Measured, failures included.</span>
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-body">
            Each bid schedule in the eval set has an expected answer for every line. The agent
            drafts each bid several times with the cache off, and every run is compared with
            that answer.
          </p>
        </Container>

        {data.state === "loading" && (
          <Container className="pb-20">
            <p className="text-sm text-subtle">Loading the latest eval results...</p>
          </Container>
        )}

        {data.state === "empty" && (
          <Container className="pb-20">
            <div className="rounded-lg border border-line bg-surface p-6">
              <p className="flex items-center gap-2 text-lg font-medium text-ink">
                <FlaskConicalIcon className="size-5 text-subtle" aria-hidden="true" />
                No eval has been run yet
              </p>
              <p className="mt-2 text-sm text-body">{data.message}</p>
            </div>
          </Container>
        )}

        {data.state === "error" && (
          <Container className="pb-20">
            <div role="alert" className="rounded-lg border border-line bg-blocker-soft p-6">
              <p className="text-lg font-medium text-blocker">{data.error.title}</p>
              <p className="mt-2 text-sm text-ink">{data.error.message}</p>
              <Button
                variant="outline"
                size="lg"
                className="mt-4"
                onClick={() => {
                  setData({ state: "loading" });
                  load();
                }}
              >
                Try again
              </Button>
            </div>
          </Container>
        )}

        {selected && (
          <>
            <Container className="pb-12">
              <DatasetNote result={selected} />
              {results.length > 1 && (
                <div className="mt-6 flex flex-wrap items-center gap-2">
                  <span className="eyebrow mr-2 text-subtle">Model</span>
                  {results.map((result) => (
                    <button
                      key={result.meta.model}
                      type="button"
                      aria-pressed={result === selected}
                      onClick={() => setModel(result.meta.model)}
                      className={cn(
                        "h-9 rounded-md border px-3 font-mono text-xs focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
                        result === selected
                          ? "border-brand bg-brand text-on-brand"
                          : "border-line bg-page text-body hover:text-ink",
                      )}
                    >
                      {result.meta.model}
                    </button>
                  ))}
                </div>
              )}
            </Container>

            <section id="headline" className="scroll-mt-16 bg-surface py-14 sm:py-20">
              <Container className="space-y-6">
                <SectionHeading
                  eyebrow="01 / Headline numbers"
                  title="Four numbers."
                  muted="Each with the counts behind it."
                >
                  For <span className="font-mono text-sm text-ink">{selected.meta.model}</span>.
                  Accuracy and money over {selected.summary.runs_scored} runs of{" "}
                  {selected.summary.cases} bids; stability over the{" "}
                  {selected.summary.stability_cases} bids that were run more than once.
                </SectionHeading>
                <Headline summary={selected.summary} />
              </Container>
            </section>

            <section id="comparison" className="scroll-mt-16 py-14 sm:py-20">
              <Container className="space-y-6">
                <SectionHeading eyebrow="02 / Model comparison" title="The same bids, side by side.">
                  The newest eval of each model. Every model ran the same cases against the same
                  expected answers.
                </SectionHeading>
                <ModelComparison results={results} />
              </Container>
            </section>

            <section id="cases" className="scroll-mt-16 bg-surface py-14 sm:py-20">
              <Container className="space-y-6">
                <SectionHeading
                  eyebrow="03 / Cases"
                  title="Bid by bid."
                  muted="Every failure, expected against what came back."
                >
                  Select a failure to see what was expected and what each run returned.
                </SectionHeading>
                <CaseTable cases={selected.cases} />
                <FailureList cases={selected.cases} />
              </Container>
            </section>

            <section id="weaknesses" className="scroll-mt-16 py-14 sm:py-20">
              <Container className="space-y-6">
                <SectionHeading eyebrow="04 / Known weaknesses" title="What went wrong, grouped.">
                  Generated from the failures above, most frequent first. Nothing here is written
                  by hand.
                </SectionHeading>
                <Weaknesses result={selected} />
              </Container>
            </section>
          </>
        )}
      </main>

      <footer className="border-t border-line">
        <Container className="flex flex-col gap-2 py-6 text-xs text-subtle sm:flex-row sm:justify-between">
          <p>Bid Draft Agent. The LLM extracts and classifies; company data and code price.</p>
          <p>The eval dataset is synthetic, for a fictional company.</p>
        </Container>
      </footer>
    </>
  );
}

/** What the numbers rest on: a synthetic dataset, and how much of it a person has checked. */
function DatasetNote({ result }: { result: EvalResult }) {
  const { dataset, meta } = result;
  const allVerified = dataset.hand_verified === dataset.cases;
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-page">
      <div className="grid divide-y divide-line md:grid-cols-[1fr_2fr] md:divide-x md:divide-y-0">
        <div className="p-5 sm:p-6">
          <p className="eyebrow text-subtle">Hand-verified cases</p>
          <p className="mt-3 flex items-baseline gap-2">
            <span
              data-testid="hand-verified"
              className="text-4xl font-medium tracking-tight text-ink tabular-nums"
            >
              {dataset.hand_verified} of {dataset.cases}
            </span>
          </p>
          <p
            className={cn(
              "mt-2 flex items-start gap-1.5 text-sm",
              allVerified ? "text-ok" : "text-warning",
            )}
          >
            {allVerified ? (
              <CircleCheckIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            ) : (
              <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            )}
            {allVerified
              ? "A person has checked every expected answer."
              : "Scores on the other cases rest on expected answers nobody has checked yet."}
          </p>
        </div>
        <div className="p-5 sm:p-6">
          <p className="eyebrow text-subtle">Synthetic dataset</p>
          <p className="mt-3 text-sm leading-relaxed text-body">{dataset.note}</p>
          <p className="mt-3 font-mono text-xs text-subtle">
            run {meta.run_id} · {meta.runs_per_case} per case
            {meta.stability_cases.length > 0 &&
              `, ${meta.stability_runs} on ${meta.stability_cases.join(", ")}`}{" "}
            · temperature {meta.temperature}
            {meta.reasoning_effort && ` · reasoning effort ${meta.reasoning_effort}`} · cache off
          </p>
        </div>
      </div>
      {!meta.complete && (
        <p
          role="alert"
          className="flex items-start gap-2 border-t border-line bg-warning-soft px-5 py-3 text-sm text-warning sm:px-6"
        >
          <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>
            <span className="font-medium">This eval is not finished.</span> The numbers cover
            only the {result.summary.runs_total} runs made so far.
            {meta.stopped_because && ` Reason: ${meta.stopped_because}`}
          </span>
        </p>
      )}
    </div>
  );
}

function Weaknesses({ result }: { result: EvalResult }) {
  if (result.known_weaknesses.length === 0) {
    return (
      <p className="rounded-lg border border-line bg-page px-5 py-4 text-sm text-body">
        No failures in this run. That is a statement about these {result.summary.cases} cases
        only.
      </p>
    );
  }
  return (
    <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-page">
      {result.known_weaknesses.map((weakness, index) => (
        <li key={`${weakness.kind}-${index}`} className="flex gap-4 px-5 py-4">
          <span className="font-mono text-xs text-subtle tabular-nums">
            {String(index + 1).padStart(2, "0")}
          </span>
          <div className="min-w-0">
            <p className="font-medium text-ink">
              {weakness.title}
              {weakness.severity === "note" && (
                <span className="ml-2 text-sm font-normal text-subtle">(note, not an error)</span>
              )}
            </p>
            <p className="mt-1 text-sm text-body">{weakness.detail}</p>
            <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-sm">
              {weakness.examples.map((id) => (
                <a
                  key={id}
                  href={`#${id}`}
                  className="font-mono text-xs text-brand underline-offset-2 hover:underline"
                >
                  {id}
                </a>
              ))}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
