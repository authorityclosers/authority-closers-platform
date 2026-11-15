/**
 * The coaching loop's reads and writes for the app (13 Nov 2026 meeting,
 * section 5; docs/product/ask-dipak.md): my missions with their counts, the
 * active three, my latest calls from leads and my yes or no for each.
 */

const BASE = "/v1/sales-xray/ask-dipak";

export type Mission = Readonly<{
  question_id: string;
  title: string;
  mission: string | null;
  active: boolean;
  ticked: boolean;
  done_calls: number;
  not_done_calls: number;
}>;

export type Growth = Readonly<{
  max_active: number;
  active: readonly string[];
  missions: readonly Mission[];
}>;

export type RecentCall = Readonly<{
  call_id: string;
  lead_name: string;
  called_at: string;
  answered: readonly string[];
  waiting: readonly string[];
}>;

export type Calls = Readonly<{
  active: readonly Readonly<{ question_id: string; title: string }>[];
  calls: readonly RecentCall[];
}>;

export class CoachingError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const body = (await response.json().catch(() => null)) as
    | (T & { detail?: unknown })
    | null;
  if (!response.ok || body === null) {
    const detail =
      body && typeof body.detail === "string"
        ? body.detail
        : "Couldn’t reach Sales X-Ray just now.";
    throw new CoachingError(response.status, detail);
  }
  return body;
}

export const readGrowth = () => call<Growth>("/growth");

export const setActive = (questionId: string, active: boolean) =>
  call<Growth>(`/focus/${encodeURIComponent(questionId)}`, {
    method: "PUT",
    body: JSON.stringify({ active }),
  });

export const readCalls = () => call<Calls>("/calls");

export const answerCall = (callId: string, questionId: string, done: boolean) =>
  call<unknown>(`/calls/${encodeURIComponent(callId)}/check`, {
    method: "PUT",
    body: JSON.stringify({ answers: [{ question_id: questionId, done }] }),
  });
