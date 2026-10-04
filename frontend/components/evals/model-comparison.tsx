import { comparisonRows, type EvalResult } from "@/lib/evals";

/** The overall metrics of each model's newest eval, one column per model. */
export function ModelComparison({ results }: { results: EvalResult[] }) {
  const columns = results.map((result) => comparisonRows(result.summary));
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-page">
      {results.length === 1 && (
        <p className="border-b border-line bg-surface px-5 py-3 text-sm text-body">
          Only one model has been evaluated so far. Run the eval with a second{" "}
          <span className="font-mono text-xs">--model</span> to compare.
        </p>
      )}
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-line bg-surface text-left">
              <th scope="col" className="eyebrow px-5 py-2.5 text-subtle">
                Metric
              </th>
              {results.map((result) => (
                <th
                  key={result.meta.model}
                  scope="col"
                  className="px-5 py-2.5 text-right font-mono text-xs font-medium text-ink"
                >
                  {result.meta.model}
                  {!result.meta.complete && (
                    <span className="block font-sans text-warning">stopped early</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {columns[0].map((row, index) => (
              <tr key={row.label}>
                <th scope="row" className="px-5 py-2.5 text-left font-normal text-body">
                  {row.label}
                </th>
                {columns.map((column, modelIndex) => (
                  <td key={results[modelIndex].meta.model} className="num px-5 py-2.5">
                    <span className="font-medium text-ink">{column[index].value}</span>
                    {column[index].note && (
                      <span className="block text-xs text-subtle">{column[index].note}</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <th scope="row" className="px-5 py-2.5 text-left font-normal text-body">
                Hand-verified cases
              </th>
              {results.map((result) => (
                <td key={result.meta.model} className="num px-5 py-2.5 font-medium text-ink">
                  {result.dataset.hand_verified} of {result.dataset.cases}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
