export type EmailCodeConfig = {
  enabled: boolean;
  consent_version: string | null;
  google_enabled: boolean;
  expires_in_seconds: number;
  resend_after_seconds: number;
};

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid sign-in response");
  return value as Record<string, unknown>;
}

export function parseCodeTiming(value: unknown) {
  const item = object(value);
  const expiry = item.expires_in_seconds;
  const resend = item.resend_after_seconds;
  if (
    !Number.isInteger(expiry) ||
    Number(expiry) < 1 ||
    Number(expiry) > 3600 ||
    !Number.isInteger(resend) ||
    Number(resend) < 0 ||
    Number(resend) > Number(expiry)
  )
    throw new Error("Invalid sign-in timing");
  return {
    expires_in_seconds: Number(expiry),
    resend_after_seconds: Number(resend),
  };
}

export function parseEmailCodeConfig(value: unknown): EmailCodeConfig {
  const item = object(value);
  if (
    typeof item.enabled !== "boolean" ||
    typeof item.google_enabled !== "boolean" ||
    (item.consent_version !== null &&
      (typeof item.consent_version !== "string" ||
        !item.consent_version.trim() ||
        item.consent_version.length > 64)) ||
    (item.enabled && item.consent_version === null)
  )
    throw new Error("Invalid sign-in configuration");
  return {
    ...parseCodeTiming(item),
    enabled: item.enabled,
    consent_version: item.consent_version,
    google_enabled: item.google_enabled,
  };
}

export function parseAuthenticatedAccount(value: unknown) {
  const item = object(value);
  if (
    item.authenticated !== true ||
    typeof item.person_id !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      item.person_id,
    ) ||
    typeof item.account_created !== "boolean" ||
    typeof item.profile_complete !== "boolean"
  )
    throw new Error("Sign-in was not confirmed");
  return { personId: item.person_id, profileComplete: item.profile_complete };
}

export async function emailCodeRequest(
  path: "config" | "request" | "verify",
  signal: AbortSignal,
  body?: unknown,
) {
  const response = await fetch(
    `/v1/auth/email-code/${path}${path === "config" ? "?surface=sales_xray" : ""}`,
    {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: {
        accept: "application/json",
        ...(body === undefined ? {} : { "content-type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    },
  );
  // Do not echo server/provider bodies, email-existence details or raw errors.
  if (!response.ok)
    throw new Error(
      response.status === 429 ? "rate-limited" : "sign-in-unavailable",
    );
  return response.json() as Promise<unknown>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The popup message is only a signal. The account session is read again. */
export const AUTH_COMPLETE_MESSAGE = "sales-xray-auth-complete";

export function isAuthCompleteMessage(value: unknown, flow: string): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  return (
    item.type === AUTH_COMPLETE_MESSAGE &&
    UUID.test(flow) &&
    item.flow === flow &&
    Object.keys(item).length === 2
  );
}

export function validAuthFlow(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

export function parseCanonicalSession(value: unknown) {
  const item = object(value);
  if (
    typeof item.person_id !== "string" ||
    !UUID.test(item.person_id) ||
    typeof item.session_id !== "string" ||
    !UUID.test(item.session_id) ||
    !Array.isArray(item.workspaces) ||
    (item.selected_tenant_id !== null &&
      (typeof item.selected_tenant_id !== "string" ||
        !UUID.test(item.selected_tenant_id)))
  )
    throw new Error("Account session was not confirmed");
  return { personId: item.person_id, sessionId: item.session_id };
}

export async function readCanonicalSession(signal: AbortSignal) {
  const response = await fetch("/v1/me/workspaces", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new Error("Account session was not confirmed");
  return parseCanonicalSession(await response.json());
}

export async function passwordLogin(
  email: string,
  password: string,
  signal: AbortSignal,
) {
  const response = await fetch("/v1/auth/password/login", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error("Password sign-in was not confirmed");
  return readCanonicalSession(signal);
}

export function maskedEmail(email: string) {
  const at = email.lastIndexOf("@");
  return at > 0 ? `${email.slice(0, 1)}•••${email.slice(at)}` : "your email";
}
