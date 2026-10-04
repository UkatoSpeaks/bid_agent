import { InfoIcon, OctagonAlertIcon } from "lucide-react";

import { Pill } from "@/components/review/flag-badge";
import { flagLabel, formatMoney, formatQuantity } from "@/lib/format";
import {
  failureLabel,
  type EvalActualLine,
  type EvalCase,
  type EvalExpectedLine,
  type EvalFailure,
} from "@/lib/evals";

const sameItem = (a: string, b: string) =>
  a.trim().replace(/\s+/g, " ").toUpperCase() === b.trim().replace(/\s+/g, " ").toUpperCase();

/** The expected line and what each run returned for that item number. */
function LineComparison({ evalCase, itemNumber }: { evalCase: EvalCase; itemNumber: string }) {
  const expected = evalCase.expected_lines.filter((line) => sameItem(line.item_number, itemNumber));
  const returned = evalCase.runs.flatMap((run) =>
    run.lines
      .filter((line) => sameItem(line.item_number, itemNumber))
      .map((line) => ({ run: run.run, line })),
  );
  if (expected.length === 0 && returned.length === 0) return null;

  const cell = "px-3 py-2 align-top";
  const expectedFlags = (line: EvalExpectedLine) =>
    line.required_flags.map((spec) => spec.any_of.map(flagLabel).join(" or ")).join(", ") || "none";
  const returnedFlags = (line: EvalActualLine) =>
    line.flags.map((flag) => flagLabel(flag.code)).join(", ") || "none";

  return (
    <div className="relative mt-3 overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-[40rem] text-sm">
        <thead>
          <tr className="border-b border-line bg-surface text-left">
            <th scope="col" className="eyebrow px-3 py-2 text-subtle">
              Item {itemNumber}
            </th>
            <th scope="col" className="eyebrow px-3 py-2 text-right text-subtle">
              Qty
            </th>
            <th scope="col" className="eyebrow px-3 py-2 text-subtle">
              Unit
            </th>
            <th scope="col" className="eyebrow px-3 py-2 text-subtle">
              Production rate
            </th>
            <th scope="col" className="eyebrow px-3 py-2 text-subtle">
              Flags
            </th>
            <th scope="col" className="eyebrow px-3 py-2 text-right text-subtle">
              Line cost
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {expected.map((line, index) => (
            <tr key={`expected-${index}`} className="bg-ok-soft/40">
              <th scope="row" className={`${cell} text-left font-medium text-ink`}>
                Expected
              </th>
              <td className={`${cell} num text-ink`}>
                {/^[\d.]+$/.test(line.quantity) ? formatQuantity(line.quantity) : line.quantity}
              </td>
              <td className={`${cell} text-ink`}>{line.unit}</td>
              <td className={`${cell} font-mono text-xs text-ink`}>{line.production_rate}</td>
              <td className={`${cell} text-body`}>required: {expectedFlags(line)}</td>
              <td className={`${cell} num text-ink`}>{formatMoney(line.gold_subtotal)}</td>
            </tr>
          ))}
          {returned.map(({ run, line }, index) => (
            <tr key={`run-${run}-${index}`}>
              <th scope="row" className={`${cell} text-left font-normal text-body`}>
                Run {run}
                <span className="block font-mono text-xs text-subtle">{line.source_ref}</span>
              </th>
              <td className={`${cell} num text-ink`}>{formatQuantity(line.quantity)}</td>
              <td className={`${cell} text-ink`}>{line.unit || "(blank)"}</td>
              <td className={`${cell} font-mono text-xs text-ink`}>
                {line.production_rate_code ?? "none"}
                {line.rate_basis === "assumed" && (
                  <span className="block font-sans text-subtle">assumed by the LLM</span>
                )}
              </td>
              <td className={`${cell} text-body`}>{returnedFlags(line)}</td>
              <td className={`${cell} num text-ink`}>{formatMoney(line.line_subtotal)}</td>
            </tr>
          ))}
          {returned.length === 0 && (
            <tr>
              <td colSpan={6} className={`${cell} text-body`}>
                No run returned a line with this item number.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function FailureCard({ evalCase, failure }: { evalCase: EvalCase; failure: EvalFailure }) {
  const isError = failure.severity === "error";
  const runs = Object.entries(failure.actual).sort(([a], [b]) => Number(a) - Number(b));
  return (
    <li
      id={failure.id}
      className="scroll-mt-20 px-5 py-4 target:bg-brand-soft target:outline-2 target:-outline-offset-2 target:outline-brand"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Pill tone={isError ? "blocker" : "info"}>
          {isError ? (
            <OctagonAlertIcon className="size-3" aria-hidden="true" />
          ) : (
            <InfoIcon className="size-3" aria-hidden="true" />
          )}
          {failureLabel(failure.kind)}
        </Pill>
        {failure.item_number && (
          <span className="text-sm font-medium text-ink">Item {failure.item_number}</span>
        )}
        <span className="text-sm text-subtle">
          in {failure.runs.length} of {evalCase.runs.length} runs
        </span>
        {failure.problem && (
          <span className="text-sm text-subtle">· planted: {failure.problem}</span>
        )}
        <span className="ml-auto font-mono text-xs text-subtle">{failure.id}</span>
      </div>
      <dl className="mt-3 grid gap-x-6 gap-y-3 text-sm md:grid-cols-2">
        <div>
          <dt className="eyebrow text-subtle">Expected</dt>
          <dd className="mt-1.5 text-ink">{failure.expected}</dd>
        </div>
        <div>
          <dt className="eyebrow text-subtle">Came back</dt>
          <dd className="mt-1.5 space-y-1 text-ink">
            {runs.map(([run, text]) => (
              <p key={run}>
                <span className="font-mono text-xs text-subtle">run {run}</span> {text}
              </p>
            ))}
          </dd>
        </div>
      </dl>
      {failure.item_number && (
        <LineComparison evalCase={evalCase} itemNumber={failure.item_number} />
      )}
    </li>
  );
}

/** Every failure of every case: what was expected, and what each run returned. */
export function FailureList({ cases }: { cases: EvalCase[] }) {
  const failing = cases.filter((evalCase) => evalCase.failures.length > 0);
  if (failing.length === 0) {
    return (
      <p className="rounded-lg border border-line bg-page px-5 py-4 text-sm text-body">
        No failures: every run matched its expected answers.
      </p>
    );
  }
  return (
    <div className="space-y-6">
      {failing.map((evalCase) => (
        <section
          key={evalCase.id}
          aria-label={`Failures of ${evalCase.title}`}
          className="overflow-hidden rounded-lg border border-line bg-page"
        >
          <div className="border-b border-line bg-surface px-5 py-3">
            <h3 className="text-lg font-medium">{evalCase.title}</h3>
            <p className="mt-0.5 font-mono text-xs text-subtle">
              {evalCase.id} · {evalCase.bid_file} · gold total {formatMoney(evalCase.gold_total)}
              {" · "}
              {evalCase.verified_by_hand ? "hand-verified" : "not hand-verified"}
            </p>
            {evalCase.planted_problems.length > 0 && (
              <p className="mt-2 text-sm text-body">
                Planted: {evalCase.planted_problems.join("; ")}.
              </p>
            )}
          </div>
          <ul className="divide-y divide-line">
            {evalCase.failures.map((failure) => (
              <FailureCard key={failure.id} evalCase={evalCase} failure={failure} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
