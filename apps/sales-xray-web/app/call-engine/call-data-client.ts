/**
 * Call data engine API (/v1/sales-xray/call-data): a lead's facts from its
 * calls, the questions waiting for the seller, and their answers. Owner
 * direction 19 Oct: every call becomes typed data; the lead fills itself and
 * asks only what it is unsure of.
 */

export const API = "/v1/sales-xray/call-data";

export type Evidence = {
  segment_id: string;
  quote: string;
  start_ms: number;
  end_ms: number;
  speaker: string;
  role: "salesperson" | "prospect" | "other" | "unknown";
};

export type Fact = {
  object_id: string;
  type: string;
  category: string;
  label: string;
  kind: string;
  value: Record<string, unknown>;
  display: string;
  confidence: number;
  basis: "observed" | "inferred" | "confirmed" | "edited" | "person";
  status: "auto_filled" | "asked" | "accepted" | "edited" | "rejected" | "kept";
  ai_read: boolean;
  evidence: Evidence[];
  call: { recording_id: string; submission_id: string | null; at: string };
  source: { pipeline: string; version: string; taxonomy_version: string };
};

export type Question = Fact & {
  question: "fill" | "replace" | "confirm" | null;
  lead_field: string | null;
  lead_value: string | null;
};

export type PipelineState = {
  state: "none" | "running" | "done" | "failed" | "skipped" | "not_started";
  at: string | null;
};

export type LeadFacts = {
  schema: "call-data-lead/1";
  lead_id: string;
  taxonomy_version: string;
  pipelines: { fast: PipelineState; deep: PipelineState };
  questions: Question[];
  facts: Fact[];
  filled: { field: string; value: string; object_id: string; at: string }[];
  categories: Record<string, string>;
};

export class CallDataError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "CallDataError";
  }
}

const FALLBACK: Record<number, string> = {
  401: "Sign in to see this.",
  403: "Open your organisation workspace first.",
  404: "This is not here any more.",
  409: "This changed. Refresh and try again.",
  422: "Check the value and try again.",
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: { accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new CallDataError("Sales Xray isn't answering. Try again.", 0);
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new CallDataError(
      detail ?? FALLBACK[response.status] ?? "Something went wrong. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export function readLeadFacts(leadId: string, signal?: AbortSignal) {
  return request<LeadFacts>(`/leads/${encodeURIComponent(leadId)}`, { signal });
}

export function answer(
  objectId: string,
  decision: "accepted" | "edited" | "rejected",
  value?: Record<string, unknown>,
) {
  return request<LeadFacts>(
    `/objects/${encodeURIComponent(objectId)}/decision`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        decision,
        ...(value ? { value } : {}),
      }),
    },
  );
}
