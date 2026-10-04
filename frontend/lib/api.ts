import type { LatestEvals } from "@/lib/evals";
import type {
  Estimate,
  ExportRequest,
  RateCard,
  RepriceRequest,
  SampleBid,
} from "@/lib/types";

/** Where the FastAPI backend lives. Set NEXT_PUBLIC_API_URL in .env.local. */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010"
).replace(/\/+$/, "");

/** A failed request, with a title and message fit to show to an estimator. */
export class ApiError extends Error {
  constructor(
    public readonly title: string,
    message: string,
    public readonly status: number | null = null,
    public readonly detail: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Human-readable text for a backend error.
 *
 * `code` is the backend's X-Error-Code header (llm_rate_limited,
 * llm_not_configured, llm_failed), which tells the two kinds of 503 apart.
 */
export function describeError(
  status: number,
  code: string | null,
  detail: string | null,
): { title: string; message: string } {
  if (status === 415) {
    return {
      title: "File type not supported",
      message: "Upload the bid schedule as a PDF, an Excel workbook (.xlsx) or a CSV file.",
    };
  }
  if (status === 404) {
    return { title: "Not found", message: detail ?? "The backend does not know this item." };
  }
  if (status === 422) {
    return {
      title: "Could not use this input",
      message:
        detail ??
        "The backend could not read this. If it is a scanned PDF, it has no text to extract.",
    };
  }
  if (status === 502) {
    return {
      title: "The language model failed",
      message:
        "The model returned an answer the agent could not use, so no estimate was drafted. Try again.",
    };
  }
  if (status === 503 && code === "llm_not_configured") {
    return {
      title: "No LLM key configured",
      message: "The backend has no GROQ_API_KEY. Add one to .env and restart the backend.",
    };
  }
  if (status === 503) {
    return {
      title: "Rate limit reached",
      message: "Rate limit reached on the free LLM tier, try again in a minute.",
    };
  }
  return {
    title: "Something went wrong",
    message: detail ?? `The backend answered with status ${status}.`,
  };
}

/** FastAPI sends `detail` as a string, or as a list for its own validation errors. */
function readDetail(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
      .filter(Boolean)
      .join(" ");
  }
  return null;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      "Cannot reach the backend",
      `No answer from ${API_BASE_URL}. Check that the backend is running.`,
    );
  }
  if (!response.ok) {
    const detail = readDetail(await response.json().catch(() => null));
    const { title, message } = describeError(
      response.status,
      response.headers.get("X-Error-Code"),
      detail,
    );
    throw new ApiError(title, message, response.status, detail);
  }
  return response;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export async function getRateCard(): Promise<RateCard> {
  return (await request("/rate-card")).json();
}

export async function getSamples(): Promise<SampleBid[]> {
  return (await request("/samples")).json();
}

/** The newest eval result of each model. Rejects with status 404 if none exists. */
export async function getLatestEvals(): Promise<LatestEvals> {
  return (await request("/evals/latest")).json();
}

export async function draftFromFile(file: File): Promise<Estimate> {
  const form = new FormData();
  form.append("file", file);
  return (await request("/estimates/draft", { method: "POST", body: form })).json();
}

export async function draftFromSample(sampleId: string): Promise<Estimate> {
  return (
    await request(`/estimates/draft/sample/${encodeURIComponent(sampleId)}`, { method: "POST" })
  ).json();
}

export async function reprice(body: RepriceRequest): Promise<Estimate> {
  return (await request("/estimates/reprice", json(body))).json();
}

export async function exportEstimate(
  body: ExportRequest,
): Promise<{ blob: Blob; filename: string }> {
  const response = await request("/estimates/export", json(body));
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "estimate.xlsx";
  return { blob: await response.blob(), filename };
}
