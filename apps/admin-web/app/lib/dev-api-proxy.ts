import { randomBytes } from "node:crypto";

import { z } from "zod";

const DEFAULT_LOCAL_API_ORIGIN = "http://127.0.0.1:8000";
const STAGING_ADMIN_ORIGIN = "https://admin-staging.authorityclosers.com";
const LOCAL_SESSION_COOKIE_NAME = "__Host-ac_dev_admin_qa_session";
const LEARNER_SESSION_COOKIE_NAME = "__Host-ac_dev_qa_session";
const STAGING_SESSION_COOKIE_NAME = "__Host-ac_session";
const ACCESS_COOKIE_NAME = "CF_Authorization";
const PROXY_TIMEOUT_MS = 12_000;
const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;
const SESSION_MAX_COUNT = 4;
const MAX_REQUEST_BODY_BYTES = 1024 * 1024;
const SESSION_VALUE_PATTERN = /^[A-Za-z0-9_-]{43,512}$/;
const ACCESS_JWT_PATTERN =
  /^[A-Za-z0-9_-]{16,2048}\.[A-Za-z0-9_-]{16,4096}\.[A-Za-z0-9_-]{16,2048}$/;
const UUID_PATH_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const STAGING_REQUEST_HEADERS = new Set([
  "accept",
  "accept-language",
  "content-type",
  "if-match",
  "idempotency-key",
  "user-agent",
  "x-request-id",
]);

type DevAdminEnvironment = Readonly<Record<string, string | undefined>>;

export type DevAdminApiTarget =
  | Readonly<{ mode: "local"; origin: string }>
  | Readonly<{
      mode: "staging-authenticated";
      origin: typeof STAGING_ADMIN_ORIGIN;
      browserOrigin: string;
      accessJwt: string;
    }>;

export type DevAdminFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface DevelopmentAdminSessionStore {
  get(localSession: string): string | null;
  set(localSession: string, stagingSession: string): void;
  delete(localSession: string): void;
}

type StoredSession = Readonly<{
  stagingSession: string;
  expiresAt: number;
}>;

export class InMemoryDevelopmentAdminSessionStore
  implements DevelopmentAdminSessionStore
{
  private readonly sessions = new Map<string, StoredSession>();

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
    while (this.sessions.size >= SESSION_MAX_COUNT) {
      const oldest = this.sessions.keys().next().value;
      if (typeof oldest !== "string") break;
      this.sessions.delete(oldest);
    }
    this.sessions.set(localSession, {
      stagingSession,
      expiresAt: this.now() + SESSION_MAX_AGE_SECONDS * 1000,
    });
  }

  delete(localSession: string): void {
    this.sessions.delete(localSession);
  }
}

const STORE_KEY = Symbol.for(
  "authority-closers.admin-web.development-bridge-store",
);

function isSessionStore(value: unknown): value is DevelopmentAdminSessionStore {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DevelopmentAdminSessionStore>;
  return (
    typeof candidate.get === "function" &&
    typeof candidate.set === "function" &&
    typeof candidate.delete === "function"
  );
}

function defaultSessionStore(): DevelopmentAdminSessionStore {
  const runtimeGlobal = globalThis as unknown as Record<symbol, unknown>;
  const existing = runtimeGlobal[STORE_KEY];
  if (isSessionStore(existing)) return existing;
  const store = new InMemoryDevelopmentAdminSessionStore();
  runtimeGlobal[STORE_KEY] = store;
  return store;
}

function isLoopbackHost(hostname: string): boolean {
  return (
    hostname === "127.0.0.1" ||
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname === "[::1]" ||
    hostname === "::1"
  );
}

function exactOrigin(value: string): URL {
  const url = new URL(value);
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.pathname !== "/" && url.pathname !== "")
  ) {
    throw new Error(
      "Development admin origins may contain only a scheme, host, and optional port.",
    );
  }
  return url;
}

function loopbackOrigin(value: string, field: string): URL {
  const url = exactOrigin(value);
  if (
    !isLoopbackHost(url.hostname) ||
    (url.protocol !== "http:" && url.protocol !== "https:")
  ) {
    throw new Error(`${field} must be an exact HTTP(S) loopback origin.`);
  }
  return url;
}

export function resolveDevAdminApiTarget(
  environment: DevAdminEnvironment,
  nodeEnvironment: string | undefined,
): DevAdminApiTarget | null {
  if (nodeEnvironment !== "development") return null;

  if (
    environment.AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED?.trim().toLowerCase() ===
    "true"
  ) {
    const browserOriginValue =
      environment.AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN?.trim();
    if (!browserOriginValue) {
      throw new Error(
        "AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN is required when the admin bridge is enabled.",
      );
    }
    const browserOrigin = loopbackOrigin(
      browserOriginValue,
      "AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN",
    );

    const upstreamValue =
      environment.AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN?.trim();
    if (!upstreamValue) {
      throw new Error(
        "AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN is required when the admin bridge is enabled.",
      );
    }
    const upstream = exactOrigin(upstreamValue);
    if (upstream.origin !== STAGING_ADMIN_ORIGIN) {
      throw new Error(
        "The admin bridge upstream must be the exact staging admin origin.",
      );
    }

    const accessJwt = environment.AC_DEV_ADMIN_ACCESS_JWT?.trim() ?? "";
    if (!ACCESS_JWT_PATTERN.test(accessJwt) || accessJwt.length > 8192) {
      throw new Error(
        "AC_DEV_ADMIN_ACCESS_JWT must contain a current Cloudflare Access user token.",
      );
    }
    return {
      mode: "staging-authenticated",
      origin: STAGING_ADMIN_ORIGIN,
      browserOrigin: browserOrigin.origin,
      accessJwt,
    };
  }

  const configured =
    environment.AC_DEV_ADMIN_API_ORIGIN?.trim() ||
    environment.AC_API_URL?.trim() ||
    DEFAULT_LOCAL_API_ORIGIN;
  const local = loopbackOrigin(configured, "AC_DEV_ADMIN_API_ORIGIN");
  return { mode: "local", origin: local.origin };
}

export function isStagingAdminBridge(
  environment: DevAdminEnvironment,
  nodeEnvironment: string | undefined,
): boolean {
  try {
    return (
      resolveDevAdminApiTarget(environment, nodeEnvironment)?.mode ===
      "staging-authenticated"
    );
  } catch {
    return false;
  }
}

function hasNoQuery(url: URL): boolean {
  return url.search === "";
}

function isUuid(value: string): boolean {
  return UUID_PATH_PATTERN.test(value);
}

/** Exact first-slice admin API surface; every other route stays unavailable. */
export function isStagingAdminRequest(url: URL, method: string): boolean {
  if (!hasNoQuery(url)) return false;
  const normalizedMethod = method.toUpperCase();
  const { pathname } = url;

  if (pathname === "/v1/dev-bridge/health") {
    return normalizedMethod === "GET";
  }
  if (pathname === "/v1/auth/password/login") {
    return normalizedMethod === "POST";
  }
  if (pathname === "/v1/auth/logout") {
    return normalizedMethod === "POST";
  }
  if (pathname === "/v1/me" || pathname === "/v1/context") {
    return normalizedMethod === "GET";
  }
  if (
    pathname === "/v1/admin/corrections" ||
    pathname === "/v1/admin/enrollment-grants" ||
    pathname === "/v1/admin/recovery/reconcile"
  ) {
    return normalizedMethod === "POST";
  }

  const publishMatch = /^\/v1\/admin\/program-versions\/([^/]+)\/publish$/.exec(
    pathname,
  );
  if (publishMatch) {
    return normalizedMethod === "POST" && isUuid(publishMatch[1]);
  }
  const retryMatch = /^\/v1\/admin\/jobs\/([^/]+)\/retry$/.exec(pathname);
  if (retryMatch) {
    return normalizedMethod === "POST" && isUuid(retryMatch[1]);
  }
  return false;
}

function problem(status: number, code: string, detail: string): Response {
  return Response.json(
    { title: "Development admin bridge unavailable", detail, code },
    {
      status,
      headers: {
        "cache-control": "no-store",
        "content-type": "application/problem+json",
        "x-ac-dev-data-mode": "staging-admin-authenticated",
      },
    },
  );
}

function cookieValues(request: Request): Map<string, string[]> {
  const values = new Map<string, string[]>();
  const raw = request.headers.get("cookie");
  if (!raw) return values;
  for (const segment of raw.split(";")) {
    const pair = segment.trim();
    const separator = pair.indexOf("=");
    if (separator < 1) continue;
    const name = pair.slice(0, separator);
    const value = pair.slice(separator + 1);
    values.set(name, [...(values.get(name) ?? []), value]);
  }
  return values;
}

function stripDevelopmentBridgeCookies(headers: Headers): void {
  const raw = headers.get("cookie");
  if (!raw) return;
  const retained = raw
    .split(";")
    .map((segment) => segment.trim())
    .filter((pair) => {
      const separator = pair.indexOf("=");
      const name = separator < 0 ? pair : pair.slice(0, separator);
      return (
        name !== LOCAL_SESSION_COOKIE_NAME &&
        name !== LEARNER_SESSION_COOKIE_NAME
      );
    });
  if (retained.length === 0) {
    headers.delete("cookie");
  } else {
    headers.set("cookie", retained.join("; "));
  }
}

function localSessionFrom(request: Request): string | null {
  const values = cookieValues(request).get(LOCAL_SESSION_COOKIE_NAME) ?? [];
  if (values.length === 0) return null;
  if (values.length !== 1 || !SESSION_VALUE_PATTERN.test(values[0])) {
    throw new Error("The local admin development session cookie is invalid.");
  }
  return values[0];
}

function hasForbiddenBrowserCredential(request: Request): boolean {
  const cookies = cookieValues(request);
  return (
    cookies.has(STAGING_SESSION_COOKIE_NAME) ||
    cookies.has(ACCESS_COOKIE_NAME) ||
    request.headers.has("authorization") ||
    request.headers.has("x-api-key") ||
    request.headers.has("cf-access-token") ||
    request.headers.has("cf-access-jwt-assertion") ||
    request.headers.has("cf-access-client-id") ||
    request.headers.has("cf-access-client-secret")
  );
}

function hasAllowedOrigin(request: Request, browserOrigin: string): boolean {
  let requestOrigin: string;
  try {
    requestOrigin = new URL(request.url).origin;
  } catch {
    return false;
  }
  if (requestOrigin !== browserOrigin) return false;
  const supplied = request.headers.get("origin");
  if (supplied !== null && supplied !== browserOrigin) return false;
  if (!["GET", "HEAD"].includes(request.method.toUpperCase())) {
    return supplied === browserOrigin;
  }
  return true;
}

function setLocalSessionCookie(
  response: Response,
  value: string,
  maxAge: number,
): void {
  if (value && !SESSION_VALUE_PATTERN.test(value)) {
    throw new Error("Refusing to set a malformed local admin session.");
  }
  response.headers.append(
    "set-cookie",
    [
      `${LOCAL_SESSION_COOKIE_NAME}=${value}`,
      `Max-Age=${maxAge}`,
      "Path=/",
      "HttpOnly",
      "SameSite=Lax",
      "Secure",
    ].join("; "),
  );
}

function clearLocalSessionCookie(response: Response): void {
  setLocalSessionCookie(response, "", 0);
}

function splitSetCookieHeader(value: string): string[] {
  return value.split(/,(?=\s*[^;,=]+=[^;,]*)/);
}

function setCookieHeaders(response: Response): string[] {
  const headers = response.headers as Headers & {
    getSetCookie?: () => string[];
  };
  if (typeof headers.getSetCookie === "function") return headers.getSetCookie();
  const combined = response.headers.get("set-cookie");
  return combined ? splitSetCookieHeader(combined) : [];
}

function stagingSessionFrom(headers: string[]): string | null {
  const candidates: Array<{ value: string; attributes: string[] }> = [];
  for (const header of headers) {
    const segments = header.split(";");
    const pair = segments.shift()?.trim() ?? "";
    const separator = pair.indexOf("=");
    if (
      separator < 1 ||
      pair.slice(0, separator) !== STAGING_SESSION_COOKIE_NAME
    ) {
      continue;
    }
    candidates.push({
      value: pair.slice(separator + 1),
      attributes: segments.map((value) => value.trim().toLowerCase()),
    });
  }
  if (candidates.length !== 1) return null;
  const candidate = candidates[0];
  const required = ["secure", "httponly", "samesite=lax", "path=/"].every(
    (attribute) => candidate.attributes.includes(attribute),
  );
  const hasDomain = candidate.attributes.some((attribute) =>
    attribute.startsWith("domain="),
  );
  return required && !hasDomain && SESSION_VALUE_PATTERN.test(candidate.value)
    ? candidate.value
    : null;
}

async function loginResponseContainsBrowserCredential(
  response: Response,
): Promise<boolean> {
  const body = await response.clone().text();
  if (body.toLowerCase().includes("bearer ")) return true;
  if (!response.headers.get("content-type")?.includes("application/json")) {
    return false;
  }
  return /"(?:access_token|refresh_token|token|authorization|cf_authorization)"\s*:/i.test(
    body,
  );
}

function upstreamHeaders(
  request: Request,
  target: Extract<DevAdminApiTarget, { mode: "staging-authenticated" }>,
  stagingSession: string | null,
): Headers {
  const headers = new Headers();
  for (const name of STAGING_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  headers.set("origin", STAGING_ADMIN_ORIGIN);
  const cookies = [`${ACCESS_COOKIE_NAME}=${target.accessJwt}`];
  if (stagingSession) {
    cookies.push(`${STAGING_SESSION_COOKIE_NAME}=${stagingSession}`);
  }
  headers.set("cookie", cookies.join("; "));
  return headers;
}

function sanitizedResponseHeaders(response: Response): Headers {
  const headers = new Headers(response.headers);
  for (const name of [
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "set-cookie",
    "location",
    "refresh",
    "authorization",
    "proxy-authenticate",
    "www-authenticate",
    "cf-access-jwt-assertion",
  ]) {
    headers.delete(name);
  }
  headers.set("cache-control", "private, no-store");
  headers.set("x-ac-dev-data-mode", "staging-admin-authenticated");
  return headers;
}

type UpstreamResult = Readonly<{
  response: Response;
  cookies: string[];
}>;

function readStreamChunk(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  signal: AbortSignal,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  if (signal.aborted) {
    return Promise.reject(
      signal.reason ??
        new Error("The incoming request body read was cancelled."),
    );
  }
  return new Promise((resolve, reject) => {
    const abort = () => {
      void reader.cancel(signal.reason).catch(() => undefined);
      reject(
        signal.reason ??
          new Error("The incoming request body read was cancelled."),
      );
    };
    signal.addEventListener("abort", abort, { once: true });
    reader.read().then(
      (result) => {
        signal.removeEventListener("abort", abort);
        resolve(result);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", abort);
        reject(error);
      },
    );
  });
}

async function readBoundedRequestBody(
  request: Request,
  signal: AbortSignal,
): Promise<{ body: ArrayBuffer | undefined; tooLarge: boolean }> {
  if (request.method === "GET" || request.method === "HEAD") {
    return { body: undefined, tooLarge: false };
  }
  const declaredLength = request.headers.get("content-length");
  if (
    declaredLength !== null &&
    (!/^\d+$/.test(declaredLength) ||
      Number(declaredLength) > MAX_REQUEST_BODY_BYTES)
  ) {
    return { body: undefined, tooLarge: true };
  }
  if (!request.body) return { body: undefined, tooLarge: false };

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await readStreamChunk(reader, signal);
    if (done) break;
    total += value.byteLength;
    if (total > MAX_REQUEST_BODY_BYTES) {
      await reader.cancel();
      return { body: undefined, tooLarge: true };
    }
    chunks.push(value);
  }
  const combined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { body: combined.buffer, tooLarge: false };
}

async function proxyStagingRequest(
  request: Request,
  target: Extract<DevAdminApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevAdminFetch,
  stagingSession: string | null,
): Promise<UpstreamResult> {
  const incoming = new URL(request.url);
  const upstream = new URL(
    `${incoming.pathname}${incoming.search}`,
    target.origin,
  );
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  const abort = () => controller.abort(request.signal.reason);
  request.signal.addEventListener("abort", abort, { once: true });
  if (request.signal.aborted) controller.abort(request.signal.reason);
  try {
    const boundedBody = await readBoundedRequestBody(
      request,
      controller.signal,
    );
    if (boundedBody.tooLarge) {
      return {
        response: problem(
          413,
          "admin_bridge_request_too_large",
          "The admin request body is too large.",
        ),
        cookies: [],
      };
    }
    const response = await fetcher(upstream, {
      method: request.method,
      headers: upstreamHeaders(request, target, stagingSession),
      body: boundedBody.body,
      redirect: "manual",
      signal: controller.signal,
    });
    const cookies = setCookieHeaders(response);
    if (response.status >= 300 && response.status < 400) {
      return {
        response: problem(
          502,
          "admin_bridge_access_required",
          "Cloudflare Access is unavailable or expired. Restart the local staging workflow and authenticate again.",
        ),
        cookies,
      };
    }
    return {
      response: new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: sanitizedResponseHeaders(response),
      }),
      cookies,
    };
  } catch {
    return {
      response: problem(
        controller.signal.aborted ? 504 : 502,
        controller.signal.aborted
          ? "admin_bridge_upstream_timeout"
          : "admin_bridge_upstream_unavailable",
        controller.signal.aborted
          ? "The staging admin API did not respond before the bridge timeout."
          : "The staging admin API could not be reached.",
      ),
      cookies: [],
    };
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abort);
  }
}

const meSchema = z
  .object({
    person_id: z.uuid(),
    selected_tenant_id: z.uuid().nullable(),
    membership_role: z
      .enum(["owner", "admin", "support", "learner"])
      .nullable(),
    permissions: z.array(z.string().min(1).max(64)).max(64),
  })
  .passthrough();

const contextSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    tenant_id: z.uuid().nullable(),
    membership_role: z
      .enum(["owner", "admin", "support", "learner"])
      .nullable(),
    permissions: z.array(z.string().min(1).max(64)).max(64),
  })
  .strict();

async function readAdminIdentity(
  path: "/v1/me" | "/v1/context",
  target: Extract<DevAdminApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevAdminFetch,
  stagingSession: string,
): Promise<unknown | null> {
  try {
    const response = await fetcher(new URL(path, target.origin), {
      method: "GET",
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      headers: {
        accept: "application/json",
        cookie: `${ACCESS_COOKIE_NAME}=${target.accessJwt}; ${STAGING_SESSION_COOKIE_NAME}=${stagingSession}`,
      },
    });
    if (response.status !== 200) return null;
    return await response.json();
  } catch {
    return null;
  }
}

async function isAuthorizedAdminSession(
  target: Extract<DevAdminApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevAdminFetch,
  stagingSession: string,
): Promise<boolean> {
  const [rawMe, rawContext] = await Promise.all([
    readAdminIdentity("/v1/me", target, fetcher, stagingSession),
    readAdminIdentity("/v1/context", target, fetcher, stagingSession),
  ]);
  const parsedMe = meSchema.safeParse(rawMe);
  const parsedContext = contextSchema.safeParse(rawContext);
  if (!parsedMe.success || !parsedContext.success) return false;
  const me = parsedMe.data;
  const context = parsedContext.data;
  const role = context.membership_role;
  return (
    (role === "owner" || role === "admin" || role === "support") &&
    context.tenant_id !== null &&
    me.person_id === context.person_id &&
    me.selected_tenant_id === context.tenant_id &&
    me.membership_role === role &&
    me.permissions.includes("admin_surface") &&
    context.permissions.includes("admin_surface")
  );
}

async function revokeUnmappedSession(
  target: Extract<DevAdminApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevAdminFetch,
  stagingSession: string,
): Promise<void> {
  try {
    await fetcher(new URL("/v1/auth/logout", target.origin), {
      method: "POST",
      redirect: "manual",
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      headers: {
        accept: "application/json",
        origin: STAGING_ADMIN_ORIGIN,
        cookie: `${ACCESS_COOKIE_NAME}=${target.accessJwt}; ${STAGING_SESSION_COOKIE_NAME}=${stagingSession}`,
      },
    });
  } catch {
    // Best-effort revocation after a failed authorization check. No local
    // mapping is created, regardless of upstream availability.
  }
}

async function probeAdminTransport(
  target: Extract<DevAdminApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevAdminFetch,
): Promise<Response> {
  try {
    const response = await fetcher(new URL("/v1/me", target.origin), {
      method: "GET",
      redirect: "manual",
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      headers: {
        accept: "application/json",
        cookie: `${ACCESS_COOKIE_NAME}=${target.accessJwt}`,
      },
    });
    if (response.status >= 300 && response.status < 400) {
      return problem(
        502,
        "admin_bridge_access_required",
        "Cloudflare Access is unavailable or expired. Restart the local staging workflow and authenticate again.",
      );
    }
    let code: string | null = null;
    try {
      const body = (await response.json()) as { code?: unknown };
      code = typeof body.code === "string" ? body.code : null;
    } catch {
      code = null;
    }
    if (response.status !== 401 || code !== "authentication_required") {
      return problem(
        502,
        "admin_bridge_transport_unverified",
        "Cloudflare Access responded, but the staging product API boundary could not be verified.",
      );
    }
    return Response.json(
      {
        status: "ok",
        transport: "connected",
        product_session: "sign_in_required",
        upstream: "staging-admin",
      },
      {
        headers: {
          "cache-control": "no-store",
          "x-ac-dev-data-mode": "staging-admin-authenticated",
        },
      },
    );
  } catch {
    return problem(
      502,
      "admin_bridge_upstream_unavailable",
      "The staging admin API could not be reached.",
    );
  }
}

async function proxyStagingAdmin(
  request: Request,
  target: Extract<DevAdminApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevAdminFetch,
  sessionStore: DevelopmentAdminSessionStore,
): Promise<Response> {
  if (!hasAllowedOrigin(request, target.browserOrigin)) {
    return problem(
      403,
      "admin_bridge_origin_denied",
      "The admin bridge accepts requests only from its exact configured localhost origin.",
    );
  }
  if (hasForbiddenBrowserCredential(request)) {
    return problem(
      403,
      "admin_bridge_browser_credential_denied",
      "Remote session, Access, bearer, and API-key credentials are not accepted from the browser.",
    );
  }

  const incoming = new URL(request.url);
  if (!isStagingAdminRequest(incoming, request.method)) {
    return problem(
      403,
      "admin_bridge_route_denied",
      "This route is not enabled through the development admin bridge.",
    );
  }
  if (incoming.pathname === "/v1/dev-bridge/health") {
    return probeAdminTransport(target, fetcher);
  }

  let localSession: string | null;
  try {
    localSession = localSessionFrom(request);
  } catch {
    const response = problem(
      401,
      "admin_bridge_session_required",
      "The local admin session is invalid or expired. Sign in again.",
    );
    clearLocalSessionCookie(response);
    return response;
  }
  const isLogin = incoming.pathname === "/v1/auth/password/login";
  const isLogout = incoming.pathname === "/v1/auth/logout";
  let stagingSession: string | null = null;
  if (!isLogin) {
    if (!localSession) {
      const response = problem(
        401,
        "admin_bridge_session_required",
        "The local admin session is invalid or expired. Sign in again.",
      );
      clearLocalSessionCookie(response);
      return response;
    }
    stagingSession = sessionStore.get(localSession);
    if (!stagingSession) {
      const response = problem(
        401,
        "admin_bridge_session_required",
        "The local admin session is invalid or expired. Sign in again.",
      );
      clearLocalSessionCookie(response);
      return response;
    }
  }

  const upstream = await proxyStagingRequest(
    request,
    target,
    fetcher,
    stagingSession,
  );
  const response = upstream.response;
  if (isLogin && response.ok) {
    const issuedSession = stagingSessionFrom(upstream.cookies);
    if (!issuedSession) {
      return problem(
        502,
        "admin_bridge_session_contract_invalid",
        "The staging login did not return the required host-only session contract.",
      );
    }
    try {
      if (await loginResponseContainsBrowserCredential(response)) {
        await revokeUnmappedSession(target, fetcher, issuedSession);
        return problem(
          502,
          "admin_bridge_credential_contract_invalid",
          "The staging login returned an unsupported browser credential contract.",
        );
      }
    } catch {
      await revokeUnmappedSession(target, fetcher, issuedSession);
      return problem(
        502,
        "admin_bridge_credential_contract_invalid",
        "The staging login returned an unreadable credential contract.",
      );
    }
    if (!(await isAuthorizedAdminSession(target, fetcher, issuedSession))) {
      await revokeUnmappedSession(target, fetcher, issuedSession);
      return problem(
        403,
        "admin_bridge_authorization_denied",
        "The authenticated account has no verified admin tenant and permission context.",
      );
    }
    const nextLocalSession = randomBytes(32).toString("base64url");
    sessionStore.set(nextLocalSession, issuedSession);
    setLocalSessionCookie(response, nextLocalSession, SESSION_MAX_AGE_SECONDS);
    return response;
  }

  if (localSession && (isLogout || response.status === 401)) {
    sessionStore.delete(localSession);
    clearLocalSessionCookie(response);
  }
  return response;
}

async function proxyLocalAdmin(
  request: Request,
  target: Extract<DevAdminApiTarget, { mode: "local" }>,
  fetcher: DevAdminFetch,
): Promise<Response> {
  const incoming = new URL(request.url);
  const upstream = new URL(
    `${incoming.pathname}${incoming.search}`,
    target.origin,
  );
  const headers = new Headers(request.headers);
  for (const name of [
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
  ]) {
    headers.delete(name);
  }
  stripDevelopmentBridgeCookies(headers);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  const abort = () => controller.abort(request.signal.reason);
  request.signal.addEventListener("abort", abort, { once: true });
  if (request.signal.aborted) controller.abort(request.signal.reason);
  try {
    const boundedBody = await readBoundedRequestBody(
      request,
      controller.signal,
    );
    if (boundedBody.tooLarge) {
      return problem(
        413,
        "admin_bridge_request_too_large",
        "The admin request body is too large.",
      );
    }
    return await fetcher(upstream, {
      method: request.method,
      headers,
      body: boundedBody.body,
      redirect: "manual",
      signal: controller.signal,
    });
  } catch {
    if (controller.signal.aborted) {
      return problem(
        504,
        "admin_local_api_timeout",
        "The loopback admin API request timed out or was cancelled.",
      );
    }
    return problem(
      502,
      "admin_local_api_unavailable",
      "The loopback admin API could not be reached.",
    );
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abort);
  }
}

export async function proxyDevelopmentAdminApi(
  request: Request,
  fetcher: DevAdminFetch = globalThis.fetch.bind(globalThis),
  environment: DevAdminEnvironment = process.env,
  nodeEnvironment: string | undefined = process.env.NODE_ENV,
  sessionStore: DevelopmentAdminSessionStore = defaultSessionStore(),
): Promise<Response> {
  let target: DevAdminApiTarget | null;
  try {
    target = resolveDevAdminApiTarget(environment, nodeEnvironment);
  } catch (error) {
    return problem(
      500,
      "admin_bridge_configuration_invalid",
      error instanceof Error
        ? error.message
        : "The admin bridge configuration is invalid.",
    );
  }
  if (!target) {
    return problem(
      404,
      "admin_development_proxy_unavailable",
      "The admin API proxy is development-only.",
    );
  }
  if (!new URL(request.url).pathname.startsWith("/v1/")) {
    return problem(
      404,
      "admin_proxy_path_invalid",
      "Only same-origin /v1 requests are proxied.",
    );
  }
  return target.mode === "staging-authenticated"
    ? proxyStagingAdmin(request, target, fetcher, sessionStore)
    : proxyLocalAdmin(request, target, fetcher);
}
