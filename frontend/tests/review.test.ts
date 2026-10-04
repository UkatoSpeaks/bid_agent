import { describe, expect, it } from "vitest";

import { describeError } from "@/lib/api";
import { formatMoney, formatQuantity } from "@/lib/format";
import { canApprove, parseQuantityInput, patchEdit, reviewFirst } from "@/lib/review";

import { estimate, flag, line } from "./fixtures";

describe("canApprove (the approve gate)", () => {
  it("is false while any blocker is unresolved", () => {
    const draft = estimate([
      line("L001"),
      line("L002", { flags: [flag("blocker", "ASSUMED_PRODUCTION_RATE")] }),
    ]);
    expect(canApprove(draft)).toBe(false);
  });

  it("is true once every blocker is resolved; warnings do not block", () => {
    const reviewed = estimate([
      line("L001", { flags: [flag("warning", "HIGH_IMPACT_LINE")] }),
      line("L002", { flags: [flag("blocker", "ASSUMED_PRODUCTION_RATE", { resolved: true })] }),
    ]);
    expect(canApprove(reviewed)).toBe(true);
  });

  it("stays false if the summary says ready but a blocker flag is still open", () => {
    const inconsistent = estimate([line("L001", { flags: [flag("blocker", "NO_COMPONENTS")] })], {
      ready_to_approve: true,
      blocker_count: 0,
    });
    expect(canApprove(inconsistent)).toBe(false);
  });

  it("follows the backend when it says not ready, e.g. every line excluded", () => {
    expect(canApprove(estimate([line("L001")], { ready_to_approve: false }))).toBe(false);
  });

  it("is false with no estimate or no review summary", () => {
    expect(canApprove(null)).toBe(false);
    expect(canApprove({ ...estimate([line("L001")]), review: null })).toBe(false);
  });
});

describe("reviewFirst", () => {
  it("puts blockers before warnings, then the biggest line first", () => {
    const items = reviewFirst(
      estimate([
        line("small-warning", { line_subtotal: "50.00", flags: [flag("warning", "VAGUE_SCOPE")] }),
        line("big-warning", { line_subtotal: "9000.00", flags: [flag("warning", "VAGUE_SCOPE")] }),
        line("small-blocker", {
          line_subtotal: "10.00",
          flags: [flag("blocker", "UNIT_MISMATCH")],
        }),
        line("big-blocker", {
          line_subtotal: "700.00",
          flags: [flag("blocker", "UNIT_MISMATCH")],
        }),
      ]),
    );
    expect(items.map((item) => item.line.id)).toEqual([
      "big-blocker",
      "small-blocker",
      "big-warning",
      "small-warning",
    ]);
  });

  it("leaves out clean, info-only, resolved and excluded lines", () => {
    const items = reviewFirst(
      estimate([
        line("clean"),
        line("info", { flags: [flag("info", "EXTRACTION_NOTE")] }),
        line("resolved", { flags: [flag("warning", "VAGUE_SCOPE", { resolved: true })] }),
        line("excluded", {
          review_status: "excluded",
          flags: [flag("blocker", "NO_COMPONENTS")],
        }),
      ]),
    );
    expect(items).toEqual([]);
  });
});

describe("patchEdit", () => {
  it("merges changes for a line and drops an edit that changes nothing", () => {
    let edits = patchEdit({}, "L001", { quantity: "40" });
    edits = patchEdit(edits, "L001", { status: "reviewed" });
    expect(edits).toEqual({
      L001: { line_id: "L001", quantity: "40", status: "reviewed", exclusion_reason: null },
    });
    edits = patchEdit(edits, "L001", { quantity: null, status: "open" });
    expect(edits).toEqual({});
  });

  it("keeps the exclusion reason only while the line is excluded", () => {
    let edits = patchEdit({}, "L001", { status: "excluded", exclusion_reason: "By owner" });
    expect(edits.L001.exclusion_reason).toBe("By owner");
    edits = patchEdit(edits, "L001", { status: "reviewed" });
    expect(edits.L001.exclusion_reason).toBeNull();
  });
});

describe("input and formatting", () => {
  it("accepts plain and grouped numbers as a quantity, nothing else", () => {
    expect(parseQuantityInput(" 1,850.5 ")).toBe("1850.5");
    expect(parseQuantityInput("40")).toBe("40");
    expect(parseQuantityInput("-3")).toBeNull();
    expect(parseQuantityInput("TBD")).toBeNull();
    expect(parseQuantityInput("")).toBeNull();
  });

  it("formats money with the currency and two decimals", () => {
    expect(formatMoney("3449.84", "USD")).toBe("$3,449.84");
    expect(formatMoney("0", "USD")).toBe("$0.00");
    expect(formatQuantity("1850.5")).toBe("1,850.5");
  });
});

describe("describeError", () => {
  it("gives a human-readable message for each backend error", () => {
    expect(describeError(415, null, "Unsupported file type '.docx'.").message).toContain("PDF");
    expect(describeError(422, null, "The PDF has no text layer.").message).toBe(
      "The PDF has no text layer.",
    );
    expect(describeError(502, "llm_failed", "Groq rejected the request").title).toBe(
      "The language model failed",
    );
    expect(describeError(503, "llm_rate_limited", "429").message).toBe(
      "Rate limit reached on the free LLM tier, try again in a minute.",
    );
    expect(describeError(503, "llm_not_configured", "no key").message).toContain("GROQ_API_KEY");
  });
});
