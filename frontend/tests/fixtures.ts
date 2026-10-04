import type { Estimate, Flag, PricedLine, Severity } from "@/lib/types";

export function flag(severity: Severity, code: string, extra: Partial<Flag> = {}): Flag {
  return {
    severity,
    code,
    message: `${code} message`,
    suggested_production_rate_code: null,
    resolved: false,
    ...extra,
  };
}

export function line(id: string, extra: Partial<PricedLine> = {}): PricedLine {
  return {
    id,
    item_number: id,
    description: `Line ${id}`,
    quantity: "1",
    unit: "EA",
    labor_cost: "0.00",
    material_cost: "100.00",
    equipment_cost: "0.00",
    line_subtotal: "100.00",
    calculation_trace: [],
    flags: [],
    source_ref: null,
    assumptions: [],
    rate_basis: "standard",
    production_rate_code: "PR-X",
    subtotal_share_pct: "50.0",
    mapping_confidence: "high",
    mapping_rationale: "Direct match.",
    review_status: "open",
    exclusion_reason: null,
    reviewer_edits: [],
    ...extra,
  };
}

/** An estimate whose summary counts are derived from its lines' open flags. */
export function estimate(
  lines: PricedLine[],
  review: Partial<NonNullable<Estimate["review"]>> = {},
): Estimate {
  const all_flags = lines.flatMap((l) => l.flags.map((f) => ({ ...f, line_id: l.id })));
  const open = (severity: Severity) =>
    all_flags.filter((f) => f.severity === severity && !f.resolved).length;
  return {
    currency: "USD",
    lines,
    totals: {
      direct_labor: "690.00",
      direct_material: "1795.00",
      material_markup: "269.25",
      sales_tax: "149.66",
      direct_equipment: "0.00",
      subtotal: "2903.91",
      overhead: "290.39",
      profit: "255.54",
      grand_total: "3449.84",
    },
    all_flags,
    review: {
      blocker_count: open("blocker"),
      warning_count: open("warning"),
      info_count: open("info"),
      ready_to_approve: open("blocker") === 0 && lines.length > 0,
      standard_rate_pct: "60.7",
      assumed_rate_pct: "39.3",
      lines_on_standard_rates: 1,
      lines_on_assumed_rates: 1,
      lines_not_priced: 0,
      lines_excluded: 0,
      high_impact_threshold_pct: "15",
      high_impact_line_ids: [],
      ...review,
    },
    skipped_rows: [],
    source_lines: [],
  };
}
