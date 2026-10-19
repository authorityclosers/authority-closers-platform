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

/**
 * Full-page sign-in, for browsers that block the sign-in window: the Claude
 * desktop pane, and Facebook's and Instagram's in-app browsers, where people
 * arrive from lead ads. The same click navigates this tab through
 * /v1/auth/<provider>/start; /auth/complete confirms the flow's receipt, keeps
 * a short "signed in" note for this tab and returns to the starting page,
 * where the sign-in screen finishes as it does after the window.
 */
export type SignInProvider = "google" | "apple" | "facebook";
const SIGN_IN_PROVIDERS = new Set<SignInProvider>([
  "google",
  "apple",
  "facebook",
]);

export function providerLabel(provider: SignInProvider) {
  return provider === "google"
    ? "Google"
    : provider === "apple"
      ? "Apple"
      : "Facebook";
}

const REDIRECT_KEY = "sx.signIn.redirect";
const RESULT_KEY = "sx.signIn.result";
/** As long as the server keeps the sign-in transaction. */
const REDIRECT_MAX_AGE_MS = 10 * 60 * 1000;
/** The receipt the completion page checked is good for three minutes. */
const RESULT_MAX_AGE_MS = 3 * 60 * 1000;

/** In-app browsers known to break sign-in windows. */
const POPUP_HOSTILE =
  /\bFBA[NV]\/|\bFB_IAB\b|\bFB4A\b|\bFBIOS\b|\bInstagram[ /]\d|\bLinkedInApp\b|\bBytedanceWebview\b|\bmusical_ly_|\bSnapchat\/|\bLine\/\d/i;

export function popupHostileBrowser(userAgent: string | null | undefined) {
  return POPUP_HOSTILE.test(userAgent ?? "");
}

/** A same-origin page to come back to; never the completion or API paths. */
export function safeReturnPath(candidate: unknown): string {
  if (
    typeof candidate !== "string" ||
    candidate.length > 512 ||
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\")
  )
    return "/";
  try {
    const url = new URL(candidate, "https://sales-xray.invalid");
    if (
      url.origin !== "https://sales-xray.invalid" ||
      url.pathname.startsWith("/auth/complete") ||
      url.pathname.startsWith("/v1/")
    )
      return "/";
    return `${url.pathname}${url.search}`;
  } catch {
    return "/";
  }
}

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function rememberRedirectSignIn(
  flow: string,
  provider: SignInProvider,
  returnTo: string,
) {
  if (!UUID.test(flow)) return false;
  try {
    sessionStore()?.setItem(
      REDIRECT_KEY,
      JSON.stringify({
        flow,
        provider,
        returnTo: safeReturnPath(returnTo),
        at: Date.now(),
      }),
    );
    return true;
  } catch {
    return false;
  }
}

/** The page a full-page sign-in started from, once, for this exact flow. */
export function takeRedirectSignIn(
  flow: string,
): { provider: SignInProvider; returnTo: string } | null {
  const store = sessionStore();
  try {
    const raw = store?.getItem(REDIRECT_KEY);
    store?.removeItem(REDIRECT_KEY);
    const kept = JSON.parse(raw ?? "null") as {
      flow?: unknown;
      provider?: unknown;
      returnTo?: unknown;
      at?: unknown;
    } | null;
    if (
      !kept ||
      kept.flow !== flow ||
      !UUID.test(flow) ||
      typeof kept.provider !== "string" ||
      !SIGN_IN_PROVIDERS.has(kept.provider as SignInProvider) ||
      typeof kept.at !== "number" ||
      Date.now() - kept.at > REDIRECT_MAX_AGE_MS
    )
      return null;
    return {
      provider: kept.provider as SignInProvider,
      returnTo: safeReturnPath(kept.returnTo),
    };
  } catch {
    return null;
  }
}

export function keepSignInResult(
  result: AuthCompletionResult,
  provider: SignInProvider,
) {
  try {
    sessionStore()?.setItem(
      RESULT_KEY,
      JSON.stringify({ result, provider, at: Date.now() }),
    );
  } catch {
    // Without storage the starting page simply shows the sign-in again.
  }
}

/** The outcome of a full-page sign-in this tab just came back from, once. */
export function takeSignInResult(): {
  result: AuthCompletionResult;
  provider: SignInProvider;
} | null {
  const store = sessionStore();
  try {
    const raw = store?.getItem(RESULT_KEY);
    if (raw === null || raw === undefined) return null;
    store?.removeItem(RESULT_KEY);
    const kept = JSON.parse(raw) as {
      result?: unknown;
      provider?: unknown;
      at?: unknown;
    } | null;
    if (
      !kept ||
      typeof kept.at !== "number" ||
      Date.now() - kept.at > RESULT_MAX_AGE_MS ||
      typeof kept.result !== "string" ||
      !AUTH_COMPLETION_RESULTS.has(kept.result as AuthCompletionResult) ||
      typeof kept.provider !== "string" ||
      !SIGN_IN_PROVIDERS.has(kept.provider as SignInProvider)
    )
      return null;
    return {
      result: kept.result as AuthCompletionResult,
      provider: kept.provider as SignInProvider,
    };
  } catch {
    return null;
  }
}
