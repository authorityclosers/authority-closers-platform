const DEFAULT_LOCAL_API_ORIGIN = "http://127.0.0.1:8000";
const STAGING_API_ORIGIN = "https://api-staging.authorityclosers.com";
const PROXY_TIMEOUT_MS = 12_000;
const MAX_CATALOG_SLUG_LENGTH = 120;

// A public catalog preview has no reason to forward browser state or
// arbitrary headers to staging. Origin is intentionally retained so the
// staging API can enforce its own origin policy; all credential and proxy
// metadata is dropped at this boundary.
const STAGING_PREVIEW_REQUEST_HEADERS = new Set([
  "accept",
  "accept-language",
  "origin",
]);

type DevApiEnvironment = Readonly<Record<string, string | undefined>>;

export type DevApiTarget =
  | { mode: "local"; origin: string }
  | { mode: "staging-public-catalog"; origin: typeof STAGING_API_ORIGIN };

export type DevApiFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

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

/**
 * Development has two data modes:
 * - local: the normal local loopback API;
 * - staging-public-catalog: anonymous catalog GETs only.
 */
export function resolveDevApiTarget(
  environment: DevApiEnvironment,
  nodeEnvironment: string | undefined,
): DevApiTarget | null {
  if (nodeEnvironment !== "development") return null;

  const configured =
    [environment.AC_DEV_API_ORIGIN, environment.AC_API_URL]
      .map((value) => value?.trim())
      .find((value): value is string => Boolean(value)) ??
    DEFAULT_LOCAL_API_ORIGIN;
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

function proxyRequestHeaders(
  request: Request,
  mode: DevApiTarget["mode"],
): Headers {
  const headers = new Headers(request.headers);
  for (const header of [
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
  ]) {
    headers.delete(header);
  }
  if (mode === "staging-public-catalog") {
    for (const name of [...headers.keys()]) {
      if (!STAGING_PREVIEW_REQUEST_HEADERS.has(name)) headers.delete(name);
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
  if (mode === "staging-public-catalog") {
    headers.delete("set-cookie");
    headers.delete("location");
    headers.delete("refresh");
    headers.set("cache-control", "private, no-store");
    headers.set("x-ac-dev-data-mode", "staging-public-catalog");
  }
  return headers;
}

function jsonError(status: number, detail: string): Response {
  return Response.json(
    { title: "Development API proxy unavailable", detail },
    { status, headers: { "cache-control": "no-store" } },
  );
}

export async function proxyDevelopmentLearnerApi(
  request: Request,
  fetcher: DevApiFetch = globalThis.fetch.bind(globalThis),
  environment: DevApiEnvironment = process.env,
  nodeEnvironment: string | undefined = process.env.NODE_ENV,
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

  if (target.mode === "staging-public-catalog") {
    if (
      request.method !== "GET" ||
      !isStagingPublicCatalogRequest(incomingUrl)
    ) {
      return jsonError(
        403,
        "Local staging preview permits anonymous published-catalog GETs only. Test protected data and mutations on deployed staging.",
      );
    }
  }

  if (request.signal.aborted) {
    return jsonError(
      504,
      "The development API proxy timed out or was cancelled.",
    );
  }

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
      return jsonError(
        504,
        "The development API proxy timed out or was cancelled.",
      );
    }
    const body =
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer();
    const response = await fetcher(upstreamUrl, {
      method: request.method,
      headers: proxyRequestHeaders(request, target.mode),
      body,
      redirect: "manual",
      signal: controller.signal,
    });
    if (
      target.mode === "staging-public-catalog" &&
      response.status >= 300 &&
      response.status < 400
    ) {
      return jsonError(
        502,
        "The staging catalog returned an unexpected redirect.",
      );
    }
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: proxyResponseHeaders(response, target.mode),
    });
  } catch (error) {
    if (controller.signal.aborted) {
      return jsonError(
        504,
        "The development API proxy timed out or was cancelled.",
      );
    }
    return jsonError(
      502,
      error instanceof Error
        ? `The configured API could not be reached: ${error.message}`
        : "The configured API could not be reached.",
    );
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abort);
  }
}
