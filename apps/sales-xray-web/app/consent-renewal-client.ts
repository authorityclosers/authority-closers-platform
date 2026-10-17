export const CONSENT_PATH = "/v1/me/consent";
export const CONSENT_RENEW_PATH = "/v1/me/consent/renew";

export type ConsentStatus = "current" | "renewal_required" | "consent_required";

export type ConsentDocument = Readonly<{
  version: string;
  acknowledgement: string;
  terms_path: string;
  privacy_path: string;
}>;

export type ConsentRecord = Readonly<{
  status: ConsentStatus;
  current_version: string;
  document: ConsentDocument;
}>;

export class ConsentRequestError extends Error {
  constructor(
    readonly status: number,
    message = "consent_request_failed",
  ) {
    super(message);
    this.name = "ConsentRequestError";
  }
}

const STATUSES: readonly string[] = [
  "current",
  "renewal_required",
  "consent_required",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A page of this app only: one path, never a full address or "//host". */
function ownPath(value: unknown, fallback: string): string {
  return typeof value === "string" &&
    /^\/[A-Za-z0-9_-]+(\/[A-Za-z0-9_-]+)*$/.test(value)
    ? value
    : fallback;
}

/** Read the server's answer strictly; the words and version come from it. */
export function parseConsent(value: unknown): ConsentRecord {
  const document = isRecord(value) ? value.document : null;
  if (
    !isRecord(value) ||
    typeof value.status !== "string" ||
    !STATUSES.includes(value.status) ||
    typeof value.current_version !== "string" ||
    !isRecord(document) ||
    typeof document.version !== "string" ||
    !document.version ||
    typeof document.acknowledgement !== "string" ||
    !document.acknowledgement.trim()
  ) {
    throw new Error("invalid_consent_response");
  }
  return {
    status: value.status as ConsentStatus,
    current_version: value.current_version,
    document: {
      version: document.version,
      acknowledgement: document.acknowledgement,
      terms_path: ownPath(document.terms_path, "/terms"),
      privacy_path: ownPath(document.privacy_path, "/privacy"),
    },
  };
}

/** The signed-in account's consent state against the current document. */
export async function readConsent(
  signal?: AbortSignal,
): Promise<ConsentRecord> {
  const response = await fetch(CONSENT_PATH, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new ConsentRequestError(response.status);
  return parseConsent(await response.json());
}

/**
 * Accept the document the person was shown. The server checks the version and
 * answers a repeated acceptance with the original decision, so a retry after a
 * lost answer is safe.
 */
export async function renewConsent(
  expectedVersion: string,
  signal?: AbortSignal,
): Promise<ConsentRecord> {
  const response = await fetch(CONSENT_RENEW_PATH, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify({ accepted: true, expected_version: expectedVersion }),
    signal,
  });
  if (!response.ok) throw new ConsentRequestError(response.status);
  return parseConsent(await response.json());
}
