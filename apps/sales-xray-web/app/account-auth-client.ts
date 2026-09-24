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
    ((item.enabled || item.google_enabled) && item.consent_version === null)
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

export type AuthCompletionResult =
  | "success"
  | "failed"
  | "review_terms"
  | "unavailable";

const AUTH_COMPLETION_RESULTS = new Set<AuthCompletionResult>([
  "success",
  "failed",
  "review_terms",
  "unavailable",
]);

export function parseAuthCompletionQuery(
  query: Record<string, string | string[] | undefined>,
): { flow: string; result: AuthCompletionResult } | null {
  if (Reflect.ownKeys(query).length !== 2) return null;
  const { flow, auth_result } = query;
  if (
    typeof flow !== "string" ||
    !UUID.test(flow) ||
    typeof auth_result !== "string" ||
    !AUTH_COMPLETION_RESULTS.has(auth_result as AuthCompletionResult)
  )
    return null;
  return { flow, result: auth_result as AuthCompletionResult };
}

export function isAuthCompleteMessage(
  value: unknown,
  flow: string,
): value is {
  type: typeof AUTH_COMPLETE_MESSAGE;
  flow: string;
  auth_result: AuthCompletionResult;
} {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  return (
    item.type === AUTH_COMPLETE_MESSAGE &&
    UUID.test(flow) &&
    item.flow === flow &&
    typeof item.auth_result === "string" &&
    AUTH_COMPLETION_RESULTS.has(item.auth_result as AuthCompletionResult) &&
    Reflect.ownKeys(item).length === 3 &&
    Object.hasOwn(item, "type") &&
    Object.hasOwn(item, "flow") &&
    Object.hasOwn(item, "auth_result")
  );
}

export function parseAuthCompletionUrl(
  url: string,
  origin: string,
  flow: string,
): AuthCompletionResult | null {
  try {
    const parsed = new URL(url, origin);
    if (
      parsed.origin !== origin ||
      parsed.pathname !== "/auth/complete" ||
      parsed.hash
    )
      return null;
    const keys = [...parsed.searchParams.keys()];
    if (
      keys.length !== 2 ||
      keys.some((key) => key !== "flow" && key !== "auth_result")
    )
      return null;
    const flows = parsed.searchParams.getAll("flow");
    const results = parsed.searchParams.getAll("auth_result");
    if (
      flows.length !== 1 ||
      results.length !== 1 ||
      flows[0] !== flow ||
      !UUID.test(flow)
    )
      return null;
    return AUTH_COMPLETION_RESULTS.has(results[0] as AuthCompletionResult)
      ? (results[0] as AuthCompletionResult)
      : null;
  } catch {
    return null;
  }
}

export async function readGoogleCompletion(flow: string, signal: AbortSignal) {
  if (!UUID.test(flow)) throw new Error("Google sign-in was not confirmed");
  const response = await fetch("/v1/auth/google/completion", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ flow_id: flow }),
  });
  if (!response.ok) throw new Error("Google sign-in was not confirmed");
  const value = await response.json();
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Google sign-in was not confirmed");
  const item = value as Record<string, unknown>;
  if (
    item.matched !== true ||
    Reflect.ownKeys(item).length !== 1 ||
    !Object.hasOwn(item, "matched")
  )
    throw new Error("Google sign-in was not confirmed");
  return true as const;
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
