import { randomBytes } from "node:crypto";

const DEFAULT_LOCAL_API_ORIGIN = "http://127.0.0.1:8000";
const STAGING_API_ORIGIN = "https://api-staging.authorityclosers.com";
const STAGING_PUBLIC_APP_ORIGIN = "https://staging.authorityclosers.com";
const PROXY_TIMEOUT_MS = 12_000;
const MAX_CATALOG_SLUG_LENGTH = 120;
const MAX_BRIDGE_QUERY_VALUE_LENGTH = 200;
const BRIDGE_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;
const BRIDGE_SESSION_MAX_COUNT = 8;
const BRIDGE_SESSION_COOKIE_NAME = "__Host-ac_dev_qa_session";
const STAGING_SESSION_COOKIE_NAME = "__Host-ac_session";
const SESSION_COOKIE_VALUE_PATTERN = /^[A-Za-z0-9_-]{43,512}$/;

// A public catalog preview has no reason to forward browser state or
// arbitrary headers to staging. Origin is intentionally retained so the
// staging API can enforce its own origin policy; all credential and proxy
// metadata is dropped at this boundary.
const STAGING_PREVIEW_REQUEST_HEADERS = new Set([
  "accept",
  "accept-language",
  "origin",
]);

// Authenticated staging requests use the normal same-origin learner API
// contract. The local gateway supplies the staging surface Origin and the
// server-side staging session; browser credentials and proxy metadata never
// cross this boundary.
const STAGING_AUTH_REQUEST_HEADERS = new Set([
  "accept",
  "accept-language",
  "content-type",
  "if-match",
  "idempotency-key",
  "user-agent",
  "x-request-id",
]);

type DevApiEnvironment = Readonly<Record<string, string | undefined>>;

export type DevApiTarget =
  | { mode: "local"; origin: string }
  | { mode: "staging-public-catalog"; origin: typeof STAGING_API_ORIGIN }
  | {
      mode: "staging-authenticated";
      origin: typeof STAGING_PUBLIC_APP_ORIGIN;
      browserOrigin: string;
    };

export type DevApiFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface DevelopmentBridgeSessionStore {
  get(localSession: string): string | null;
  set(localSession: string, stagingSession: string): void;
  delete(localSession: string): void;
}

type StoredBridgeSession = {
  stagingSession: string;
  expiresAt: number;
};

/**
 * Ephemeral server-side bridge state. It intentionally has no persistence
 * path: restarting the local dev server drops every local-to-staging mapping.
 */
export class InMemoryDevelopmentBridgeSessionStore
  implements DevelopmentBridgeSessionStore
{
  private readonly sessions = new Map<string, StoredBridgeSession>();

  constructor(private readonly now: () => number = Date.now) {}

  get(localSession: string): string | null {
    const stored = this.sessions.get(localSession);
    if (!stored) return null;
    if (stored.expiresAt <= this.now()) {
      this.sessions.delete(localSession);
      return null;
    }
    return stored.stagingSession;
  }

  set(localSession: string, stagingSession: string): void {
    this.sessions.delete(localSession);
    while (this.sessions.size >= BRIDGE_SESSION_MAX_COUNT) {
      const oldest = this.sessions.keys().next().value;
      if (typeof oldest !== "string") break;
      this.sessions.delete(oldest);
    }
    this.sessions.set(localSession, {
      stagingSession,
      expiresAt: this.now() + BRIDGE_SESSION_MAX_AGE_SECONDS * 1000,
    });
  }

  delete(localSession: string): void {
    this.sessions.delete(localSession);
  }
}

const DEV_BRIDGE_STORE_KEY = Symbol.for(
  "authority-closers.learner-web.development-bridge-store",
);

function isDevelopmentBridgeSessionStore(
  value: unknown,
): value is DevelopmentBridgeSessionStore {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DevelopmentBridgeSessionStore>;
  return (
    typeof candidate.get === "function" &&
    typeof candidate.set === "function" &&
    typeof candidate.delete === "function"
  );
}

function defaultDevelopmentBridgeSessionStore(): DevelopmentBridgeSessionStore {
  const runtimeGlobal = globalThis as unknown as Record<symbol, unknown>;
  const existing = runtimeGlobal[DEV_BRIDGE_STORE_KEY];
  if (isDevelopmentBridgeSessionStore(existing)) return existing;
  const store = new InMemoryDevelopmentBridgeSessionStore();
  runtimeGlobal[DEV_BRIDGE_STORE_KEY] = store;
  return store;
}

function isLoopbackHost(hostname: string): boolean {
  return (
    hostname === "127.0.0.1" ||
    hostname === "localhost" ||
    hostname === "[::1]" ||
    hostname === "::1"
  );
}

function normalizedOrigin(value: string): URL {
  const url = new URL(value);
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.pathname !== "/" && url.pathname !== "")
  ) {
    throw new Error(
      "Development API origin must contain only a scheme, host, and optional port.",
    );
  }
  return url;
}

function optionalConfiguredApiOrigin(
  environment: DevApiEnvironment,
): string | undefined {
  return [environment.AC_DEV_API_ORIGIN, environment.AC_API_URL]
    .map((value) => value?.trim())
    .find((value): value is string => Boolean(value));
}

function validateOptionalConfiguredApiOrigin(
  environment: DevApiEnvironment,
): void {
  const explicit = environment.AC_DEV_API_ORIGIN?.trim();
  if (!explicit) return;
  const url = normalizedOrigin(explicit);
  const isLoopback =
    isLoopbackHost(url.hostname) &&
    (url.protocol === "http:" || url.protocol === "https:");
  if (isLoopback || url.origin === STAGING_API_ORIGIN) return;
  throw new Error(
    "Development API origin must be loopback or the exact staging API origin. Production and arbitrary remote origins are forbidden.",
  );
}

export type DevAuthBridgeConfig = Readonly<{
  browserOrigin: string;
  upstreamOrigin: typeof STAGING_PUBLIC_APP_ORIGIN;
}>;

/**
 * Authenticated staging access is an explicit owner-approved development
 * capability. Both the local browser origin and the upstream learner origin
 * are exact allowlisted values; no wildcard or production target is accepted.
 */
export function resolveDevAuthBridgeConfig(
  environment: DevApiEnvironment,
  nodeEnvironment: string | undefined,
): DevAuthBridgeConfig | null {
  if (nodeEnvironment !== "development") return null;
  if (environment.AC_DEV_AUTH_BRIDGE_ENABLED?.trim() !== "true") return null;

  const browserOriginValue = environment.AC_DEV_AUTH_BRIDGE_ORIGIN?.trim();
  if (!browserOriginValue) {
    throw new Error(
      "AC_DEV_AUTH_BRIDGE_ORIGIN is required when the authenticated development bridge is enabled.",
    );
  }
  const browserOrigin = normalizedOrigin(browserOriginValue);
  if (
    !isLoopbackHost(browserOrigin.hostname) ||
    !["http:", "https:"].includes(browserOrigin.protocol)
  ) {
    throw new Error(
      "AC_DEV_AUTH_BRIDGE_ORIGIN must be an exact http(s) loopback origin.",
    );
  }

  const upstreamOriginValue =
    environment.AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN?.trim();
  if (!upstreamOriginValue) {
    throw new Error(
      "AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN is required when the authenticated development bridge is enabled.",
    );
  }
  const upstreamOrigin = normalizedOrigin(upstreamOriginValue);
  if (upstreamOrigin.origin !== STAGING_PUBLIC_APP_ORIGIN) {
    throw new Error(
      "AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN must be the exact staging learner origin; production and API-host targets are forbidden.",
    );
  }

  return {
    browserOrigin: browserOrigin.origin,
    upstreamOrigin: STAGING_PUBLIC_APP_ORIGIN,
  };
}

/**
 * Development has three data modes:
 * - local: the normal local loopback API;
 * - staging-public-catalog: anonymous catalog GETs only;
 * - staging-authenticated: explicit password login plus learner API access
 *   through a separate local HttpOnly cookie and an ephemeral server mapping.
 */
export function resolveDevApiTarget(
  environment: DevApiEnvironment,
  nodeEnvironment: string | undefined,
): DevApiTarget | null {
  if (nodeEnvironment !== "development") return null;
  validateOptionalConfiguredApiOrigin(environment);

  const authBridge = resolveDevAuthBridgeConfig(environment, nodeEnvironment);
  if (authBridge) {
    return {
      mode: "staging-authenticated",
      origin: authBridge.upstreamOrigin,
      browserOrigin: authBridge.browserOrigin,
    };
  }

  const configured =
    optionalConfiguredApiOrigin(environment) ?? DEFAULT_LOCAL_API_ORIGIN;
  const url = normalizedOrigin(configured);

  if (url.origin === STAGING_API_ORIGIN) {
    return { mode: "staging-public-catalog", origin: STAGING_API_ORIGIN };
  }

  if (
    isLoopbackHost(url.hostname) &&
    (url.protocol === "http:" || url.protocol === "https:")
  ) {
    return { mode: "local", origin: url.origin };
  }

  throw new Error(
    "Development API origin must be loopback or the exact staging API origin. Production and arbitrary remote origins are forbidden.",
  );
}

export function isStagingPublicCatalogPreview(
  environment: DevApiEnvironment,
  nodeEnvironment: string | undefined,
): boolean {
  try {
    return (
      resolveDevApiTarget(environment, nodeEnvironment)?.mode ===
      "staging-public-catalog"
    );
  } catch {
    return false;
  }
}

export function isStagingAuthenticatedBridge(
  environment: DevApiEnvironment,
  nodeEnvironment: string | undefined,
): boolean {
  try {
    return (
      resolveDevApiTarget(environment, nodeEnvironment)?.mode ===
      "staging-authenticated"
    );
  } catch {
    return false;
  }
}

export function isStagingPublicCatalogRequest(url: URL): boolean {
  if (url.pathname === "/v1/programs") {
    if (url.search === "") return true;
    const match = /^\?limit=([1-9]\d{0,2})$/.exec(url.search);
    if (!match) return false;
    const limit = Number(match[1]);
    return limit <= 100;
  }

  if (!url.pathname.startsWith("/v1/programs/")) return false;
  const slug = url.pathname.slice("/v1/programs/".length);
  if (url.search !== "" || slug.length === 0 || slug.includes("/"))
    return false;

  let decoded: string;
  try {
    decoded = decodeURIComponent(slug);
  } catch {
    return false;
  }

  return (
    decoded.length <= MAX_CATALOG_SLUG_LENGTH &&
    decoded !== "." &&
    decoded !== ".." &&
    !decoded.includes("/") &&
    !decoded.includes("\\") &&
    !decoded.includes("%") &&
    !/[\u0000-\u001f\u007f]/.test(decoded) &&
    encodeURIComponent(decoded) === slug
  );
}

function isCanonicalEncodedPathSegment(value: string): boolean {
  if (!value || value.includes("/")) return false;
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return false;
  }
  return (
    decoded.length > 0 &&
    decoded.length <= MAX_BRIDGE_QUERY_VALUE_LENGTH &&
    decoded !== "." &&
    decoded !== ".." &&
    !decoded.includes("/") &&
    !decoded.includes("\\") &&
    !decoded.includes("%") &&
    !/[\u0000-\u001f\u007f]/.test(decoded) &&
    encodeURIComponent(decoded) === value
  );
}

function hasNoQuery(url: URL): boolean {
  return url.search === "";
}

function hasLearningQuery(url: URL): boolean {
  if (url.search === "") return true;
  const keys = [...url.searchParams.keys()];
  if (
    keys.length !== 2 ||
    new Set(keys).size !== 2 ||
    !keys.includes("enrollment_id") ||
    !keys.includes("program_version_id")
  ) {
    return false;
  }
  return keys.every((key) => {
    const value = url.searchParams.get(key);
    return (
      value !== null &&
      value.length > 0 &&
      value.length <= MAX_BRIDGE_QUERY_VALUE_LENGTH &&
      !/[\u0000-\u001f\u007f]/.test(value)
    );
  });
}

function hasAnalyticsQuery(url: URL): boolean {
  if (url.search === "") return true;
  const keys = [...url.searchParams.keys()];
  if (keys.length !== 1 || keys[0] !== "period") return false;
  return ["today", "week", "month"].includes(
    url.searchParams.get("period") ?? "",
  );
}

/**
 * Allow only the learner surface exercised by the real UI. Admin, internal,
 * provider, arbitrary proxy, and unsupported password-recovery routes remain
 * unavailable through the local staging bridge.
 */
export function isStagingAuthenticatedLearnerRequest(
  url: URL,
  method: string,
): boolean {
  const normalizedMethod = method.toUpperCase();
  const { pathname } = url;
  if (pathname === "/v1/auth/password/login") {
    return normalizedMethod === "POST" && hasNoQuery(url);
  }
  if (pathname === "/v1/auth/logout") {
    return normalizedMethod === "POST" && hasNoQuery(url);
  }
  if (pathname === "/v1/me" || pathname === "/v1/context") {
    return (
      (normalizedMethod === "GET" || normalizedMethod === "POST") &&
      hasNoQuery(url) &&
      !(pathname === "/v1/me" && normalizedMethod === "POST")
    );
  }
  if (pathname === "/v1/onboarding") {
    return (
      (normalizedMethod === "GET" || normalizedMethod === "PUT") &&
      hasNoQuery(url)
    );
  }
  if (pathname === "/v1/enrollments/free") {
    return normalizedMethod === "POST" && hasNoQuery(url);
  }
  if (pathname === "/v1/programs" || pathname.startsWith("/v1/programs/")) {
    return normalizedMethod === "GET" && isStagingPublicCatalogRequest(url);
  }

  const learningPrefix = "/v1/learning/";
  if (pathname.startsWith(learningPrefix)) {
    if (pathname === "/v1/learning/insights") {
      return normalizedMethod === "GET" && hasAnalyticsQuery(url);
    }
    return (
      normalizedMethod === "GET" &&
      isCanonicalEncodedPathSegment(pathname.slice(learningPrefix.length)) &&
      hasLearningQuery(url)
    );
  }

  const activityPrefix = "/v1/activities/";
  if (pathname.startsWith(activityPrefix)) {
    const remainder = pathname.slice(activityPrefix.length);
    const activityParts = remainder.split("/");
    if (activityParts.length > 2) return false;
    const [activityId, action] = activityParts;
    if (!isCanonicalEncodedPathSegment(activityId) || !hasNoQuery(url)) {
      return false;
    }
    if (!action) return normalizedMethod === "GET";
    if (action !== "draft" && action !== "evidence") {
      return false;
    }
    return action === "draft"
      ? normalizedMethod === "PUT"
      : normalizedMethod === "POST";
  }

  const certificatePrefix = "/v1/certificates/";
  if (pathname.startsWith(certificatePrefix)) {
    return (
      normalizedMethod === "GET" &&
      hasNoQuery(url) &&
      isCanonicalEncodedPathSegment(pathname.slice(certificatePrefix.length))
    );
  }
  return false;
}

function proxyRequestHeaders(
  request: Request,
  mode: DevApiTarget["mode"],
  stagingSession: string | null = null,
): Headers {
  if (mode === "local") {
    const headers = new Headers(request.headers);
    for (const header of [
      "connection",
      "content-length",
      "host",
      "transfer-encoding",
    ]) {
      headers.delete(header);
    }
    return headers;
  }

  const allowedHeaders =
    mode === "staging-authenticated"
      ? STAGING_AUTH_REQUEST_HEADERS
      : STAGING_PREVIEW_REQUEST_HEADERS;
  const headers = new Headers();
  for (const name of allowedHeaders) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  if (mode === "staging-authenticated") {
    headers.set("origin", STAGING_PUBLIC_APP_ORIGIN);
    if (stagingSession !== null) {
      headers.set("cookie", `${STAGING_SESSION_COOKIE_NAME}=${stagingSession}`);
    }
  }
  return headers;
}

function proxyResponseHeaders(
  response: Response,
  mode: DevApiTarget["mode"],
): Headers {
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("transfer-encoding");
  if (mode === "staging-public-catalog" || mode === "staging-authenticated") {
    headers.delete("set-cookie");
    headers.delete("location");
    headers.delete("refresh");
    headers.delete("authorization");
    headers.delete("proxy-authenticate");
    headers.delete("www-authenticate");
    headers.set("cache-control", "private, no-store");
    headers.set(
      "x-ac-dev-data-mode",
      mode === "staging-authenticated"
        ? "staging-authenticated"
        : "staging-public-catalog",
    );
  }
  return headers;
}

function jsonError(status: number, detail: string): Response {
  return Response.json(
    { title: "Development API proxy unavailable", detail },
    { status, headers: { "cache-control": "no-store" } },
  );
}

function cookieValues(request: Request): Map<string, string[]> {
  const values = new Map<string, string[]>();
  const raw = request.headers.get("cookie");
  if (!raw) return values;
  for (const segment of raw.split(";")) {
    const pair = segment.trim();
    const separator = pair.indexOf("=");
    if (separator < 1) {
      if (
        pair === BRIDGE_SESSION_COOKIE_NAME ||
        pair === STAGING_SESSION_COOKIE_NAME
      ) {
        values.set(pair, [""]);
      }
      continue;
    }
    const name = pair.slice(0, separator);
    const value = pair.slice(separator + 1);
    values.set(name, [...(values.get(name) ?? []), value]);
  }
  return values;
}

function readBridgeSessionCookie(request: Request): string | null {
  const values = cookieValues(request).get(BRIDGE_SESSION_COOKIE_NAME) ?? [];
  if (values.length === 0) return null;
  if (values.length !== 1 || !SESSION_COOKIE_VALUE_PATTERN.test(values[0])) {
    throw new Error("The local development session cookie is invalid.");
  }
  return values[0];
}

function hasStagingSessionCookie(request: Request): boolean {
  return (
    (cookieValues(request).get(STAGING_SESSION_COOKIE_NAME) ?? []).length > 0
  );
}

function hasClientCredentialHeader(request: Request): boolean {
  return (
    request.headers.has("authorization") || request.headers.has("x-api-key")
  );
}

function isAllowedBridgeOrigin(
  request: Request,
  expectedOrigin: string,
): boolean {
  let requestOrigin: string;
  try {
    requestOrigin = new URL(request.url).origin;
  } catch {
    return false;
  }
  if (requestOrigin !== expectedOrigin) return false;
  const originHeader = request.headers.get("origin");
  if (originHeader !== null && originHeader !== expectedOrigin) return false;
  // Cookie-authenticated state changes must carry the exact browser Origin;
  // safe GETs may omit Origin under the Fetch standard.
  if (!["GET", "HEAD"].includes(request.method.toUpperCase())) {
    return originHeader === expectedOrigin;
  }
  return true;
}

function setLocalBridgeCookie(
  response: Response,
  value: string,
  maxAge: number,
): void {
  if (value && !SESSION_COOKIE_VALUE_PATTERN.test(value)) {
    throw new Error(
      "Refusing to set a malformed local development session cookie.",
    );
  }
  response.headers.append(
    "set-cookie",
    [
      `${BRIDGE_SESSION_COOKIE_NAME}=${value}`,
      `Max-Age=${maxAge}`,
      "Path=/",
      "HttpOnly",
      "SameSite=Lax",
      "Secure",
    ].join("; "),
  );
}

function clearLocalBridgeCookie(response: Response): void {
  setLocalBridgeCookie(response, "", 0);
}

function splitSetCookieHeader(value: string): string[] {
  return value.split(/,(?=\s*[^;,=]+=[^;,]*)/);
}

function getSetCookieHeaders(response: Response): string[] {
  const headers = response.headers as Headers & {
    getSetCookie?: () => string[];
  };
  if (typeof headers.getSetCookie === "function") {
    return headers.getSetCookie();
  }
  const combined = response.headers.get("set-cookie");
  return combined ? splitSetCookieHeader(combined) : [];
}

type UpstreamSessionCookieResult =
  | { token: string }
  | { error: "missing" | "invalid" | "duplicate" };

function extractUpstreamSessionCookie(
  setCookieHeaders: string[],
): UpstreamSessionCookieResult {
  const candidates: Array<{ token: string; attributes: string[] }> = [];
  for (const header of setCookieHeaders) {
    const segments = header.split(";");
    const pair = segments.shift()?.trim() ?? "";
    const separator = pair.indexOf("=");
    if (separator < 1) continue;
    const name = pair.slice(0, separator);
    if (name !== STAGING_SESSION_COOKIE_NAME) continue;
    candidates.push({
      token: pair.slice(separator + 1),
      attributes: segments.map((attribute) => attribute.trim().toLowerCase()),
    });
  }
  if (candidates.length === 0) return { error: "missing" };
  if (candidates.length !== 1) return { error: "duplicate" };
  const candidate = candidates[0];
  const hasRequiredAttributes = [
    "secure",
    "httponly",
    "samesite=lax",
    "path=/",
  ].every((attribute) => candidate.attributes.includes(attribute));
  const hasDomainAttribute = candidate.attributes.some((attribute) =>
    attribute.startsWith("domain="),
  );
  if (
    !SESSION_COOKIE_VALUE_PATTERN.test(candidate.token) ||
    !hasRequiredAttributes ||
    hasDomainAttribute
  ) {
    return { error: "invalid" };
  }
  return { token: candidate.token };
}

function localBridgeCookieFailure(): Response {
  return jsonError(
    401,
    "The local development session is invalid or expired. Sign in again through the local bridge.",
  );
}

async function loginResponseContainsBearerToken(
  response: Response,
): Promise<boolean> {
  const body = await response.clone().text();
  if (body.toLowerCase().includes("bearer ")) return true;
  if (response.headers.get("content-type")?.includes("application/json")) {
    return /"(?:access_token|refresh_token|token|authorization)"\s*:/i.test(
      body,
    );
  }
  return false;
}

async function proxyUpstream(
  request: Request,
  target: DevApiTarget,
  fetcher: DevApiFetch,
  stagingSession: string | null,
): Promise<{ response: Response; setCookieHeaders: string[] }> {
  if (request.signal.aborted) {
    return {
      response: jsonError(
        504,
        "The development API proxy timed out or was cancelled.",
      ),
      setCookieHeaders: [],
    };
  }

  const incomingUrl = new URL(request.url);
  const upstreamUrl = new URL(
    `${incomingUrl.pathname}${incomingUrl.search}`,
    target.origin,
  );
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  const abort = () => controller.abort(request.signal.reason);
  request.signal.addEventListener("abort", abort, { once: true });
  if (request.signal.aborted) controller.abort(request.signal.reason);

  try {
    if (controller.signal.aborted) {
      return {
        response: jsonError(
          504,
          "The development API proxy timed out or was cancelled.",
        ),
        setCookieHeaders: [],
      };
    }
    const body =
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer();
    const response = await fetcher(upstreamUrl, {
      method: request.method,
      headers: proxyRequestHeaders(request, target.mode, stagingSession),
      body,
      redirect: "manual",
      signal: controller.signal,
    });
    const setCookieHeaders = getSetCookieHeaders(response);
    if (
      (target.mode === "staging-public-catalog" ||
        target.mode === "staging-authenticated") &&
      response.status >= 300 &&
      response.status < 400
    ) {
      return {
        response: jsonError(
          502,
          "The staging API returned an unexpected redirect.",
        ),
        setCookieHeaders,
      };
    }
    return {
      response: new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: proxyResponseHeaders(response, target.mode),
      }),
      setCookieHeaders,
    };
  } catch (error) {
    if (controller.signal.aborted) {
      return {
        response: jsonError(
          504,
          "The development API proxy timed out or was cancelled.",
        ),
        setCookieHeaders: [],
      };
    }
    return {
      response: jsonError(
        502,
        target.mode === "staging-authenticated"
          ? "The staging API could not be reached."
          : error instanceof Error
            ? `The configured API could not be reached: ${error.message}`
            : "The configured API could not be reached.",
      ),
      setCookieHeaders: [],
    };
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abort);
  }
}

async function proxyAuthenticatedStaging(
  request: Request,
  target: Extract<DevApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevApiFetch,
  sessionStore: DevelopmentBridgeSessionStore,
): Promise<Response> {
  if (!isAllowedBridgeOrigin(request, target.browserOrigin)) {
    return jsonError(
      403,
      "The authenticated staging bridge accepts requests only from its exact configured localhost origin.",
    );
  }
  if (hasClientCredentialHeader(request)) {
    return jsonError(
      400,
      "Bearer and API-key credentials are not accepted by the local staging bridge.",
    );
  }
  if (hasStagingSessionCookie(request)) {
    return jsonError(
      403,
      "Staging session cookies cannot be used by the local bridge. Sign in through the local login form.",
    );
  }

  const incomingUrl = new URL(request.url);
  if (!isStagingAuthenticatedLearnerRequest(incomingUrl, request.method)) {
    return jsonError(
      403,
      "This learner route is not enabled through the development staging bridge.",
    );
  }

  let localSession: string | null;
  try {
    localSession = readBridgeSessionCookie(request);
  } catch {
    return localBridgeCookieFailure();
  }

  const isLogin = incomingUrl.pathname === "/v1/auth/password/login";
  const isLogout = incomingUrl.pathname === "/v1/auth/logout";
  let stagingSession: string | null = null;
  if (!isLogin) {
    if (
      localSession === null &&
      request.method.toUpperCase() === "GET" &&
      isStagingPublicCatalogRequest(incomingUrl)
    ) {
      const publicCatalog = await proxyUpstream(
        request,
        { mode: "staging-public-catalog", origin: STAGING_API_ORIGIN },
        fetcher,
        null,
      );
      return publicCatalog.response;
    }
    if (localSession === null) return localBridgeCookieFailure();
    stagingSession = sessionStore.get(localSession);
    if (stagingSession === null) {
      return localBridgeCookieFailure();
    }
  }

  const upstream = await proxyUpstream(
    request,
    target,
    fetcher,
    stagingSession,
  );
  const response = upstream.response;

  if (isLogin && response.ok) {
    const sessionCookie = extractUpstreamSessionCookie(
      upstream.setCookieHeaders,
    );
    if (!("token" in sessionCookie)) {
      return jsonError(
        502,
        "The staging login did not return the required host-only session contract.",
      );
    }
    try {
      if (await loginResponseContainsBearerToken(response)) {
        return jsonError(
          502,
          "The staging login returned an unsupported browser credential contract.",
        );
      }
    } catch {
      return jsonError(
        502,
        "The staging login returned an unreadable response.",
      );
    }
    const nextLocalSession = randomBytes(32).toString("base64url");
    sessionStore.set(nextLocalSession, sessionCookie.token);
    setLocalBridgeCookie(
      response,
      nextLocalSession,
      BRIDGE_SESSION_MAX_AGE_SECONDS,
    );
    return response;
  }

  if (localSession !== null && (isLogout || response.status === 401)) {
    sessionStore.delete(localSession);
    clearLocalBridgeCookie(response);
  }
  return response;
}

export async function proxyDevelopmentLearnerApi(
  request: Request,
  fetcher: DevApiFetch = globalThis.fetch.bind(globalThis),
  environment: DevApiEnvironment = process.env,
  nodeEnvironment: string | undefined = process.env.NODE_ENV,
  sessionStore: DevelopmentBridgeSessionStore = defaultDevelopmentBridgeSessionStore(),
): Promise<Response> {
  let target: DevApiTarget | null;
  try {
    target = resolveDevApiTarget(environment, nodeEnvironment);
  } catch (error) {
    return jsonError(
      500,
      error instanceof Error
        ? error.message
        : "Invalid development API origin.",
    );
  }
  if (!target) {
    return jsonError(404, "The learner API proxy is development-only.");
  }

  const incomingUrl = new URL(request.url);
  if (!incomingUrl.pathname.startsWith("/v1/")) {
    return jsonError(404, "Only same-origin /v1 requests are proxied.");
  }

  if (target.mode === "staging-authenticated") {
    return proxyAuthenticatedStaging(request, target, fetcher, sessionStore);
  }

  if (target.mode === "staging-public-catalog") {
    if (
      request.method !== "GET" ||
      !isStagingPublicCatalogRequest(incomingUrl)
    ) {
      return jsonError(
        403,
        "Local staging preview permits anonymous published-catalog GETs only. Test protected data and mutations through the explicitly enabled local bridge or deployed staging.",
      );
    }
  }

  return (await proxyUpstream(request, target, fetcher, null)).response;
}
