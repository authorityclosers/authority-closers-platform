/**
 * Calls from the company number (owner, 27 Oct 2026: "Bridge via Exotel …
 * consented leads only, recording notice on"; server: lead_desk/telephony).
 *
 * The seller taps Call. Sales X-Ray rings the seller's own mobile first, then
 * the lead, who sees the business's number and hears that the call is
 * recorded. The call lands on the lead by itself, and its recording goes
 * through the usual upload, with the seller's consent and AI setting.
 *
 * Starting a call never goes through the write queue (sync/write-queue.ts): a
 * call placed minutes late, when the phone is back online, would ring a lead
 * nobody is waiting for. No answer here carries a price.
 */

export const CALLING_PATH = "/v1/lead-desk/calling";

export type CallingSource = { key: string; label: string; on: boolean };
export type CallingNotice = { version: string; text: string };

export type Calling = {
  available: boolean;
  on: boolean;
  number: string | null;
  /** The provider's name, for owners and admins only. */
  provider: string | null;
  notice: CallingNotice | null;
  notices: CallingNotice[];
  windowDays: number;
  sources: CallingSource[];
  myMobile: string | null;
  canManage: boolean;
  /** This person can place company calls now. */
  ready: boolean;
  /** What stands in the way, each in words with its fix. */
  blockers: string[];
  /** The calling limit is reached: why, without amounts. */
  paused: string | null;
  /** A test site: company calls ring only the team's test phones. */
  testOnly: boolean;
};

export type LeadCallCheck = {
  available: boolean;
  reason: string | null;
  words: string | null;
};

export type CompanyCallStatus =
  | "requested"
  | "queued"
  | "ringing"
  | "in_progress"
  | "completed"
  | "busy"
  | "no_answer"
  | "failed"
  | "canceled"
  | "not_placed";

export type CompanyCall = {
  id: string;
  leadId: string;
  status: CompanyCallStatus;
  final: boolean;
  words: string | null;
  talkSeconds: number | null;
  connected: boolean | null;
  /** The call on the lead's history, once it ended. */
  eventId: string | null;
  recording: boolean;
  requestedAt: string;
};

export class CompanyCallError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Why the company number can't call this lead (the server's reason). */
    readonly reason: string | null = null,
  ) {
    super(message);
    this.name = "CompanyCallError";
  }
}

async function answer<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new CompanyCallError(
      typeof body?.detail === "string"
        ? body.detail
        : response.status === 0
          ? "Sales X-Ray isn't answering. Try again."
          : "The call didn't start. Try again.",
      response.status,
      response.headers.get("x-company-call-refused"),
    );
  }
  return (await response.json()) as T;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: { accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new CompanyCallError("Sales X-Ray isn't answering. Try again.", 0);
  }
  return answer<T>(response);
}

const put = (body: unknown): RequestInit => ({
  method: "PUT",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export function readCalling(signal?: AbortSignal) {
  return call<Calling>(CALLING_PATH, { signal });
}

export function saveCalling(settings: {
  on: boolean;
  number: string | null;
  noticeVersion: string;
  windowDays: number;
  sources: string[];
}) {
  return call<Calling>(CALLING_PATH, put(settings));
}

export function saveMyMobile(mobile: string | null) {
  return call<Calling>(`${CALLING_PATH}/me`, put({ mobile }));
}

export function checkLead(leadId: string, signal?: AbortSignal) {
  return call<LeadCallCheck>(
    `${CALLING_PATH}/leads/${encodeURIComponent(leadId)}`,
    { signal },
  );
}

export function startCompanyCall(leadId: string, commandId: string) {
  return call<CompanyCall>(
    `/v1/lead-desk/leads/${encodeURIComponent(leadId)}/calls/company`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ commandId }),
    },
  );
}

export function readCompanyCall(callId: string, signal?: AbortSignal) {
  return call<CompanyCall>(
    `/v1/lead-desk/calls/company/${encodeURIComponent(callId)}`,
    { signal },
  );
}

/** The ended call's recording as a file, for the usual upload. */
export async function readCompanyRecording(
  value: Pick<CompanyCall, "id" | "requestedAt">,
): Promise<File> {
  let response: Response;
  try {
    response = await fetch(
      `/v1/lead-desk/calls/company/${encodeURIComponent(value.id)}/recording`,
      { credentials: "same-origin", cache: "no-store", redirect: "error" },
    );
  } catch {
    throw new CompanyCallError("The recording didn't download. Try again.", 0);
  }
  if (!response.ok) await answer<never>(response);
  const blob = await response.blob();
  const day = value.requestedAt.slice(0, 16).replace(/[-:T]/g, "");
  return new File([blob], `company-call-${day}.mp3`, {
    type: blob.type || "audio/mpeg",
  });
}

/** What the seller sees while the call goes on, in plain words. */
export function callLine(value: CompanyCall, name: string): string {
  switch (value.status) {
    case "requested":
    case "queued":
      return `Ringing your phone. Pick up, and we'll call ${name}.`;
    case "ringing":
      return `Pick up your phone to reach ${name}.`;
    case "in_progress":
      return `On the call. ${name} sees your company number.`;
    case "completed":
      return value.connected
        ? "Call ended."
        : (value.words ?? "They didn't answer.");
    default:
      return value.words ?? "The call didn't go through.";
  }
}

export const LIVE_STATUSES: ReadonlySet<CompanyCallStatus> = new Set([
  "requested",
  "queued",
  "ringing",
  "in_progress",
]);
