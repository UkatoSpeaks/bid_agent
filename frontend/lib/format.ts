// Display formatting only. The backend sends decimal strings that are
// already rounded; nothing here adds, multiplies or rounds money.

export function formatMoney(value: string | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || value === "") return "-";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

/** A quantity as written, with thousands separators: "1850.5" -> "1,850.5". */
export function formatQuantity(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(Number(value));
}

/** A percentage from the backend, kept at its one decimal: "60.7" -> "60.7%". */
export function formatPct(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${value}%`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const FLAG_LABELS: Record<string, string> = {
  ASSUMED_PRODUCTION_RATE: "Assumed rate",
  STANDARD_RATE_DECLINED: "Standard rate declined",
  HIGH_IMPACT_LINE: "High impact",
  VAGUE_SCOPE: "Vague scope",
  QUANTITY_NOT_NUMERIC: "Quantity missing",
  QUANTITY_NOT_IN_SOURCE: "Quantity not in source",
  UNKNOWN_SOURCE_REF: "Unknown source row",
  EXTRACTION_NOTE: "Extraction note",
  UNKNOWN_PRODUCTION_RATE: "Unknown production rate",
  UNIT_MISMATCH: "Unit mismatch",
  UNKNOWN_RATE_CODE: "Unknown rate code",
  INVALID_QUANTITY_PER_UNIT: "Invalid quantity per unit",
  LOW_CONFIDENCE_MAPPING: "Low confidence",
  NO_RATE_CARD_MATCH: "No rate card match",
  PROPOSED_COMPONENTS_IGNORED: "Proposal ignored",
  MAPPING_MISSING: "Not mapped",
  NO_COMPONENTS: "Not priced",
  NEGATIVE_QUANTITY: "Negative quantity",
  ZERO_QUANTITY: "Zero quantity",
};

/** "ASSUMED_PRODUCTION_RATE" -> "Assumed rate". Unknown codes are title-cased. */
export function flagLabel(code: string): string {
  const known = FLAG_LABELS[code];
  if (known) return known;
  const words = code.toLowerCase().split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
