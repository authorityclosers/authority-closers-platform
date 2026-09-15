import { randomBytes } from "node:crypto";
import { isIP } from "node:net";
import { resolve } from "node:path";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import http from "node:http";

export const PRODUCTION_UPSTREAM_ORIGIN =
  "https://salesxray.authorityclosers.com";
export const DEFAULT_BROWSER_ORIGIN = "http://salesxray.localhost:3016";
export const DEFAULT_INNER_ORIGIN = "http://127.0.0.1:3116";
export const LOCAL_SESSION_COOKIE = "ac_sales_xray_dev_session";
export const UPSTREAM_SESSION_COOKIE = "__Host-ac_session";
export const UPSTREAM_OAUTH_COOKIE_PREFIX = "__Host-ac_oauth_transaction";
export const MAX_REQUEST_BODY_BYTES = 34 * 1024 ** 2;
export const MAX_AUTH_RESPONSE_BYTES = 1024 ** 2;
export const LOCAL_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;
export const API_REQUEST_TIMEOUT_MS = 30 * 1000;
export const UPLOAD_REQUEST_TIMEOUT_MS = 3 * 60 * 1000;

const LOCAL_SESSION_PATTERN = /^[A-Za-z0-9_-]{43}$/;
const UPSTREAM_SESSION_PATTERN = /^[A-Za-z0-9_-]{43,512}$/;
const UUID =
  "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const SAFE_HEADER_NAMES = new Set([
  "accept",
  "accept-language",
  "content-type",
  "if-match",
  "if-none-match",
  "idempotency-key",
  "range",
]);
const RESPONSE_HEADER_NAMES = [
  "accept-ranges",
  "cache-control",
  "content-disposition",
  "content-length",
  "content-range",
  "content-type",
  "etag",
  "last-modified",
  "vary",
  "www-authenticate",
];
const FORBIDDEN_INCOMING_HEADERS = new Set([
  "authorization",
  "proxy-authorization",
  "x-api-key",
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-proto",
  "forwarded",
]);

function jsonHeaders() {
  return {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    pragma: "no-cache",
    "x-ac-dev-data-mode": "production-live",
    "x-ac-dev-bridge": "loopback-fixed-production-origin",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
  };
}

function writeJson(response, status, body, extraHeaders = {}) {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    ...jsonHeaders(),
    "content-length": Buffer.byteLength(payload),
    ...extraHeaders,
  });
  response.end(payload);
}

function localError(response, status, detail) {
  writeJson(response, status, { detail });
}

function isLoopbackAddress(value) {
  if (!value) return false;
  const normalized = value.startsWith("::ffff:")
    ? value.slice("::ffff:".length)
    : value;
  return normalized === "127.0.0.1" || normalized === "::1";
}

function exactOrigin(value, label) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${label} must be an absolute origin.`);
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  )
    throw new Error(`${label} must not contain credentials, a path, or query.`);
  return parsed;
}

function exactLoopbackOrigin(value, label) {
  const parsed = exactOrigin(value, label);
  if (
    parsed.protocol !== "http:" ||
    !(
      parsed.hostname === "127.0.0.1" ||
      parsed.hostname === "localhost" ||
      parsed.hostname === "::1"
    )
  )
    throw new Error(`${label} must be an HTTP loopback origin.`);
  return parsed;
}

function exactBrowserOrigin(value) {
  const parsed = exactOrigin(value, "browserOrigin");
  if (
    parsed.protocol !== "http:" ||
    !(
      parsed.hostname === "localhost" ||
      parsed.hostname.endsWith(".localhost") ||
      parsed.hostname === "127.0.0.1"
    )
  )
    throw new Error("browserOrigin must be an HTTP localhost origin.");
  return parsed;
}

export function validateBridgeConfig({
  browserOrigin = DEFAULT_BROWSER_ORIGIN,
  innerOrigin = DEFAULT_INNER_ORIGIN,
  upstreamOrigin = PRODUCTION_UPSTREAM_ORIGIN,
} = {}) {
  const browser = exactBrowserOrigin(browserOrigin);
  const inner = exactLoopbackOrigin(innerOrigin, "innerOrigin");
  const upstream = exactOrigin(upstreamOrigin, "upstreamOrigin");
  if (upstream.origin !== PRODUCTION_UPSTREAM_ORIGIN)
    throw new Error(
      `upstreamOrigin is pinned to ${PRODUCTION_UPSTREAM_ORIGIN}; arbitrary proxy destinations are disabled.`,
    );
  if (isIP(browser.hostname) && browser.hostname !== "127.0.0.1")
    throw new Error("browserOrigin must use localhost or 127.0.0.1.");
  return {
    browserOrigin: browser.origin,
    browserHost: browser.host,
    innerOrigin: inner.origin,
    upstreamOrigin: upstream.origin,
  };
}

function parseCookieHeader(header) {
  const cookies = new Map();
  if (!header) return cookies;
  for (const part of header.split(";")) {
    const separator = part.indexOf("=");
    if (separator <= 0) continue;
    const name = part.slice(0, separator).trim();
    const value = part.slice(separator + 1).trim();
    if (!name || cookies.has(name)) {
      if (cookies.has(name)) cookies.set(name, null);
      continue;
    }
    cookies.set(name, value);
  }
  return cookies;
}

export function readLocalSessionHandle(header) {
  const cookies = parseCookieHeader(header);
  const value = cookies.get(LOCAL_SESSION_COOKIE);
  if (value === null) return { kind: "invalid" };
  if (value === undefined) return { kind: "missing" };
  if (!LOCAL_SESSION_PATTERN.test(value)) return { kind: "invalid" };
  return { kind: "present", handle: value };
}

function containsCredentialCookie(header) {
  const cookies = parseCookieHeader(header);
  for (const name of cookies.keys()) {
    if (
      name === UPSTREAM_SESSION_COOKIE ||
      name === "ac_session" ||
      name === "__Host-ac_xray_guest" ||
      name === "ac_xray_guest" ||
      name === "__Host-ac_oauth_transaction" ||
      name === "ac_oauth_transaction" ||
      name.startsWith(UPSTREAM_OAUTH_COOKIE_PREFIX + ".")
    )
      return true;
  }
  return false;
}

function sessionCookie(handle) {
  return `${LOCAL_SESSION_COOKIE}=${handle}; HttpOnly; Path=/; SameSite=Lax; Max-Age=${LOCAL_SESSION_MAX_AGE_SECONDS}`;
}

function clearSessionCookie() {
  return `${LOCAL_SESSION_COOKIE}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0`;
}

export class EphemeralSessionStore {
  #sessions = new Map();

  #prune(now = Date.now()) {
    for (const [handle, entry] of this.#sessions) {
      if (entry.expiresAt <= now) this.#sessions.delete(handle);
    }
    while (this.#sessions.size > 16)
      this.#sessions.delete(this.#sessions.keys().next().value);
  }

  create(upstreamValue) {
    if (!UPSTREAM_SESSION_PATTERN.test(upstreamValue))
      throw new Error("The upstream session cookie is malformed.");
    this.#prune();
    const handle = randomBytes(32).toString("base64url");
    this.#sessions.set(handle, {
      upstreamValue,
      expiresAt: Date.now() + LOCAL_SESSION_MAX_AGE_SECONDS * 1000,
    });
    return handle;
  }

  get(handle) {
    this.#prune();
    const entry = this.#sessions.get(handle);
    if (!entry) return null;
    entry.expiresAt = Date.now() + LOCAL_SESSION_MAX_AGE_SECONDS * 1000;
    return entry.upstreamValue;
  }

  replace(handle, upstreamValue) {
    if (!UPSTREAM_SESSION_PATTERN.test(upstreamValue)) return false;
    if (!this.#sessions.has(handle)) return false;
    this.#sessions.set(handle, {
      upstreamValue,
      expiresAt: Date.now() + LOCAL_SESSION_MAX_AGE_SECONDS * 1000,
    });
    return true;
  }

  delete(handle) {
    this.#sessions.delete(handle);
  }

  clear() {
    this.#sessions.clear();
  }
}

export function resolveApiRoute(method, pathname, search = "") {
  const verb = method.toUpperCase();
  const exact = (allowedVerb, path) => verb === allowedVerb && pathname === path;
  const noQuery = search.length === 0;
  const api = (auth = "session", requiresSession = auth === "session") => ({
    kind: "api",
    auth,
    requiresSession,
  });
  const safeCursorQuery = () => {
    const params = new URLSearchParams(search);
    return (
      [...params.keys()].every((key) => key === "before") &&
      (params.has("before") ? /^[A-Za-z0-9_-]{1,256}$/.test(params.get("before")) : true)
    );
  };

  if (
    exact("GET", "/v1/me") ||
    exact("GET", "/v1/me/workspaces") ||
    exact("GET", "/v1/context") ||
    exact("POST", "/v1/context") ||
    exact("POST", "/v1/auth/password/login") ||
    exact("POST", "/v1/auth/logout")
  ) {
    if (!noQuery) return { kind: "blocked" };
    return pathname === "/v1/auth/password/login"
      ? api("login", false)
      : api();
  }

  if (
    pathname === "/v1/auth/google/start" ||
    pathname === "/v1/auth/google/callback"
  )
    return { kind: "oauth" };

  if (exact("GET", "/v1/conversation/workspace") && noQuery) return api();
  if (
    (exact("GET", "/v1/conversation/capabilities") ||
      exact("GET", "/v1/conversation/example")) &&
    noQuery
  )
    return api("public", false);

  const acquisitionExact = {
    "/v1/conversation/acquisition/entry": new Set(["GET"]),
    "/v1/conversation/acquisition/upload-policy": new Set(["GET"]),
    "/v1/conversation/acquisition/session": new Set(["GET", "POST"]),
    "/v1/conversation/acquisition/availability": new Set(["GET"]),
    "/v1/conversation/acquisition/claim": new Set(["POST"]),
  };
  if (acquisitionExact[pathname]?.has(verb) && noQuery) return api();

  if (pathname === "/v1/conversation/acquisition/submissions") {
    if (verb === "GET" && safeCursorQuery()) return api();
    return { kind: "blocked" };
  }

  const submission = new RegExp(
    `^/v1/conversation/acquisition/submissions/(${UUID})(?:/(report|transcript|source|waveform|measurements|plan|plan/quote|report\\.docx))?$`,
  ).exec(pathname);
  if (submission) {
    const suffix = submission[2];
    if (!suffix && (verb === "GET" || verb === "DELETE") && noQuery)
      return api();
    if (
      suffix === "source" &&
      (verb === "GET" || verb === "PUT") &&
      noQuery
    )
      return api();
    if (
      ["report", "transcript", "waveform", "measurements", "plan", "report.docx"].includes(suffix) &&
      verb === "GET" &&
      noQuery
    )
      return api();
    if (suffix === "plan" && verb === "POST" && noQuery)
      return api();
    if (suffix === "plan/quote" && verb === "POST" && noQuery)
      return api();
    return { kind: "blocked" };
  }

  if (pathname === "/v1/conversation/intake/quote" && verb === "POST" && noQuery)
    return api();
  if (pathname === "/v1/conversation/recordings" && verb === "GET" && noQuery)
    return api();

  const recording = new RegExp(
    `^/v1/conversation/recordings/(${UUID})(?:/(transcript|source|measurements|plan|plan/quote))?$`,
  ).exec(pathname);
  if (recording) {
    const suffix = recording[2];
    if (!suffix && (verb === "GET" || verb === "DELETE") && noQuery)
      return api();
    if (
      suffix === "source" &&
      (verb === "GET" || verb === "PUT") &&
      noQuery
    )
      return api();
    if (
      ["transcript", "measurements", "plan"].includes(suffix) &&
      verb === "GET" &&
      noQuery
    )
      return api();
    if (suffix === "plan" && verb === "POST" && noQuery)
      return api();
    if (suffix === "plan/quote" && verb === "POST" && noQuery)
      return api();
    return { kind: "blocked" };
  }

  if (pathname === "/v1/conversation/runs" && verb === "POST" && noQuery)
    return api();
  const run = new RegExp(`^/v1/conversation/runs/(${UUID})(?:/report)?$`).exec(
    pathname,
  );
  if (run && verb === "GET" && noQuery) return api();

  return { kind: "blocked" };
}

function getSetCookieHeaders(headers) {
  if (typeof headers.getSetCookie === "function") return headers.getSetCookie();
  const combined = headers.get("set-cookie");
  return combined ? [combined] : [];
}

function parseSetCookie(header) {
  const separator = header.indexOf(";");
  const pair = separator === -1 ? header : header.slice(0, separator);
  const equals = pair.indexOf("=");
  if (equals <= 0) return null;
  const name = pair.slice(0, equals).trim();
  const value = pair.slice(equals + 1).trim();
  const attributes = new Map();
  for (const rawAttribute of header.slice(separator + 1).split(";")) {
    const attribute = rawAttribute.trim();
    if (!attribute) continue;
    const attributeSeparator = attribute.indexOf("=");
    const key = (attributeSeparator === -1
      ? attribute
      : attribute.slice(0, attributeSeparator)
    ).toLowerCase();
    const attributeValue =
      attributeSeparator === -1
        ? true
        : attribute.slice(attributeSeparator + 1).trim();
    attributes.set(key, attributeValue);
  }
  return { name, value, attributes };
}

export function readUpstreamSessionCookie(headers) {
  for (const raw of getSetCookieHeaders(headers)) {
    const parsed = parseSetCookie(raw);
    if (!parsed || parsed.name !== UPSTREAM_SESSION_COOKIE) continue;
    if (
      !UPSTREAM_SESSION_PATTERN.test(parsed.value) ||
      parsed.attributes.get("secure") !== true ||
      parsed.attributes.get("httponly") !== true ||
      parsed.attributes.get("path") !== "/" ||
      parsed.attributes.has("domain")
    )
      return { kind: "invalid" };
    return { kind: "present", value: parsed.value };
  }
  return { kind: "missing" };
}

function hasCredentialSetCookie(headers) {
  return getSetCookieHeaders(headers).some((raw) => {
    const parsed = parseSetCookie(raw);
    return (
      parsed &&
      (parsed.name === UPSTREAM_SESSION_COOKIE ||
        parsed.name.startsWith(UPSTREAM_OAUTH_COOKIE_PREFIX))
    );
  });
}

function upstreamRequestHeaders(request, upstreamCookie) {
  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    if (!value || !SAFE_HEADER_NAMES.has(name.toLowerCase())) continue;
    headers.set(name, Array.isArray(value) ? value.join(", ") : value);
  }
  headers.set("origin", PRODUCTION_UPSTREAM_ORIGIN);
  headers.set("accept-encoding", "identity");
  headers.set("cache-control", "no-store");
  if (upstreamCookie) headers.set("cookie", `${UPSTREAM_SESSION_COOKIE}=${upstreamCookie}`);
  return headers;
}

function localRequestHasValidOrigin(request, browserOrigin, browserHost) {
  if (request.headers.host !== browserHost) return false;
  if (request.headers.origin && request.headers.origin !== browserOrigin) return false;
  if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method))
    return request.headers.origin === browserOrigin;
  return true;
}

function rejectCredentialHeaders(request) {
  return Object.keys(request.headers).some((name) =>
    FORBIDDEN_INCOMING_HEADERS.has(name.toLowerCase()),
  );
}

function rejectUpgrade(socket, status = 403) {
  socket.end(
    `HTTP/1.1 ${status} ${status === 403 ? "Forbidden" : "Bad Request"}\r\n` +
      "Connection: close\r\nContent-Length: 0\r\n\r\n",
  );
}

function proxyInnerUpgrade(request, socket, head, config) {
  if (
    !isLoopbackAddress(request.socket.remoteAddress) ||
    request.headers.host !== config.browserHost ||
    (request.headers.origin && request.headers.origin !== config.browserOrigin) ||
    rejectCredentialHeaders(request) ||
    !request.url ||
    !request.url.startsWith("/") ||
    request.url.startsWith("//")
  ) {
    rejectUpgrade(socket);
    return;
  }
  const target = new URL(request.url, config.innerOrigin);
  if (target.pathname !== "/_next/webpack-hmr") {
    rejectUpgrade(socket, 400);
    return;
  }
  const headers = {
    host: target.host,
    connection: "Upgrade",
    upgrade: "websocket",
  };
  for (const name of [
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-protocol",
    "sec-websocket-extensions",
  ]) {
    const value = request.headers[name];
    if (value) headers[name] = Array.isArray(value) ? value.join(", ") : value;
  }
  const upstreamRequest = http.request({
    hostname: target.hostname,
    port: target.port || 80,
    path: target.pathname + target.search,
    method: "GET",
    headers,
    agent: false,
  });
  const close = () => {
    if (!socket.destroyed) socket.destroy();
  };
  upstreamRequest.once("upgrade", (upstreamResponse, upstreamSocket, upstreamHead) => {
    if (socket.destroyed) {
      upstreamSocket.destroy();
      return;
    }
    const statusLine = `HTTP/1.1 ${upstreamResponse.statusCode} ${upstreamResponse.statusMessage ?? "Switching Protocols"}\r\n`;
    socket.write(statusLine);
    for (const [name, value] of Object.entries(upstreamResponse.headers)) {
      if (name === "set-cookie" || value === undefined) continue;
      const values = Array.isArray(value) ? value : [value];
      for (const item of values) socket.write(`${name}: ${item}\r\n`);
    }
    socket.write("\r\n");
    if (head.length) upstreamSocket.write(head);
    if (upstreamHead.length) socket.write(upstreamHead);
    upstreamSocket.pipe(socket);
    socket.pipe(upstreamSocket);
    socket.once("close", () => upstreamSocket.destroy());
    upstreamSocket.once("close", () => socket.destroy());
  });
  upstreamRequest.once("response", () => close());
  upstreamRequest.once("error", close);
  upstreamRequest.end();
}

async function readBody(request, maxBytes) {
  if (["GET", "HEAD"].includes(request.method)) return undefined;
  const declared = request.headers["content-length"];
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > maxBytes))
    throw Object.assign(new Error("Request body is too large."), { status: 413 });
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    total += chunk.length;
    if (total > maxBytes)
      throw Object.assign(new Error("Request body is too large."), { status: 413 });
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function responseHeaders(
  upstream,
  { localCookie, clearLocalCookie, allowLocationOrigin, rewriteLocationOrigin } = {},
) {
  const headers = {};
  for (const name of RESPONSE_HEADER_NAMES) {
    const value = upstream.headers.get(name);
    if (value) headers[name] = value;
  }
  headers["cache-control"] = "no-store";
  headers["referrer-policy"] = "no-referrer";
  headers["x-content-type-options"] = "nosniff";
  headers["x-frame-options"] = "DENY";
  headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()";
  const contentEncoding = upstream.headers.get("content-encoding");
  if (contentEncoding && contentEncoding.toLowerCase() !== "identity")
    delete headers["content-length"];
  if (allowLocationOrigin && rewriteLocationOrigin) {
    const location = upstream.headers.get("location");
    if (location) {
      try {
        const parsed = new URL(location, allowLocationOrigin);
        if (parsed.origin === allowLocationOrigin)
          headers.location = `${rewriteLocationOrigin}${parsed.pathname}${parsed.search}${parsed.hash}`;
      } catch {
        // Do not expose an invalid or cross-origin local redirect.
      }
    }
  }
  headers["x-ac-dev-data-mode"] = "production-live";
  headers["x-ac-dev-bridge"] = "loopback-fixed-production-origin";
  if (localCookie) headers["set-cookie"] = sessionCookie(localCookie);
  if (clearLocalCookie) headers["set-cookie"] = clearSessionCookie();
  return headers;
}

function sendUpstreamResponse(response, upstream, options = {}) {
  const headers = responseHeaders(upstream, options);
  response.writeHead(upstream.status, headers);
  if (!upstream.body || options.head) {
    response.end();
    return;
  }
  Readable.fromWeb(upstream.body).pipe(response);
}

function canonicalOAuthRedirect(pathname, search) {
  const target = new URL(pathname, PRODUCTION_UPSTREAM_ORIGIN);
  const incoming = new URLSearchParams(search);
  const keys =
    pathname.endsWith("/start")
      ? ["action", "surface", "return_path"]
      : ["code", "state", "error", "error_description"];
  for (const key of keys) {
    const value = incoming.get(key);
    if (value !== null && value.length <= 4096) target.searchParams.set(key, value);
  }
  if (pathname.endsWith("/start")) {
    target.searchParams.set("surface", "sales_xray");
    target.searchParams.set("return_path", "/");
  }
  return target.toString();
}

async function proxyInner(request, response, innerOrigin, fetcher) {
  if (!["GET", "HEAD"].includes(request.method)) {
    localError(response, 405, "Only browser page and asset reads are available on this bridge.");
    return;
  }
  if (!request.url || !request.url.startsWith("/") || request.url.startsWith("//")) {
    localError(response, 400, "The local UI request target must be a relative path.");
    return;
  }
  const target = new URL(request.url, innerOrigin);
  const headers = new Headers();
  if (request.headers.accept) headers.set("accept", request.headers.accept);
  if (request.headers["accept-language"])
    headers.set("accept-language", request.headers["accept-language"]);
  headers.set("accept-encoding", "identity");
  let upstream;
  try {
    upstream = await fetcher(target, {
      method: request.method,
      headers,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(API_REQUEST_TIMEOUT_MS),
    });
  } catch {
    localError(response, 502, "The local Sales Xray UI is not running.");
    return;
  }
  sendUpstreamResponse(response, upstream, {
    head: request.method === "HEAD",
    allowLocationOrigin: innerOrigin,
    rewriteLocationOrigin: new URL(request.headers.host ? `http://${request.headers.host}` : DEFAULT_BROWSER_ORIGIN).origin,
  });
}

export function createSalesXrayProductionBridge({
  browserOrigin = DEFAULT_BROWSER_ORIGIN,
  innerOrigin = DEFAULT_INNER_ORIGIN,
  upstreamOrigin = PRODUCTION_UPSTREAM_ORIGIN,
  fetcher = globalThis.fetch,
  sessionStore = new EphemeralSessionStore(),
} = {}) {
  const config = validateBridgeConfig({ browserOrigin, innerOrigin, upstreamOrigin });
  if (typeof fetcher !== "function") throw new Error("A fetch implementation is required.");

  const handle = async (request, response) => {
    if (!isLoopbackAddress(request.socket.remoteAddress)) {
      localError(response, 403, "The Sales Xray development bridge is loopback-only.");
      return;
    }
    if (rejectCredentialHeaders(request)) {
      localError(response, 400, "Browser credentials must not be supplied to the local bridge.");
      return;
    }
    if (!localRequestHasValidOrigin(request, config.browserOrigin, config.browserHost)) {
      localError(response, 403, "The request origin is not the configured local Sales Xray origin.");
      return;
    }
    if (containsCredentialCookie(request.headers.cookie)) {
      localError(response, 400, "Production cookies are never accepted from the browser.");
      return;
    }

    if (!request.url || !request.url.startsWith("/") || request.url.startsWith("//")) {
      localError(response, 400, "The local bridge request target must be a relative path.");
      return;
    }
    const incoming = new URL(request.url, config.browserOrigin);
    if (request.method === "OPTIONS") {
      response.writeHead(204, {
        ...jsonHeaders(),
        "access-control-allow-origin": config.browserOrigin,
        "access-control-allow-methods": "GET,HEAD,POST,PUT,DELETE,OPTIONS",
        "access-control-allow-headers": "content-type,accept,if-match,idempotency-key,range",
      });
      response.end();
      return;
    }
    if (incoming.pathname === "/health") {
      writeJson(response, 200, {
        status: "ok",
        service: "sales-xray-local-production-bridge",
        mode: "development-only",
        data_mode: "production-live",
        upstream_origin: config.upstreamOrigin,
        session: "ephemeral-http-only-local-handle",
        provider_processing: "no automatic jobs",
      });
      return;
    }

    if (!incoming.pathname.startsWith("/v1/")) {
      await proxyInner(request, response, config.innerOrigin, fetcher);
      return;
    }

    const route = resolveApiRoute(request.method, incoming.pathname, incoming.search);
    if (route.kind === "oauth") {
      response.writeHead(303, {
        location: canonicalOAuthRedirect(incoming.pathname, incoming.search),
        ...jsonHeaders(),
      });
      response.end();
      return;
    }
    if (route.kind !== "api") {
      localError(response, 404, "That Sales Xray API route is not enabled by the local bridge.");
      return;
    }

    const localHandleResult = readLocalSessionHandle(request.headers.cookie);
    if (localHandleResult.kind === "invalid") {
      localError(response, 400, "The local Sales Xray session handle is invalid.");
      return;
    }
    const localHandle =
      localHandleResult.kind === "present" ? localHandleResult.handle : null;
    const upstreamCookie = localHandle ? sessionStore.get(localHandle) : null;
    if (localHandle && !upstreamCookie) {
      response.writeHead(401, {
        ...jsonHeaders(),
        "set-cookie": clearSessionCookie(),
      });
      response.end(JSON.stringify({ detail: "Your local Sales Xray session expired." }));
      return;
    }
    if (route.requiresSession && !upstreamCookie) {
      localError(response, 401, "Sign in to this local Sales Xray workspace first.");
      return;
    }
    let body;
    try {
      body = await readBody(request, MAX_REQUEST_BODY_BYTES);
    } catch (error) {
      localError(response, error.status === 413 ? 413 : 400, error.message);
      return;
    }

    const target = new URL(incoming.pathname + incoming.search, config.upstreamOrigin);
    let upstream;
    try {
      upstream = await fetcher(target, {
        method: request.method,
        headers: upstreamRequestHeaders(request, route.auth === "login" ? null : upstreamCookie),
        body,
        redirect: "manual",
        credentials: "omit",
        cache: "no-store",
        signal: AbortSignal.timeout(
          request.method === "PUT" ? UPLOAD_REQUEST_TIMEOUT_MS : API_REQUEST_TIMEOUT_MS,
        ),
      });
    } catch {
      localError(response, 502, "The production Sales Xray service could not be reached.");
      return;
    }

    const loginCookie = route.auth === "login" ? readUpstreamSessionCookie(upstream.headers) : null;
    if (route.auth === "login" && loginCookie?.kind === "invalid") {
      localError(response, 502, "Production login returned an invalid session cookie.");
      return;
    }
    if (route.auth === "login" && upstream.ok && loginCookie?.kind !== "present") {
      localError(response, 502, "Production login did not return a session cookie.");
      return;
    }
    if (hasCredentialSetCookie(upstream.headers) && route.auth !== "login") {
      const refreshed = readUpstreamSessionCookie(upstream.headers);
      if (refreshed.kind === "present" && localHandle)
        sessionStore.replace(localHandle, refreshed.value);
    }

    if (route.auth === "login") {
      const raw = Buffer.from(await upstream.arrayBuffer());
      if (raw.length > MAX_AUTH_RESPONSE_BYTES || /(?:access|refresh|id)?[_-]?token|authorization\s*:/i.test(raw.toString("utf8"))) {
        localError(response, 502, "Production login returned an unsupported credential response.");
        return;
      }
      const headers = responseHeaders(upstream, {
        localCookie:
          upstream.ok && loginCookie?.kind === "present"
            ? sessionStore.create(loginCookie.value)
            : undefined,
      });
      delete headers["content-length"];
      headers["content-length"] = raw.length;
      response.writeHead(upstream.status, headers);
      response.end(raw);
      return;
    }

    if (route.auth === "session" && upstream.status === 401 && localHandle) {
      sessionStore.delete(localHandle);
      sendUpstreamResponse(response, upstream, {
        clearLocalCookie: true,
        head: request.method === "HEAD",
      });
      return;
    }
    if (request.method === "POST" && incoming.pathname === "/v1/auth/logout" && localHandle) {
      sessionStore.delete(localHandle);
      sendUpstreamResponse(response, upstream, {
        clearLocalCookie: true,
        head: request.method === "HEAD",
      });
      return;
    }
    sendUpstreamResponse(response, upstream, { head: request.method === "HEAD" });
  };

  return { config, handle, sessionStore };
}

export function createServer(options = {}) {
  const bridge = createSalesXrayProductionBridge(options);
  const server = http.createServer((request, response) => {
    bridge.handle(request, response).catch(() => {
      if (!response.headersSent) localError(response, 500, "The local Sales Xray bridge failed safely.");
      else response.destroy();
    });
  });
  server.on("upgrade", (request, socket, head) =>
    proxyInnerUpgrade(request, socket, head, bridge.config),
  );
  return { server, bridge };
}

function parseCli(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) throw new Error(`Unexpected argument '${item}'.`);
    const key = item.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for --${key}.`);
    values.set(key, value);
    index += 1;
  }
  return values;
}

if (
  process.argv[1] &&
  resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1])
) {
  try {
    const args = parseCli(process.argv.slice(2));
    const browserOrigin = args.get("browser-origin") ?? DEFAULT_BROWSER_ORIGIN;
    const innerOrigin = args.get("inner-origin") ?? DEFAULT_INNER_ORIGIN;
    const browserPort = new URL(browserOrigin).port || "3016";
    const port = Number(args.get("port") ?? browserPort);
    if (!Number.isInteger(port) || port < 1024 || port > 65535)
      throw new Error("port must be an integer between 1024 and 65535.");
    const { server, bridge } = createServer({ browserOrigin, innerOrigin });
    server.listen(port, "127.0.0.1", () => {
      process.stdout.write(
        `Sales Xray local bridge listening on ${bridge.config.browserOrigin}; production origin is pinned.\n`,
      );
    });
    const shutdown = () => {
      bridge.sessionStore.clear();
      server.close(() => process.exit(0));
    };
    process.once("SIGINT", shutdown);
    process.once("SIGTERM", shutdown);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : "Bridge startup failed."}\n`);
    process.exitCode = 1;
  }
}
