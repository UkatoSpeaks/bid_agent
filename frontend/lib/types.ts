// Mirrors the backend's Pydantic models (backend/app/schemas, app/main.py).
// Money, quantities and percentages arrive as decimal strings and stay
// strings: the frontend formats them and never does arithmetic on them.

export type Severity = "info" | "warning" | "blocker";
export type ComponentType = "labor" | "material" | "equipment";
export type Confidence = "high" | "medium" | "low";
export type RateBasis = "standard" | "assumed" | "none";
export type ReviewStatus = "open" | "reviewed" | "excluded";

export interface Flag {
  severity: Severity;
  code: string;
  message: string;
  suggested_production_rate_code: string | null;
  resolved: boolean;
}

export interface LineFlag extends Flag {
  line_id: string;
}

export interface LineItemComponent {
  type: ComponentType;
  rate_card_code: string;
  quantity_per_unit: string;
}

/** A line as extracted and mapped, before pricing. Sent back on a reprice. */
export interface BidLineItem {
  id: string;
  item_number: string;
  description: string;
  quantity: string;
  unit: string;
  components: LineItemComponent[];
  flags: Flag[];
  source_ref: string | null;
  production_rate_code: string | null;
  assumptions: string[];
  mapping_confidence: Confidence | null;
  mapping_rationale: string | null;
}

export interface PricedLine {
  id: string;
  item_number: string;
  description: string;
  quantity: string;
  unit: string;
  labor_cost: string;
  material_cost: string;
  equipment_cost: string;
  line_subtotal: string;
  calculation_trace: string[];
  flags: Flag[];
  source_ref: string | null;
  assumptions: string[];
  rate_basis: RateBasis;
  production_rate_code: string | null;
  subtotal_share_pct: string | null;
  mapping_confidence: Confidence | null;
  mapping_rationale: string | null;
  review_status: ReviewStatus;
  exclusion_reason: string | null;
  reviewer_edits: string[];
}

export interface EstimateTotals {
  direct_labor: string;
  direct_material: string;
  material_markup: string;
  sales_tax: string;
  direct_equipment: string;
  subtotal: string;
  overhead: string;
  profit: string;
  grand_total: string;
}

export interface ReviewSummary {
  blocker_count: number;
  warning_count: number;
  info_count: number;
  ready_to_approve: boolean;
  standard_rate_pct: string;
  assumed_rate_pct: string;
  lines_on_standard_rates: number;
  lines_on_assumed_rates: number;
  lines_not_priced: number;
  lines_excluded: number;
  high_impact_threshold_pct: string;
  high_impact_line_ids: string[];
}

export interface SkippedRow {
  source_ref: string;
  description: string;
  reason: string;
}

export interface Estimate {
  currency: string;
  lines: PricedLine[];
  totals: EstimateTotals;
  all_flags: LineFlag[];
  review: ReviewSummary | null;
  skipped_rows: SkippedRow[];
  source_lines: BidLineItem[];
}

export interface ProductionRate {
  code: string;
  description: string;
  unit: string;
  components: LineItemComponent[];
  notes: string | null;
}

export interface RateCard {
  company_name: string;
  trade: string;
  currency: string;
  labor_rates: { code: string; role: string; hourly_rate: string }[];
  materials: { code: string; name: string; unit: string; unit_cost: string }[];
  equipment: { code: string; name: string; unit: string; rate: string }[];
  markups: {
    material_markup_pct: string;
    overhead_pct: string;
    profit_pct: string;
    sales_tax_pct_on_materials: string;
  };
  production_rates: ProductionRate[];
  production_rates_note: string | null;
}

export interface SampleBid {
  id: string;
  filename: string;
  title: string;
  description: string;
}

/** Everything the reviewer has changed on one line. */
export interface LineEdit {
  line_id: string;
  quantity?: string | null;
  production_rate_code?: string | null;
  status: ReviewStatus;
  exclusion_reason?: string | null;
}

export interface AuditEntry {
  id: string;
  timestamp: string; // ISO 8601
  who: string;
  action: string;
  line_id?: string | null;
  item_number?: string | null;
  before?: string | null;
  after?: string | null;
  note?: string | null;
}

export interface RepriceRequest {
  lines: BidLineItem[];
  edits: LineEdit[];
  skipped_rows: SkippedRow[];
}

export interface ExportRequest extends RepriceRequest {
  audit_log: Omit<AuditEntry, "id">[];
  source_filename: string | null;
}
