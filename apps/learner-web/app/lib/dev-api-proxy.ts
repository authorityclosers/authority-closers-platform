import { randomBytes } from "node:crypto";
import { proxyLocalSandboxMedia } from "./local-media-upstream";
import { proxyLocalSandboxAvatarUpload } from "./local-avatar-upstream";
import { fetchDevelopmentLocalApiUpstream } from "./dev-local-api-upstream";
import { fetchLocalLearnerWire } from "./local-api-upstream";
import { LOCAL_SANDBOX_ORIGIN } from "./local-sandbox";
import { fetchDevelopmentMediaUpstream } from "./dev-media-upstream";
import {
  DEVELOPMENT_MEDIA_MAX_BYTES,
  DEVELOPMENT_MEDIA_REGISTRATION,
  DEVELOPMENT_MEDIA_LOCATOR_PREFIX,
  DEVELOPMENT_MEDIA_MAX_SOURCES,
  isDevelopmentMediaLocatorPath,
  readDevelopmentMediaSource,
  isDevelopmentMediaRange,
} from "./dev-media-transport";

const DEFAULT_LOCAL_API_ORIGIN = "http://127.0.0.1:8000";
const STAGING_API_ORIGIN = "https://api-staging.authorityclosers.com";
const STAGING_PUBLIC_APP_ORIGIN = "https://staging.authorityclosers.com";
const PROXY_TIMEOUT_MS = 12_000;
const MEDIA_READ_TIMEOUT_MS = 30_000;
const MEDIA_STREAM_MAX_MS = 30 * 60 * 1000;
const MAX_BRIDGE_REQUEST_BODY_BYTES = 1024 * 1024;
const MAX_CATALOG_SLUG_LENGTH = 120;
const MAX_BRIDGE_QUERY_VALUE_LENGTH = 200;
const MAX_BRIDGE_CURSOR_LENGTH = 512;
const BRIDGE_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;
const BRIDGE_SESSION_MAX_COUNT = 8;
const BRIDGE_SESSION_COOKIE_NAME = "__Host-ac_dev_qa_session";
const ADMIN_BRIDGE_SESSION_COOKIE_NAME = "__Host-ac_dev_admin_qa_session";
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
  | {
      mode: "local";
      origin: string;
      browserOrigin?: typeof LOCAL_SANDBOX_ORIGIN;
    }
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
  registerMedia(
    localSession: string,
    sources: string[],
  ): RegisteredDevelopmentMedia[] | "limited" | null;
  mediaSource(localSession: string, locator: string): string | null;
  generation(localSession: string): object | null;
  allowMediaRegistration(localSession: string): boolean;
}

type RegisteredDevelopmentMedia = { path: string; expires_at: number };

type StoredBridgeSession = {
  stagingSession: string;
  expiresAt: number;
  media: Map<string, { source: string; expiresAt: number }>;
  registrations: { start: number; count: number };
};

/**
 * Ephemeral server-side bridge state. It intentionally has no persistence
 * path: restarting the local dev server drops every local-to-staging mapping.
 */
export class InMemoryDevelopmentBridgeSessionStore
  implements DevelopmentBridgeSessionStore
{
  private readonly sessions = new Map<string, StoredBridgeSession>();

  constructor(
    private readonly now: () => number = Date.now,
    private readonly createLocator: () => string = () =>
      randomBytes(32).toString("base64url"),
  ) {}

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
      media: new Map(),
      registrations: { start: this.now(), count: 0 },
    });
  }

  delete(localSession: string): void {
    this.sessions.delete(localSession);
  }

  generation(localSession: string): object | null {
    return this.get(localSession) ? this.sessions.get(localSession)! : null;
  }

  allowMediaRegistration(localSession: string): boolean {
    if (!this.get(localSession)) return false;
    const session = this.sessions.get(localSession)!;
    const now = this.now();
    if (now - session.registrations.start >= 60_000)
      session.registrations = { start: now, count: 0 };
    return ++session.registrations.count <= 30;
  }

  registerMedia(
    localSession: string,
    sources: string[],
  ): RegisteredDevelopmentMedia[] | "limited" | null {
    if (!this.get(localSession)) return null;
    const session = this.sessions.get(localSession)!;
    const now = this.now();
    if (
      sources.length < 1 ||
      sources.length > DEVELOPMENT_MEDIA_MAX_SOURCES ||
      new Set(sources).size !== sources.length
    )
      return null;
    const validated = sources.map((source) =>
      readDevelopmentMediaSource(source, now),
    );
    if (validated.some((value) => !value)) return null;
    for (const [locator, entry] of session.media)
      if (entry.expiresAt <= now) session.media.delete(locator);
    const missing = sources.filter(
      (source) =>
        ![...session.media.values()].some((entry) => entry.source === source),
    );
    if (session.media.size + missing.length > 64) return "limited";
    const nextMedia = new Map(session.media);
    const registrations = sources.map((source, index) => {
      const existing = [...nextMedia].find(
        ([, entry]) => entry.source === source,
      );
      if (existing)
        return {
          path: DEVELOPMENT_MEDIA_LOCATOR_PREFIX + existing[0],
          expires_at: existing[1].expiresAt,
        };
      const locator = this.createLocator();
      if (!/^[A-Za-z0-9_-]{43}$/.test(locator) || nextMedia.has(locator))
        throw new Error("Local media registry is unavailable.");
      const expiresAt = Math.min(
        validated[index]!.expiresAt,
        session.expiresAt,
      );
      nextMedia.set(locator, { source, expiresAt });
      return {
        path: DEVELOPMENT_MEDIA_LOCATOR_PREFIX + locator,
        expires_at: expiresAt,
      };
    });
    session.media = nextMedia;
    return registrations;
  }

  mediaSource(localSession: string, locator: string): string | null {
    if (!this.get(localSession)) return null;
    const session = this.sessions.get(localSession)!;
    const entry = session.media.get(locator);
    if (!entry) return null;
    if (entry.expiresAt <= this.now()) {
      session.media.delete(locator);
      return null;
    }
    return entry.source;
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
    typeof candidate.delete === "function" &&
    typeof candidate.registerMedia === "function" &&
    typeof candidate.mediaSource === "function" &&
    typeof candidate.generation === "function" &&
    typeof candidate.allowMediaRegistration === "function"
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
    hostname.endsWith(".localhost") ||
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

function originFromAuthorityHeader(value: string, protocol: string): string {
  if (!value || value !== value.trim() || /[\s,/?#@\\]/u.test(value)) {
    throw new Error("Development bridge authority header is malformed.");
  }
  return normalizedOrigin(`${protocol}//${value}`).origin;
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
    return environment.AC_DEV_LOCAL_SANDBOX_ENABLED === "true"
      ? {
          mode: "local",
          origin: url.origin,
          browserOrigin: LOCAL_SANDBOX_ORIGIN,
        }
      : { mode: "local", origin: url.origin };
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

function hasLearningCollectionQuery(url: URL): boolean {
  const keys = [...url.searchParams.keys()];
  const uniqueKeys = new Set(keys);
  if (
    keys.length < 1 ||
    keys.length > 2 ||
    uniqueKeys.size !== keys.length ||
    !uniqueKeys.has("limit") ||
    [...uniqueKeys].some((key) => key !== "limit" && key !== "cursor") ||
    url.searchParams.get("limit") !== "50"
  ) {
    return false;
  }
  if (!uniqueKeys.has("cursor")) return true;
  const cursor = url.searchParams.get("cursor");
  return (
    cursor !== null &&
    cursor.length > 0 &&
    cursor.length <= MAX_BRIDGE_CURSOR_LENGTH &&
    !/[\u0000-\u001f\u007f]/.test(cursor)
  );
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
  if (pathname === DEVELOPMENT_MEDIA_REGISTRATION)
    return normalizedMethod === "POST" && hasNoQuery(url);
  if (pathname.startsWith(DEVELOPMENT_MEDIA_LOCATOR_PREFIX))
    return (
      ["GET", "HEAD"].includes(normalizedMethod) &&
      hasNoQuery(url) &&
      isDevelopmentMediaLocatorPath(pathname)
    );
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
  if (pathname === "/v1/me/app-updates") {
    return normalizedMethod === "GET" && hasNoQuery(url);
  }
  if (pathname === "/v1/me/consent") {
    return normalizedMethod === "GET" && hasNoQuery(url);
  }
  if (pathname === "/v1/me/consent/renew") {
    return normalizedMethod === "POST" && hasNoQuery(url);
  }
  if (
    /^\/v1\/me\/app-updates\/[a-z0-9]+(?:-[a-z0-9]+)*\/read$/.test(pathname)
  ) {
    const releaseId = pathname.split("/")[4];
    return (
      normalizedMethod === "POST" && releaseId.length <= 128 && hasNoQuery(url)
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
  if (pathname === "/v1/profile/avatar") {
    return (
      (normalizedMethod === "GET" || normalizedMethod === "POST") &&
      hasNoQuery(url)
    );
  }
  const avatarPrefix = "/v1/profile/avatar/";
  if (pathname.startsWith(avatarPrefix)) {
    const parts = pathname.slice(avatarPrefix.length).split("/");
    return (
      normalizedMethod === "POST" &&
      parts.length === 2 &&
      isCanonicalEncodedPathSegment(parts[0]) &&
      parts[1] === "complete" &&
      hasNoQuery(url)
    );
  }
  if (pathname === "/v1/learning") {
    return normalizedMethod === "GET" && hasLearningCollectionQuery(url);
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
  target: DevApiTarget,
  stagingSession: string | null = null,
): Headers {
  if (target.mode === "local") {
    const headers = new Headers(request.headers);
    for (const header of [
      "connection",
      "content-length",
      "forwarded",
      "host",
      "transfer-encoding",
      "x-forwarded-host",
      "x-forwarded-port",
      "x-forwarded-proto",
    ]) {
      headers.delete(header);
    }
    stripDevelopmentBridgeCookies(headers);
    return headers;
  }

  const allowedHeaders =
    target.mode === "staging-authenticated"
      ? STAGING_AUTH_REQUEST_HEADERS
      : STAGING_PREVIEW_REQUEST_HEADERS;
  const headers = new Headers();
  for (const name of allowedHeaders) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  if (target.mode === "staging-authenticated") {
    headers.set("origin", STAGING_PUBLIC_APP_ORIGIN);
    if (stagingSession !== null) {
      headers.set("cookie", `${STAGING_SESSION_COOKIE_NAME}=${stagingSession}`);
    }
  }
  return headers;
}

function proxyUpstreamOrigin(target: DevApiTarget): string {
  if (target.mode !== "local" || target.browserOrigin === undefined) {
    return target.origin;
  }
  // Address the configured loopback API through the package-owned learner
  // hostname. Node fetch will then generate the canonical Host itself; it does
  // not honor a caller-supplied Host header. Scheme and port remain those of
  // the already-validated loopback API origin.
  const upstream = new URL(target.origin);
  upstream.hostname = new URL(target.browserOrigin).hostname;
  return upstream.origin;
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
        name !== BRIDGE_SESSION_COOKIE_NAME &&
        name !== ADMIN_BRIDGE_SESSION_COOKIE_NAME
      );
    });
  if (retained.length === 0) {
    headers.delete("cookie");
  } else {
    headers.set("cookie", retained.join("; "));
  }
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
    const rawUrl = new URL(request.url);
    if (!isLoopbackHost(rawUrl.hostname)) return false;

    const expectedUrl = new URL(expectedOrigin);
    const hostHeader = request.headers.get("host");

    if (hostHeader !== null) {
      const directHostOrigin = originFromAuthorityHeader(
        hostHeader,
        rawUrl.protocol,
      );
      if (directHostOrigin !== expectedOrigin) return false;
      requestOrigin = directHostOrigin;
    } else {
      if (rawUrl.origin !== expectedOrigin) return false;
      requestOrigin = rawUrl.origin;
    }

    const forwardedHost = request.headers.get("x-forwarded-host");
    if (forwardedHost !== null) {
      const forwardedHostOrigin = originFromAuthorityHeader(
        forwardedHost,
        rawUrl.protocol,
      );
      if (forwardedHostOrigin !== expectedOrigin) return false;
    }

    const forwardedProto = request.headers.get("x-forwarded-proto");
    if (forwardedProto !== null) {
      if (!/^(?:http|https)$/u.test(forwardedProto)) return false;
      if (`${forwardedProto}:` !== expectedUrl.protocol) return false;
    }
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
  const response = jsonError(
    401,
    "The local development session is invalid or expired. Sign in again through the local bridge.",
  );
  clearLocalBridgeCookie(response);
  return response;
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
  maximumBytes = MAX_BRIDGE_REQUEST_BODY_BYTES,
): Promise<{ body: ArrayBuffer | undefined; tooLarge: boolean }> {
  if (request.method === "GET" || request.method === "HEAD") {
    return { body: undefined, tooLarge: false };
  }
  const declaredLength = request.headers.get("content-length");
  if (
    declaredLength !== null &&
    (!/^\d+$/.test(declaredLength) || Number(declaredLength) > maximumBytes)
  ) {
    return { body: undefined, tooLarge: true };
  }
  if (!request.body) return { body: undefined, tooLarge: false };

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await readStreamChunk(reader, signal);
      if (done) break;
      total += value.byteLength;
      if (total > maximumBytes) {
        void reader.cancel().catch(() => undefined);
        return { body: undefined, tooLarge: true };
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const combined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { body: combined.buffer, tooLarge: false };
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
  const localNativeTransport =
    target.mode === "local" &&
    target.browserOrigin === LOCAL_SANDBOX_ORIGIN &&
    fetcher === fetchLocalLearnerWire;
  const upstreamUrl = new URL(
    `${incomingUrl.pathname}${incomingUrl.search}`,
    localNativeTransport
      ? DEFAULT_LOCAL_API_ORIGIN
      : proxyUpstreamOrigin(target),
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
    const boundedBody = await readBoundedRequestBody(
      request,
      controller.signal,
    );
    if (boundedBody.tooLarge) {
      return {
        response: jsonError(
          413,
          "The development bridge request body exceeds the 1 MiB limit.",
        ),
        setCookieHeaders: [],
      };
    }
    const response = await fetcher(upstreamUrl, {
      method: request.method,
      headers: proxyRequestHeaders(request, target, stagingSession),
      body: boundedBody.body,
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

/** Private progressive/caption bytes only; session/grant authority stays upstream. */
async function proxyStagingMedia(
  request: Request,
  target: Extract<DevApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevApiFetch,
  stagingSession: string,
  approvedSource: string,
): Promise<Response> {
  const range = request.headers.get("range");
  if (!isDevelopmentMediaRange(range)) {
    return jsonError(
      416,
      "Only one bounded byte range is supported by local media delivery.",
    );
  }
  if (request.headers.get("sec-fetch-site") === "cross-site") {
    return jsonError(
      403,
      "Cross-site requests cannot use local media delivery.",
    );
  }
  if (request.signal.aborted)
    return jsonError(504, "Local media delivery was cancelled.");

  const controller = new AbortController();
  const abort = () => controller.abort();
  request.signal.addEventListener("abort", abort, { once: true });
  if (request.signal.aborted) controller.abort();
  let headerTimer: ReturnType<typeof setTimeout> | undefined = setTimeout(
    abort,
    PROXY_TIMEOUT_MS,
  );
  let streamTimer: ReturnType<typeof setTimeout> | undefined;
  let readTimer: ReturnType<typeof setTimeout> | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
  let finished = false;
  let transferred = false;
  const sanitizedError = () =>
    new Error("Local media stream is unavailable or cancelled.");
  const cleanup = () => {
    if (finished) return;
    finished = true;
    clearTimeout(headerTimer);
    clearTimeout(streamTimer);
    clearTimeout(readTimer);
    request.signal.removeEventListener("abort", abort);
    controller.signal.removeEventListener("abort", cancelStream);
  };
  const cancelStream = () => {
    if (finished) return;
    streamController?.error(sanitizedError());
    cleanup();
    void reader?.cancel().catch(() => undefined);
  };
  try {
    const upstream = new URL(approvedSource);
    if (
      upstream.origin !== target.origin ||
      !readDevelopmentMediaSource(approvedSource)
    )
      return jsonError(
        403,
        "Local media authorization is unavailable or expired.",
      );
    const headers = new Headers({
      accept:
        request.headers.get("accept") ?? "video/mp4, video/webm, text/vtt",
      "accept-encoding": "identity",
      origin: STAGING_PUBLIC_APP_ORIGIN,
      cookie: `${STAGING_SESSION_COOKIE_NAME}=${stagingSession}`,
    });
    if (range !== null) headers.set("range", range);
    const response = await fetcher(upstream, {
      method: request.method,
      headers,
      redirect: "manual",
      cache: "no-store",
      credentials: "omit",
      signal: controller.signal,
    });
    clearTimeout(headerTimer);
    headerTimer = undefined;
    const discard = () => {
      void response.body?.cancel().catch(() => undefined);
      controller.abort();
    };
    if (controller.signal.aborted) {
      discard();
      return jsonError(504, "Local media delivery was cancelled.");
    }
    if (![200, 206, 416].includes(response.status)) {
      discard();
      const status =
        response.status >= 400 && response.status <= 599
          ? response.status
          : 502;
      return jsonError(
        status,
        "The approved staging media could not be delivered.",
      );
    }

    const outputHeaders = new Headers({
      "cache-control": "private, no-store",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
      "x-ac-dev-data-mode": "staging-authenticated",
    });
    const contentRange = response.headers.get("content-range");
    if (response.status === 416) {
      discard();
      if (
        contentRange &&
        /^bytes \*\/[1-9]\d{0,9}$/.test(contentRange) &&
        Number(contentRange.slice(8)) <= DEVELOPMENT_MEDIA_MAX_BYTES
      ) {
        outputHeaders.set("content-range", contentRange);
      }
      return new Response(null, { status: 416, headers: outputHeaders });
    }
    const mime = response.headers
      .get("content-type")
      ?.split(";", 1)[0]
      .trim()
      .toLowerCase();
    const encoding = response.headers.get("content-encoding");
    const length = response.headers.get("content-length") ?? "";
    const declared = Number(length);
    if (
      !mime ||
      !["video/mp4", "video/webm", "text/vtt"].includes(mime) ||
      (encoding !== null && encoding.toLowerCase() !== "identity") ||
      !/^[1-9]\d{0,9}$/.test(length) ||
      declared > DEVELOPMENT_MEDIA_MAX_BYTES
    ) {
      discard();
      return jsonError(
        502,
        "Local delivery accepts only bounded progressive video or caption bytes.",
      );
    }
    if (response.status === 206) {
      const parsed = /^bytes (0|[1-9]\d*)-(0|[1-9]\d*)\/([1-9]\d*)$/.exec(
        contentRange ?? "",
      );
      const requested = /^bytes=(\d+)-(\d*)$/.exec(range ?? "");
      if (
        range === null ||
        !parsed ||
        ![parsed[1], parsed[2], parsed[3]].every((value) =>
          Number.isSafeInteger(Number(value)),
        ) ||
        Number(parsed[2]) < Number(parsed[1]) ||
        Number(parsed[2]) >= Number(parsed[3]) ||
        Number(parsed[3]) > DEVELOPMENT_MEDIA_MAX_BYTES ||
        Number(parsed[2]) - Number(parsed[1]) + 1 !== declared ||
        !requested ||
        Number(parsed[1]) !== Number(requested[1]) ||
        Number(parsed[2]) !==
          Math.min(
            requested[2] ? Number(requested[2]) : Number(parsed[3]) - 1,
            Number(parsed[3]) - 1,
          )
      ) {
        discard();
        return jsonError(502, "The staging media range response was invalid.");
      }
      outputHeaders.set("content-range", contentRange!);
    }
    outputHeaders.set(
      "content-type",
      mime === "text/vtt" ? "text/vtt; charset=utf-8" : mime,
    );
    outputHeaders.set("content-length", length);
    const accepts = response.headers.get("accept-ranges");
    if (accepts === "bytes" || accepts === "none")
      outputHeaders.set("accept-ranges", accepts);
    const etag = response.headers.get("etag");
    if (etag && /^"[a-f0-9]{64}"$/i.test(etag)) outputHeaders.set("etag", etag);
    if (request.method === "HEAD") {
      discard();
      return new Response(null, {
        status: response.status,
        headers: outputHeaders,
      });
    }
    if (!response.body) {
      discard();
      return jsonError(502, "The staging media stream was empty.");
    }
    reader = response.body.getReader();
    let observed = 0;
    const stream = new ReadableStream<Uint8Array>(
      {
        start(output) {
          streamController = output;
          controller.signal.addEventListener("abort", cancelStream, {
            once: true,
          });
          streamTimer = setTimeout(abort, MEDIA_STREAM_MAX_MS);
          if (controller.signal.aborted) cancelStream();
        },
        async pull(output) {
          if (finished) return;
          readTimer = setTimeout(abort, MEDIA_READ_TIMEOUT_MS);
          try {
            const { done, value } = await readStreamChunk(
              reader!,
              controller.signal,
            );
            clearTimeout(readTimer);
            readTimer = undefined;
            if (finished) return;
            if (done) {
              if (observed !== declared) throw sanitizedError();
              cleanup();
              reader!.releaseLock();
              output.close();
            } else {
              observed += value.byteLength;
              if (
                !value.byteLength ||
                value.byteLength > 16 * 1024 * 1024 ||
                observed > declared
              )
                throw sanitizedError();
              output.enqueue(value);
            }
          } catch {
            if (!finished) {
              output.error(sanitizedError());
              cleanup();
              controller.abort();
              void reader?.cancel().catch(() => undefined);
            }
          }
        },
        cancel() {
          cleanup();
          controller.abort();
          void reader?.cancel().catch(() => undefined);
        },
      },
      { highWaterMark: 0 },
    );
    transferred = true;
    return new Response(stream, {
      status: response.status,
      headers: outputHeaders,
    });
  } catch {
    const timedOut = controller.signal.aborted;
    controller.abort();
    return jsonError(
      timedOut ? 504 : 502,
      "Local media delivery is unavailable or timed out.",
    );
  } finally {
    if (!transferred) cleanup();
  }
}

async function proxyAuthenticatedStaging(
  request: Request,
  target: Extract<DevApiTarget, { mode: "staging-authenticated" }>,
  fetcher: DevApiFetch,
  sessionStore: DevelopmentBridgeSessionStore,
  mediaFetcher: DevApiFetch,
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
      request.method.toUpperCase() === "GET" &&
      isStagingPublicCatalogRequest(incomingUrl)
    ) {
      const hasStaleLocalSession =
        localSession !== null && sessionStore.get(localSession) === null;
      if (localSession !== null && !hasStaleLocalSession) {
        stagingSession = sessionStore.get(localSession);
      } else {
        const publicCatalog = await proxyUpstream(
          request,
          { mode: "staging-public-catalog", origin: STAGING_API_ORIGIN },
          fetcher,
          null,
        );
        if (hasStaleLocalSession)
          clearLocalBridgeCookie(publicCatalog.response);
        return publicCatalog.response;
      }
    }
    if (localSession === null) return localBridgeCookieFailure();
    stagingSession = sessionStore.get(localSession);
    if (stagingSession === null) {
      return localBridgeCookieFailure();
    }
  }

  if (incomingUrl.pathname === DEVELOPMENT_MEDIA_REGISTRATION) {
    const generation = sessionStore.generation(localSession!);
    if (!sessionStore.allowMediaRegistration(localSession!))
      return jsonError(
        429,
        "Local media registration limit reached. Reopen the lesson later.",
      );
    if (
      request.headers.get("sec-fetch-site") === "cross-site" ||
      !/^application\/json(?:;\s*charset=utf-8)?$/i.test(
        request.headers.get("content-type") ?? "",
      ) ||
      request.headers.has("content-encoding")
    )
      return jsonError(
        400,
        "Local media registration requires same-origin JSON.",
      );
    const controller = new AbortController();
    const abort = () => controller.abort();
    request.signal.addEventListener("abort", abort, { once: true });
    if (request.signal.aborted) abort();
    const timer = setTimeout(abort, PROXY_TIMEOUT_MS);
    try {
      const { body, tooLarge } = await readBoundedRequestBody(
        request,
        controller.signal,
        64 * 1024,
      );
      if (tooLarge)
        return jsonError(413, "Local media registration is too large.");
      if (!body || controller.signal.aborted)
        return jsonError(400, "Local media registration is unavailable.");
      const payload: unknown = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(body),
      );
      if (
        !payload ||
        Array.isArray(payload) ||
        typeof payload !== "object" ||
        Object.keys(payload).length !== 1 ||
        !("sources" in payload) ||
        !Array.isArray(payload.sources) ||
        !payload.sources.every((source) => typeof source === "string")
      )
        return jsonError(400, "Local media registration is invalid.");
      // Recheck the session after the asynchronous body read: logout/replacement
      // during registration must not attach sources to a new identity generation.
      if (!generation || sessionStore.generation(localSession!) !== generation)
        return localBridgeCookieFailure();
      const items = sessionStore.registerMedia(localSession!, payload.sources);
      if (items === "limited")
        return jsonError(
          429,
          "Local media registration limit reached. Reopen the lesson later.",
        );
      if (!items)
        return jsonError(
          400,
          "Local media registration is invalid or expired.",
        );
      return Response.json(
        { items },
        {
          headers: {
            "cache-control": "private, no-store",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
          },
        },
      );
    } catch {
      return jsonError(
        controller.signal.aborted ? 504 : 400,
        "Local media registration is unavailable.",
      );
    } finally {
      clearTimeout(timer);
      request.signal.removeEventListener("abort", abort);
    }
  }
  const isMedia = incomingUrl.pathname.startsWith(
    DEVELOPMENT_MEDIA_LOCATOR_PREFIX,
  );
  const source = isMedia
    ? sessionStore.mediaSource(
        localSession!,
        incomingUrl.pathname.slice(DEVELOPMENT_MEDIA_LOCATOR_PREFIX.length),
      )
    : null;
  if (isMedia && !source)
    return jsonError(
      404,
      "Local media is unavailable or expired. Reopen the lesson.",
    );
  const upstream = isMedia
    ? {
        response: await proxyStagingMedia(
          request,
          target,
          mediaFetcher,
          stagingSession!,
          source!,
        ),
        setCookieHeaders: [],
      }
    : await proxyUpstream(request, target, fetcher, stagingSession);
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
    if (localSession !== null) sessionStore.delete(localSession);
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
  fetcher?: DevApiFetch,
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

  if (
    target.mode === "local" &&
    target.browserOrigin !== undefined &&
    !isAllowedBridgeOrigin(request, target.browserOrigin)
  ) {
    return jsonError(
      403,
      "The managed local API proxy accepts requests only from its exact learner origin.",
    );
  }

  if (target.mode === "staging-authenticated") {
    return proxyAuthenticatedStaging(
      request,
      target,
      fetcher ?? globalThis.fetch.bind(globalThis),
      sessionStore,
      fetcher ?? fetchDevelopmentMediaUpstream,
    );
  }

  if (
    target.mode === "local" &&
    incomingUrl.pathname.startsWith("/v1/media/local-avatar-upload/")
  ) {
    return proxyLocalSandboxAvatarUpload(request);
  }

  if (
    target.mode === "local" &&
    (incomingUrl.pathname.startsWith("/v1/media/playback/") ||
      (environment.AC_DEV_LOCAL_SANDBOX_ENABLED === "true" &&
        incomingUrl.pathname.startsWith("/v1/media/read/")))
  ) {
    return proxyLocalSandboxMedia(request);
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

  const upstreamFetcher =
    fetcher ??
    (target.mode !== "local"
      ? globalThis.fetch.bind(globalThis)
      : target.origin === DEFAULT_LOCAL_API_ORIGIN &&
          target.browserOrigin === LOCAL_SANDBOX_ORIGIN
        ? fetchLocalLearnerWire
        : fetchDevelopmentLocalApiUpstream);
  return (await proxyUpstream(request, target, upstreamFetcher, null)).response;
}
