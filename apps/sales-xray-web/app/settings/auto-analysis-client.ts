/**
 * Analyse my calls automatically: a seller's standing consent (owner, 26 Oct
 * 2026, approved for v0.96; server: call_ai/auto_consent.py). The words, their
 * hash and the state come only from the server: the app holds no consent words
 * of its own, and nothing is on until the person taps Turn on in the sheet.
 *
 * - can_start: the found recording may start by itself (upload it with
 *   `X-Upload-Consent: standing`).
 * - "ask": show <AutoAnalysisSheet> (never chosen, or the words or the
 *   upload terms changed since).
 * - anything else: today's one tap.
 * - "unavailable": a personal workspace; show nothing.
 */

export type AutoAnalysisState = "on" | "off" | "ask" | "unavailable";

export type AutoAnalysisNotice = {
  version: string;
  language: "en";
  title: string;
  /** The approved sentence, with the organisation's name in it. */
  text: string;
  policy_sha256: string;
};

export type AutoAnalysis = {
  schema: "sales-xray-auto-analysis/1";
  state: AutoAnalysisState;
  can_start: boolean;
  since?: string | null;
  terms_sha256?: string | null;
  ai_level?: "off" | "data_only" | "auto" | "full";
  notice?: AutoAnalysisNotice;
  pending_languages?: string[];
};

export const AUTO_ANALYSIS_PATH = "/v1/sales-xray/call-ai/auto-analysis";

function parse(body: unknown): AutoAnalysis {
  const value = body as Partial<AutoAnalysis> | null;
  if (
    !value ||
    value.schema !== "sales-xray-auto-analysis/1" ||
    typeof value.can_start !== "boolean" ||
    !["on", "off", "ask", "unavailable"].includes(String(value.state))
  )
    throw new Error("Automatic analysis could not be read.");
  return value as AutoAnalysis;
}

async function answer(response: Response): Promise<AutoAnalysis> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new Error(
      typeof body?.detail === "string" ? body.detail : "Not saved. Try again.",
    );
  }
  return parse(await response.json());
}

export async function readAutoAnalysis(
  signal?: AbortSignal,
): Promise<AutoAnalysis> {
  return answer(
    await fetch(AUTO_ANALYSIS_PATH, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
      signal,
    }),
  );
}

/**
 * Turn it on (with the words' hash as shown and the upload terms' hash in
 * force) or off. One key per tap: a double tap records one choice.
 */
export async function chooseAutoAnalysis(
  choice:
    | {
        decision: "granted";
        notice: AutoAnalysisNotice;
        uploadPolicySha256: string;
      }
    | { decision: "withdrawn" },
  key: string = crypto.randomUUID(),
): Promise<AutoAnalysis> {
  const body =
    choice.decision === "granted"
      ? {
          decision: "granted",
          policy_sha256: choice.notice.policy_sha256,
          upload_policy_sha256: choice.uploadPolicySha256,
          language: choice.notice.language,
        }
      : { decision: "withdrawn" };
  return answer(
    await fetch(AUTO_ANALYSIS_PATH, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify(body),
    }),
  );
}
