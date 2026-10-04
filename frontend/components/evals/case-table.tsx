import { CircleCheckIcon, InfoIcon, OctagonAlertIcon } from "lucide-react";

import { Pill } from "@/components/review/flag-badge";
import {
  errorsOf,
  failureLabel,
  formatNumber,
  formatRatio,
  isStable,
  type EvalCase,
} from "@/lib/evals";

const HEAD = "eyebrow px-4 py-2.5 text-subtle";

/** One row per bid. Each failure is a link to its expected-vs-returned detail. */
export function CaseTable({ cases }: { cases: EvalCase[] }) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-line bg-page">
      <table className="w-full min-w-[60rem] text-sm">
        <thead>
          <tr className="border-b border-line bg-surface text-left">
            <th scope="col" className={HEAD}>
              Case
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Line recall
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Rate mapping
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Flag recall
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Extra flags
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Total error
            </th>
            <th scope="col" className={HEAD}>
              Stable
            </th>
            <th scope="col" className={HEAD}>
              Failures
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {cases.map((evalCase) => {
            const errors = errorsOf(evalCase);
            const notes = evalCase.failures.length - errors.length;
            const stable = isStable(evalCase);
            return (
              <tr key={evalCase.id} className="align-top">
                <td className="px-4 py-3">
                  <p className="font-medium text-ink">{evalCase.title}</p>
                  <p className="mt-0.5 font-mono text-xs text-subtle">
                    {evalCase.bid_file} · {evalCase.runs.length} of {evalCase.runs_requested} runs
                  </p>
                  <p className="mt-1.5">
                    {evalCase.verified_by_hand ? (
                      <Pill tone="ok">
                        <CircleCheckIcon className="size-3" aria-hidden="true" />
                        Hand-verified
                      </Pill>
                    ) : (
                      <Pill tone="neutral">Not hand-verified</Pill>
                    )}
                  </p>
                </td>
                <td className="num px-4 py-3 text-ink">
                  {formatRatio(evalCase.metrics.line_recall)}
                </td>
                <td className="num px-4 py-3 text-ink">
                  {formatRatio(evalCase.metrics.code_accuracy)}
                </td>
                <td className="num px-4 py-3 text-ink">
                  {formatRatio(evalCase.metrics.flag_recall)}
                </td>
                <td className="num px-4 py-3 text-ink">
                  {formatNumber(evalCase.metrics.extra_flags_per_bid, 2)}
                  <span className="block text-xs text-subtle">per bid</span>
                </td>
                <td className="num px-4 py-3 text-ink">
                  {formatNumber(evalCase.money.mean_abs_error_pct, 2, "%")}
                  <span className="block text-xs text-subtle">
                    exact {evalCase.money.exact_runs}/{evalCase.money.runs}
                  </span>
                </td>
                <td className="px-4 py-3 text-ink">
                  {stable === null ? "-" : stable ? "Yes" : "No"}
                </td>
                <td className="px-4 py-3">
                  {evalCase.failures.length === 0 ? (
                    <Pill tone="ok">
                      <CircleCheckIcon className="size-3" aria-hidden="true" />
                      None
                    </Pill>
                  ) : (
                    <>
                      <p className="text-xs text-subtle">
                        {errors.length} {errors.length === 1 ? "failure" : "failures"}
                        {notes > 0 && `, ${notes} ${notes === 1 ? "note" : "notes"}`}
                      </p>
                      <ul className="mt-1.5 flex max-w-xs flex-wrap gap-1.5">
                        {evalCase.failures.map((failure) => (
                          <li key={failure.id}>
                            <a
                              href={`#${failure.id}`}
                              className="rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                            >
                              <Pill
                                tone={failure.severity === "error" ? "blocker" : "info"}
                                className="hover:underline"
                              >
                                {failure.severity === "error" ? (
                                  <OctagonAlertIcon className="size-3" aria-hidden="true" />
                                ) : (
                                  <InfoIcon className="size-3" aria-hidden="true" />
                                )}
                                {failureLabel(failure.kind)}
                                {failure.item_number && ` · ${failure.item_number}`}
                              </Pill>
                            </a>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
