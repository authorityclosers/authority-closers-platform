import { randomBytes } from "node:crypto";

import { verifyAdminIdentity } from "./admin-identity";
import { fetchLocalAdminWire } from "./local-admin-transport";
import {
  fetchLocalStudioPreviewWire,
  studioPreviewRequestKind,
} from "./local-studio-preview-transport";
import {
  fetchLocalStudioVideoWire,
  isStudioVideoByteRequest,
  studioVideoByteLength,
  StudioVideoTransportError,
} from "./local-studio-video-transport";

const DEFAULT_LOCAL_API_ORIGIN = "http://127.0.0.1:8000";
const LOCAL_SANDBOX_ADMIN_ORIGIN = "http://admin.localhost:3101";
const LOCAL_SANDBOX_COACH_ORIGIN = "http://coach.localhost:3102";
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
      mode: "local-sandbox";
      origin: typeof DEFAULT_LOCAL_API_ORIGIN;
      browserOrigin:
        | typeof LOCAL_SANDBOX_ADMIN_ORIGIN
        | typeof LOCAL_SANDBOX_COACH_ORIGIN;
    }>
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

function originFromAuthorityHeader(value: string, protocol: string): string {
  if (!value || value !== value.trim() || /[\s,/?#@\\]/u.test(value)) {
    throw new Error("Development admin authority header is malformed.");
  }
  return exactOrigin(`${protocol}//${value}`).origin;
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
    environment.AC_DEV_LOCAL_SANDBOX_ENABLED?.trim().toLowerCase() === "true"
  ) {
    if (
      environment.AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED?.trim().toLowerCase() ===
      "true"
    ) {
      throw new Error(
        "Local sandbox and remote staging bridge modes are mutually exclusive.",
      );
    }
    const browser = exactOrigin(
      environment.AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN?.trim() ?? "",
    );
    const upstream = exactOrigin(
      environment.AC_DEV_ADMIN_API_ORIGIN?.trim() ?? "",
    );
    if (
      browser.origin !==
        (environment.AC_DEV_OPERATIONS_SURFACE === "coach"
          ? LOCAL_SANDBOX_COACH_ORIGIN
          : LOCAL_SANDBOX_ADMIN_ORIGIN) ||
      upstream.origin !== DEFAULT_LOCAL_API_ORIGIN
    ) {
      throw new Error(
        "Local sandbox requires the exact admin.localhost:3101 and 127.0.0.1:8000 HTTP origin pair.",
      );
    }
    return {
      mode: "local-sandbox",
      origin: DEFAULT_LOCAL_API_ORIGIN,
      browserOrigin:
        environment.AC_DEV_OPERATIONS_SURFACE === "coach"
          ? LOCAL_SANDBOX_COACH_ORIGIN
          : LOCAL_SANDBOX_ADMIN_ORIGIN,
    };
  }

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

export function developmentAdminLoginMode(
  environment: DevAdminEnvironment,
  nodeEnvironment: string | undefined,
): "local-sandbox" | "staging-authenticated" | null {
  try {
    const mode = resolveDevAdminApiTarget(environment, nodeEnvironment)?.mode;
    return mode === "local-sandbox" || mode === "staging-authenticated"
      ? mode
      : null;
  } catch {
    return null;
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
  const videoLibrary = /^\/v1\/admin\/studio\/programs\/([^/]+)\/videos$/.exec(
    url.pathname,
  );
  if (videoLibrary) {
    const entries = [...url.searchParams.entries()];
    return (
      method.toUpperCase() === "GET" &&
      isUuid(videoLibrary[1]) &&
      new Set(entries.map(([name]) => name)).size === entries.length &&
      entries.every(([name, value]) =>
        name === "limit"
          ? /^(?:[1-9]|[1-4][0-9]|50)$/.test(value)
          : name === "after" && isUuid(value),
      )
    );
  }
  if (url.pathname === "/v1/platform/tenants") {
    const entries = [...url.searchParams.entries()];
    return (
      method.toUpperCase() === "GET" &&
      (entries.length === 0 ||
        (entries.length === 1 &&
          entries[0][0] === "after_id" &&
          isUuid(entries[0][1])))
    );
  }
  if (!hasNoQuery(url)) return false;
  const normalizedMethod = method.toUpperCase();
  const { pathname } = url;
  const videoUpload =
    /^\/v1\/admin\/studio\/programs\/([^/]+)\/video-uploads(?:\/([^/]+))?$/.exec(
      pathname,
    );
  if (videoUpload) {
    return (
      isUuid(videoUpload[1]) &&
      (videoUpload[2]
        ? isUuid(videoUpload[2]) && normalizedMethod === "GET"
        : normalizedMethod === "POST")
    );
  }
  const activityVideo =
    /^\/v1\/admin\/studio\/programs\/([^/]+)\/activities\/([^/]+)\/video$/.exec(
      pathname,
    );
  if (activityVideo) {
    return (
      ["GET", "POST"].includes(normalizedMethod) &&
      isUuid(activityVideo[1]) &&
      isUuid(activityVideo[2])
    );
  }

  if (pathname === "/v1/dev-bridge/health") {
    return normalizedMethod === "GET";
  }
  if (pathname === "/v1/auth/password/login") {
    return normalizedMethod === "POST";
  }
  if (pathname === "/v1/auth/logout") {
    return normalizedMethod === "POST";
  }
  if (
    pathname === "/v1/me" ||
    pathname === "/v1/me/workspaces" ||
    pathname === "/v1/me/platform-access" ||
    pathname === "/v1/context" ||
    pathname === "/v1/me/studio-access"
  ) {
    return normalizedMethod === "GET";
  }
  if (pathname === "/v1/admin/studio/programs") {
    return normalizedMethod === "GET" || normalizedMethod === "POST";
  }
  if (pathname === "/v1/admin/studio/readiness") {
    return normalizedMethod === "GET";
  }
  const studioProgramMatch = /^\/v1\/admin\/studio\/programs\/([^/]+)$/.exec(
    pathname,
  );
  if (studioProgramMatch) {
    return normalizedMethod === "GET" && isUuid(studioProgramMatch[1]);
  }
  const studioRevision =
    /^\/v1\/admin\/studio\/program-versions\/([^/]+)\/revision$/.exec(pathname);
  if (studioRevision)
    return normalizedMethod === "POST" && isUuid(studioRevision[1]);
  const studioAuthoring =
    /^\/v1\/admin\/studio\/program-versions\/([^/]+)\/(modules|activities)(?:\/([^/]+))?(?:\/(activities))?$/.exec(
      pathname,
    );
  if (studioAuthoring) {
    const [, versionId, resource, resourceId, nested] = studioAuthoring;
    if (!isUuid(versionId) || (resourceId !== undefined && !isUuid(resourceId)))
      return false;
    return (
      (normalizedMethod === "POST" &&
        resource === "modules" &&
        ((!resourceId && !nested) ||
          (Boolean(resourceId) && nested === "activities"))) ||
      (normalizedMethod === "PATCH" && Boolean(resourceId) && !nested)
    );
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
    const rawUrl = new URL(request.url);
    if (!isLoopbackHost(rawUrl.hostname)) return false;

    const expectedUrl = new URL(browserOrigin);
    const hostHeader = request.headers.get("host");

    if (hostHeader !== null) {
      const directHostOrigin = originFromAuthorityHeader(
        hostHeader,
        rawUrl.protocol,
      );
      if (directHostOrigin !== browserOrigin) return false;
      requestOrigin = directHostOrigin;
    } else {
      if (rawUrl.origin !== browserOrigin) return false;
      requestOrigin = rawUrl.origin;
    }

    const forwardedHost = request.headers.get("x-forwarded-host");
    if (forwardedHost !== null) {
      const forwardedHostOrigin = originFromAuthorityHeader(
        forwardedHost,
        rawUrl.protocol,
      );
      if (forwardedHostOrigin !== browserOrigin) return false;
    }

    const forwardedProto = request.headers.get("x-forwarded-proto");
    if (forwardedProto !== null) {
      if (!/^(?:http|https)$/u.test(forwardedProto)) return false;
      if (`${forwardedProto}:` !== expectedUrl.protocol) return false;
    }
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

async function readAdminIdentity(
  path: "/v1/me" | "/v1/context" | "/v1/me/studio-access",
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
  const [rawMe, rawContext, rawAccess] = await Promise.all([
    readAdminIdentity("/v1/me", target, fetcher, stagingSession),
    readAdminIdentity("/v1/context", target, fetcher, stagingSession),
    readAdminIdentity("/v1/me/studio-access", target, fetcher, stagingSession),
  ]);
  return verifyAdminIdentity(rawMe, rawContext, rawAccess) !== null;
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
  target: Extract<DevAdminApiTarget, { mode: "local" | "local-sandbox" }>,
  fetcher: DevAdminFetch | undefined,
  videoUploadEnabled: boolean,
): Promise<Response> {
  const incoming = new URL(request.url);
  const videoBytes = isStudioVideoByteRequest(incoming, request.method);
  const previewKind = studioPreviewRequestKind(incoming, request.method);
  const localPreview = target.mode === "local-sandbox" && previewKind !== null;
  const capability =
    /^\/v1\/admin\/studio\/programs\/([^/]+)\/video-upload-capability$/.exec(
      incoming.pathname,
    );
  const completion =
    /^\/v1\/admin\/studio\/programs\/([^/]+)\/video-uploads\/([^/]+)\/complete$/.exec(
      incoming.pathname,
    );
  const exactCapability =
    !!capability &&
    isUuid(capability[1]) &&
    request.method === "GET" &&
    hasNoQuery(incoming) &&
    !incoming.hash;
  const exactCompletion =
    !!completion &&
    isUuid(completion[1]) &&
    isUuid(completion[2]) &&
    request.method === "POST" &&
    hasNoQuery(incoming) &&
    !incoming.hash;
  const localVideoCommand =
    target.mode === "local-sandbox" &&
    (exactCapability ||
      (exactCompletion && videoUploadEnabled) ||
      localPreview);
  if ((capability || completion) && !localVideoCommand) {
    return problem(
      403,
      "studio_video_upload_unavailable",
      "Video uploads are not enabled in this local workspace.",
    );
  }
  const localVideoBytes =
    videoBytes && target.mode === "local-sandbox" && videoUploadEnabled;
  if (videoBytes && !localVideoBytes) {
    return problem(
      403,
      "studio_video_upload_unavailable",
      "Video uploads are not enabled in this local workspace.",
    );
  }
  if (target.mode === "local-sandbox") {
    if (!hasAllowedOrigin(request, target.browserOrigin)) {
      return problem(
        403,
        "admin_local_origin_denied",
        "The local sandbox accepts only its configured admin origin.",
      );
    }
    const selectContext =
      incoming.pathname === "/v1/context" &&
      request.method === "POST" &&
      hasNoQuery(incoming);
    if (
      (!isStagingAdminRequest(incoming, request.method) &&
        !selectContext &&
        !localVideoBytes &&
        !localVideoCommand) ||
      incoming.pathname === "/v1/dev-bridge/health" ||
      (target.browserOrigin === LOCAL_SANDBOX_COACH_ORIGIN &&
        !isCoachApiRequest(incoming, request.method) &&
        !localVideoBytes &&
        !localVideoCommand)
    ) {
      return problem(
        403,
        "admin_local_route_denied",
        "This route is unavailable in the local admin sandbox.",
      );
    }
  }
  const upstream = new URL(
    `${incoming.pathname}${incoming.search}`,
    target.origin,
  );
  const headers =
    target.mode === "local-sandbox"
      ? new Headers()
      : new Headers(request.headers);
  if (target.mode === "local-sandbox") {
    for (const name of STAGING_REQUEST_HEADERS) {
      const value = request.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    const sessions = cookieValues(request).get("ac_session") ?? [];
    if (sessions.length > 0)
      headers.set(
        "cookie",
        sessions.map((value) => `ac_session=${value}`).join("; "),
      );
  }
  for (const name of [
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
  ]) {
    headers.delete(name);
  }
  stripDevelopmentBridgeCookies(headers);
  if (target.mode === "local-sandbox") {
    // Trusted reverse-proxy values, never copied from browser forwarding headers.
    headers.set("host", new URL(target.browserOrigin).host);
    headers.set("origin", target.browserOrigin);
  }
  if (localPreview && previewKind === "bytes") {
    if (!videoUploadEnabled)
      return problem(
        503,
        "preview_not_configured",
        "Video preview is not enabled in this workspace.",
      );
    if (
      hasForbiddenBrowserCredential(request) ||
      request.body ||
      ![null, "0"].includes(request.headers.get("content-length")) ||
      request.headers.has("transfer-encoding") ||
      ![null, "identity"].includes(request.headers.get("content-encoding"))
    ) {
      return problem(
        400,
        "preview_request_invalid",
        "Use the normal workspace session with no request body.",
      );
    }
    const range = request.headers.get("range");
    if (range !== null) {
      if (!/^bytes=\d+-\d*$/.test(range) || range.length > 64)
        return problem(
          416,
          "preview_range_invalid",
          "Use one video byte range.",
        );
      headers.set("range", range);
    }
    try {
      return await (fetcher ?? fetchLocalStudioPreviewWire)(upstream, {
        method: request.method,
        headers,
        signal: request.signal,
        redirect: "error",
      });
    } catch {
      return problem(
        502,
        "preview_unavailable",
        "Video preview could not be reached. Try again.",
      );
    }
  }
  if (localVideoBytes) {
    try {
      // Keep the one-MiB buffered JSON path unchanged. Only this opt-in exact
      // PUT receives raw streamed bytes and the backend's length/checksum fence.
      if (hasForbiddenBrowserCredential(request)) {
        return problem(
          403,
          "studio_video_credential_denied",
          "Use your normal local workspace session for video uploads.",
        );
      }
      studioVideoByteLength(request.headers);
      for (const name of ["content-length", "x-content-sha256"]) {
        headers.set(name, request.headers.get(name)!);
      }
      return await (fetcher ?? fetchLocalStudioVideoWire)(upstream, {
        method: "PUT",
        headers,
        body: request.body,
        signal: request.signal,
        redirect: "manual",
      });
    } catch (error) {
      if (error instanceof StudioVideoTransportError) {
        return problem(error.status, error.code, error.message);
      }
      return problem(
        502,
        "studio_video_unavailable",
        "The local video upload service could not be reached.",
      );
    }
  }
  if (exactCompletion && localVideoCommand) {
    if (
      hasForbiddenBrowserCredential(request) ||
      request.headers.has("transfer-encoding") ||
      ![null, "0"].includes(request.headers.get("content-length")) ||
      ![null, "identity"].includes(request.headers.get("content-encoding")) ||
      !/^[A-Za-z0-9_-]{1,128}$/.test(
        request.headers.get("idempotency-key") ?? "",
      )
    ) {
      return problem(
        400,
        "studio_video_completion_invalid",
        "Complete this upload with its existing request identity and no body.",
      );
    }
  }
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    exactCompletion && localVideoCommand ? 180_000 : PROXY_TIMEOUT_MS,
  );
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
    if (
      exactCompletion &&
      localVideoCommand &&
      boundedBody.body &&
      boundedBody.body.byteLength !== 0
    ) {
      return problem(
        400,
        "studio_video_completion_invalid",
        "Video completion takes no body.",
      );
    }
    const transport =
      fetcher ??
      (target.mode === "local-sandbox"
        ? fetchLocalAdminWire
        : globalThis.fetch.bind(globalThis));
    const response = await transport(upstream, {
      method: request.method,
      headers,
      body: boundedBody.body,
      redirect: "manual",
      signal: controller.signal,
    });
    if (
      exactCapability &&
      localVideoCommand &&
      !videoUploadEnabled &&
      response.ok
    ) {
      await response.body?.cancel();
      return Response.json(
        {
          available: false,
          max_source_bytes: null,
          accepted_content_types: ["video/mp4", "video/webm"],
          reason: "not_configured",
        },
        { headers: { "cache-control": "no-store" } },
      );
    }
    return response;
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

/** Coach transport never exposes operational commands even to an admin account. */
export function isCoachApiRequest(url: URL, method: string): boolean {
  if (url.pathname === "/v1/context" && method === "POST")
    return hasNoQuery(url);
  return (
    isStagingAdminRequest(url, method) &&
    ([
      "/v1/me",
      "/v1/me/workspaces",
      "/v1/context",
      "/v1/me/studio-access",
      "/v1/auth/password/login",
      "/v1/auth/logout",
    ].includes(url.pathname) ||
      url.pathname.startsWith("/v1/admin/studio/") ||
      /^\/v1\/admin\/program-versions\/[^/]+\/publish$/.test(url.pathname))
  );
}

export async function proxyDevelopmentAdminApi(
  request: Request,
  fetcher?: DevAdminFetch,
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
    ? proxyStagingAdmin(
        request,
        target,
        fetcher ?? globalThis.fetch.bind(globalThis),
        sessionStore,
      )
    : proxyLocalAdmin(
        request,
        target,
        fetcher,
        environment.AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED === "true",
      );
}
