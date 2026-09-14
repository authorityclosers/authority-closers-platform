import { request as httpRequest } from "node:http";
import { z } from "zod";

const identity = z.object({
  person_id: z
    .string()
    .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/),
  email: z.string().email().max(320),
  display_name: z.string().nullable(),
  expires_at_epoch: z.number().int().positive(),
});

const TRUSTED_INTERNAL_API_HOSTS = new Set([
  "api.production.ac.internal.invalid",
  "api.staging.ac.internal.invalid",
]);
const TRUSTED_ADMIN_APP_ORIGINS = new Set([
  "https://admin.authorityclosers.com",
  "https://admin-staging.authorityclosers.com",
]);
const OPAQUE_SESSION_PATTERN = /^[A-Za-z0-9_-]{43,512}$/;
const REVIEWER_SERVER_REQUEST_TIMEOUT_MS = 3_000;
const REVIEWER_SERVER_RESPONSE_LIMIT_BYTES = 16 * 1024;

function configuredAdminHost(
  rawAdminAppUrl: string | undefined,
): string | null {
  if (!rawAdminAppUrl) return null;
  try {
    const parsed = new URL(rawAdminAppUrl);
    if (
      !TRUSTED_ADMIN_APP_ORIGINS.has(parsed.origin) ||
      parsed.pathname !== "/" ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash
    )
      return null;
    return parsed.host;
  } catch {
    return null;
  }
}

function reviewerCookie(
  rawCookieHeader: string | null,
  production: boolean,
): string | null {
  if (!rawCookieHeader) return null;
  const expected = production
    ? "__Host-ac_reviewer_session"
    : "ac_reviewer_session";
  const values = rawCookieHeader.split(";").flatMap((segment) => {
    const separator = segment.indexOf("=");
    if (separator < 1 || segment.slice(0, separator).trim() !== expected)
      return [];
    const value = segment.slice(separator + 1).trim();
    return OPAQUE_SESSION_PATTERN.test(value) ? [value] : [];
  });
  return values.length === 1 ? `${expected}=${values[0]}` : null;
}

function reviewerMeUrl(
  rawBaseUrl: string | undefined,
  apiHost: string | undefined,
): URL | null {
  if (!rawBaseUrl || !apiHost || !TRUSTED_INTERNAL_API_HOSTS.has(apiHost))
    return null;
  const approvedOrigin = `http://${apiHost}:8000`;
  if (rawBaseUrl !== approvedOrigin) return null;
  try {
    const parsed = new URL(rawBaseUrl);
    if (
      parsed.protocol !== "http:" ||
      parsed.hostname !== apiHost ||
      parsed.port !== "8000" ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash ||
      parsed.pathname !== "/"
    )
      return null;
    return new URL("/v1/reviewer/me", parsed);
  } catch {
    return null;
  }
}

/**
 * Read the reviewer identity over the trusted internal transport.
 *
 * The URL and host are validated by resolveReviewerServerContext before this
 * helper is called. This deliberately uses node:http instead of fetch: Node's
 * fetch implementation rewrites Host to the internal loopback destination,
 * while the API authorizes reviewer traffic by the canonical Admin host.
 */
export function requestReviewerServerIdentity(
  url: URL,
  adminHost: string,
  cookie: string,
): Promise<Response> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const settleReject = (error: unknown) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    const settleResolve = (response: Response) => {
      if (settled) return;
      settled = true;
      resolve(response);
    };

    const request = httpRequest(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port || "80",
        path: `${url.pathname}${url.search}`,
        method: "GET",
        headers: {
          accept: "application/json",
          cookie,
          host: adminHost,
        },
        timeout: REVIEWER_SERVER_REQUEST_TIMEOUT_MS,
        signal: AbortSignal.timeout(REVIEWER_SERVER_REQUEST_TIMEOUT_MS),
      },
      (response) => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on("data", (chunk: Buffer | string) => {
          const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          size += value.length;
          if (size > REVIEWER_SERVER_RESPONSE_LIMIT_BYTES) {
            response.destroy();
            settleReject(
              new Error("reviewer identity response exceeded the size limit"),
            );
            return;
          }
          chunks.push(value);
        });
        response.on("end", () => {
          const headers = new Headers();
          for (const [name, value] of Object.entries(response.headers)) {
            if (value === undefined) continue;
            headers.set(name, Array.isArray(value) ? value.join(", ") : value);
          }
          settleResolve(
            new Response(Buffer.concat(chunks), {
              status: response.statusCode ?? 500,
              headers,
            }),
          );
        });
        response.on("error", settleReject);
      },
    );
    request.once("timeout", () =>
      request.destroy(new Error("reviewer identity request timed out")),
    );
    request.once("error", settleReject);
    request.end();
  });
}

export type ServerOwnedReviewerContext = Readonly<{
  source: "verified-server-reviewer-session";
  authenticated: true;
  actorId: string;
  email: string;
  expiresAtEpoch: number;
}>;

export async function resolveReviewerServerContext({
  cookieHeader,
  internalApiUrl,
  internalApiHost,
  adminAppUrl,
  production,
  fetcher,
}: {
  cookieHeader: string | null;
  internalApiUrl: string | undefined;
  internalApiHost: string | undefined;
  adminAppUrl?: string;
  production: boolean;
  fetcher?: typeof fetch;
}): Promise<ServerOwnedReviewerContext | null> {
  const url = reviewerMeUrl(internalApiUrl, internalApiHost);
  const cookie = reviewerCookie(cookieHeader, production);
  const adminHost = configuredAdminHost(adminAppUrl);
  if (!url || !cookie || !adminHost) return null;
  try {
    const response = fetcher
      ? await fetcher(url, {
          method: "GET",
          cache: "no-store",
          redirect: "manual",
          signal: AbortSignal.timeout(REVIEWER_SERVER_REQUEST_TIMEOUT_MS),
          // The API target is an internal transport address. Reviewer auth is
          // deliberately scoped by the canonical Admin host, so preserve that
          // host while keeping the internal URL private.
          headers: { accept: "application/json", cookie, host: adminHost },
        })
      : await requestReviewerServerIdentity(url, adminHost, cookie);
    if (response.status !== 200) return null;
    const value = identity.parse(await response.json());
    return {
      source: "verified-server-reviewer-session",
      authenticated: true,
      actorId: value.person_id,
      email: value.email,
      expiresAtEpoch: value.expires_at_epoch,
    };
  } catch {
    return null;
  }
}
