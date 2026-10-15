import { request as httpRequest } from "node:http";

/**
 * Server-side reads for console pages. A page awaits its reads together and
 * renders whole; a failed read becomes a message for that panel, never a
 * thrown error (Pulse rule: the API helper never throws).
 *
 * Transport mirrors the reviewer identity read (reviewer-server-auth.ts): the
 * only destination is the trusted internal API origin, the only credential
 * forwarded is the operator's own session cookie, and Host is the canonical
 * Admin host because the API admits admin routes by that host. node:http is
 * used because fetch rewrites Host. The API re-checks every permission; this
 * helper widens nothing.
 */

export type ApiResult<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; error: string; status: number };

const ADMIN_HOST_BY_API_HOST: Readonly<Record<string, string>> = {
  "api.production.ac.internal.invalid": "admin.authorityclosers.com",
  "api.staging.ac.internal.invalid": "admin-staging.authorityclosers.com",
  "api.development.ac.internal.invalid": "admin-dev.authorityclosers.com",
};
const SESSION_COOKIE_NAME = "__Host-ac_session";
/** The development API's session cookie name (settings.session_cookie_name default). */
const DEV_SESSION_COOKIE_NAME = "ac_session";
/** The dev live API's own session cookie (AC_SESSION_COOKIE_NAME on :8101). */
const DEV_LIVE_SESSION_COOKIE_NAME = "__Host-ac_live_session";
const OPAQUE_SESSION_PATTERN = /^[A-Za-z0-9_-]{43,512}$/;
const SAFE_PATH = /^\/v1\/[A-Za-z0-9\-._~/%]*(\?[A-Za-z0-9\-._~%&=+,:]*)?$/;
const READ_TIMEOUT_MS = 15_000;
const DEFAULT_LIMIT_BYTES = 8 * 1024 * 1024;

export const MESSAGES = {
  notConnected:
    "The admin data service isn't connected in this preview. Pages show their layout only.",
  signedOut: "Your session has ended. Sign in again to load this.",
  forbidden: "Your account can't open this. Ask an owner if you need it.",
  notFound: "Nothing was found here. It may have been deleted.",
  reconnecting: "The data service is reconnecting. Try again in a moment.",
  unreadable:
    "The data service sent an answer this screen doesn't understand yet.",
} as const;

type Transport = {
  origin: URL;
  adminHost: string;
  cookieNames: readonly string[];
};

const DEV_ADMIN_HOSTS = new Set(["admin-dev.authorityclosers.com"]);
const LOOPBACK = new Set(["127.0.0.1", "localhost"]);

/**
 * Development only (next dev behind admin-dev): read through the local dev
 * edge, which routes /v1/* to whichever API the dev environment uses, as the
 * admin-dev host. Never active in a production build.
 */
export function devEdgeTransport(
  env: Readonly<Record<string, string | undefined>> = process.env,
): Transport | null {
  if (env.NODE_ENV === "production") return null;
  const host = env.AC_ADMIN_DEV_HOST ?? "";
  if (!DEV_ADMIN_HOSTS.has(host)) return null;
  try {
    const origin = new URL(env.AC_ADMIN_DEV_EDGE_ORIGIN ?? "");
    if (
      origin.protocol !== "http:" ||
      !LOOPBACK.has(origin.hostname) ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.username ||
      origin.password
    )
      return null;
    return {
      origin,
      adminHost: host,
      // admin-dev's /v1/* goes to the dev live API, so its own sign-in wins.
      cookieNames: [
        DEV_LIVE_SESSION_COOKIE_NAME,
        SESSION_COOKIE_NAME,
        DEV_SESSION_COOKIE_NAME,
      ],
    };
  } catch {
    return null;
  }
}

export function internalTransport(
  env: Readonly<Record<string, string | undefined>> = process.env,
): Transport | null {
  const apiHost = env.AC_INTERNAL_API_HOST ?? "";
  const adminHost = ADMIN_HOST_BY_API_HOST[apiHost];
  const approved = `http://${apiHost}:8000`;
  if (adminHost && env.AC_INTERNAL_API_URL === approved)
    return {
      origin: new URL(approved),
      adminHost,
      cookieNames: [SESSION_COOKIE_NAME],
    };
  return devEdgeTransport(env);
}

export function sessionCookieFrom(
  cookies: readonly { name: string; value: string }[],
  names: readonly string[] = [SESSION_COOKIE_NAME],
): string | null {
  for (const name of names) {
    const values = cookies
      .filter((cookie) => cookie.name === name)
      .map((cookie) => cookie.value);
    if (values.length === 0) continue;
    if (values.length !== 1) return null;
    const value = values[0] ?? "";
    return OPAQUE_SESSION_PATTERN.test(value) ? `${name}=${value}` : null;
  }
  return null;
}

export function messageForStatus(status: number): string {
  if (status === 401) return MESSAGES.signedOut;
  if (status === 403) return MESSAGES.forbidden;
  if (status === 404) return MESSAGES.notFound;
  return MESSAGES.reconnecting;
}

type RawResponse = { status: number; body: Buffer };

function getOnce(
  url: URL,
  adminHost: string,
  cookie: string,
  limitBytes: number,
): Promise<RawResponse> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };
    const request = httpRequest(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port || "80",
        path: `${url.pathname}${url.search}`,
        method: "GET",
        headers: { accept: "application/json", cookie, host: adminHost },
        timeout: READ_TIMEOUT_MS,
        signal: AbortSignal.timeout(READ_TIMEOUT_MS),
      },
      (response) => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on("data", (chunk: Buffer | string) => {
          const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          size += value.length;
          if (size > limitBytes) {
            response.destroy();
            done(() => reject(new Error("response too large")));
            return;
          }
          chunks.push(value);
        });
        response.on("end", () =>
          done(() =>
            resolve({
              status: response.statusCode ?? 500,
              body: Buffer.concat(chunks),
            }),
          ),
        );
        response.on("error", (error) => done(() => reject(error)));
      },
    );
    request.once("timeout", () => request.destroy(new Error("timed out")));
    request.once("error", (error) => done(() => reject(error)));
    request.end();
  });
}

/** The request's cookies. Never wrapped in try: Next uses this call to render per request. */
async function requestCookies(): Promise<{ name: string; value: string }[]> {
  const { cookies } = await import("next/headers");
  return (await cookies()).getAll();
}

/**
 * GET one admin API path on behalf of the signed-in operator. `normalize`
 * turns the raw JSON into the screen's shape with defaults for missing
 * fields; if it throws, the panel says the answer was unreadable.
 */
export async function adminRead<T>(
  path: string,
  normalize: (raw: unknown) => T,
  {
    limitBytes = DEFAULT_LIMIT_BYTES,
    env = process.env,
    cookies,
    get = getOnce,
  }: {
    limitBytes?: number;
    env?: Readonly<Record<string, string | undefined>>;
    cookies?: readonly { name: string; value: string }[];
    get?: typeof getOnce;
  } = {},
): Promise<ApiResult<T>> {
  if (!SAFE_PATH.test(path) || path.includes("..") || path.includes("//"))
    return { ok: false, status: 400, error: MESSAGES.unreadable };
  const transport = internalTransport(env);
  if (!transport)
    return { ok: false, status: 503, error: MESSAGES.notConnected };
  const cookie = sessionCookieFrom(
    cookies ?? (await requestCookies()),
    transport.cookieNames,
  );
  if (!cookie) return { ok: false, status: 401, error: MESSAGES.signedOut };
  let raw: RawResponse;
  try {
    raw = await get(
      new URL(path, transport.origin),
      transport.adminHost,
      cookie,
      limitBytes,
    );
  } catch {
    return { ok: false, status: 503, error: MESSAGES.reconnecting };
  }
  if (raw.status !== 200)
    return {
      ok: false,
      status: raw.status,
      error: messageForStatus(raw.status),
    };
  try {
    return {
      ok: true,
      status: 200,
      data: normalize(JSON.parse(raw.body.toString("utf-8"))),
    };
  } catch {
    return { ok: false, status: 502, error: MESSAGES.unreadable };
  }
}

export { read } from "./read";
