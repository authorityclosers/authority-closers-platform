import { z } from "zod";

import type { ServerOwnedAdminContext } from "./admin-access";
import {
  loadPlatformIdentity,
  type PlatformIdentity,
} from "./platform-identity";
import {
  adminAccessSchema,
  contextSchema,
  meSchema,
  verifyAdminIdentity,
} from "./admin-identity";

type Fetcher = typeof fetch;

function internalContextUrl(
  rawBaseUrl: string | undefined,
  apiHost: string | null,
): URL | null {
  if (!rawBaseUrl || !apiHost) return null;
  const approvedOrigin = `http://${apiHost}:8000`;
  if (rawBaseUrl !== approvedOrigin) return null;
  try {
    const baseUrl = new URL(rawBaseUrl);
    if (
      baseUrl.protocol !== "http:" ||
      baseUrl.hostname !== apiHost ||
      baseUrl.port !== "8000" ||
      baseUrl.username ||
      baseUrl.password ||
      baseUrl.search ||
      baseUrl.hash ||
      baseUrl.pathname !== "/" ||
      baseUrl.origin !== approvedOrigin
    ) {
      return null;
    }
    return new URL("/v1/context", baseUrl);
  } catch {
    return null;
  }
}

const TRUSTED_INTERNAL_API_HOSTS = new Set([
  "api.production.ac.internal.invalid",
  "api.staging.ac.internal.invalid",
]);

function trustedInternalApiHost(rawHost: string | undefined): string | null {
  const host = rawHost ?? "";
  return TRUSTED_INTERNAL_API_HOSTS.has(host) ? host : null;
}

const SESSION_COOKIE_NAME = "__Host-ac_session";
const OPAQUE_SESSION_PATTERN = /^[A-Za-z0-9_-]{43,512}$/;

function trustedSessionCookie(rawCookieHeader: string | null): string | null {
  if (!rawCookieHeader) return null;

  const values: string[] = [];
  for (const segment of rawCookieHeader.split(";")) {
    const separator = segment.indexOf("=");
    if (separator < 1) continue;
    const name = segment.slice(0, separator).trim();
    if (name !== SESSION_COOKIE_NAME) continue;
    values.push(segment.slice(separator + 1).trim());
  }
  if (values.length !== 1) return null;
  const value = values[0];
  if (value === undefined || !OPAQUE_SESSION_PATTERN.test(value)) return null;
  return `${SESSION_COOKIE_NAME}=${value}`;
}

/** Separate platform admission; never translates platform grants into academy roles. */
export async function resolvePlatformServerContext({
  cookieHeader,
  internalApiUrl,
  internalApiHost,
  fetcher = fetch,
}: {
  cookieHeader: string | null;
  internalApiUrl: string | undefined;
  internalApiHost: string | undefined;
  fetcher?: Fetcher;
}): Promise<PlatformIdentity | null> {
  const apiHost = trustedInternalApiHost(internalApiHost);
  const contextUrl = internalContextUrl(internalApiUrl, apiHost);
  const cookie = trustedSessionCookie(cookieHeader);
  if (!contextUrl || !cookie) return null;
  return loadPlatformIdentity({
    fetcher: (path, init) =>
      fetcher(new URL(String(path), contextUrl), {
        ...init,
        redirect: "manual",
        headers: { accept: "application/json", cookie },
      }),
  });
}

export async function resolveAdminServerContext({
  cookieHeader,
  internalApiUrl,
  internalApiHost,
  fetcher = fetch,
}: {
  cookieHeader: string | null;
  internalApiUrl: string | undefined;
  internalApiHost: string | undefined;
  fetcher?: Fetcher;
}): Promise<ServerOwnedAdminContext | null> {
  const apiHost = trustedInternalApiHost(internalApiHost);
  const contextUrl = internalContextUrl(internalApiUrl, apiHost);
  const forwardedCookie = trustedSessionCookie(cookieHeader);
  if (!contextUrl || !apiHost || !forwardedCookie) return null;
  const trustedCookie: string = forwardedCookie;

  async function read<T>(url: URL, schema: z.ZodType<T>): Promise<T | null> {
    let response: Response;
    try {
      response = await fetcher(url, {
        method: "GET",
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(3_000),
        headers: {
          accept: "application/json",
          cookie: trustedCookie,
        },
      });
    } catch {
      return null;
    }
    if (!response || response.status !== 200) return null;
    try {
      return schema.parse(await response.json());
    } catch {
      return null;
    }
  }

  const meUrl = new URL("/v1/me", contextUrl);
  const me = await read(meUrl, meSchema);
  const parsed = await read(contextUrl, contextSchema);
  const access = await read(
    new URL("/v1/me/studio-access", contextUrl),
    adminAccessSchema,
  );
  const identity = verifyAdminIdentity(me, parsed, access);
  if (!identity) return null;

  return {
    source: "verified-server-session",
    authenticated: true,
    adminSurfaceAuthorized: true,
    actorId: identity.context.person_id,
    tenantId: identity.context.tenant_id,
    permissions: [...new Set(identity.context.permissions)].sort(),
    studioCapabilities: identity.studioCapabilities,
  };
}
