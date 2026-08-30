import { z } from "zod";

import type { ServerOwnedAdminContext } from "./admin-access";

const contextSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    tenant_id: z.uuid().nullable(),
    membership_role: z
      .enum(["owner", "admin", "support", "learner"])
      .nullable(),
    permissions: z.array(z.string().min(1).max(64)).max(32),
  })
  .strict();

type Fetcher = typeof fetch;

function internalContextUrl(rawBaseUrl: string | undefined): URL | null {
  if (!rawBaseUrl) return null;
  try {
    const baseUrl = new URL(rawBaseUrl);
    if (
      !["http:", "https:"].includes(baseUrl.protocol) ||
      baseUrl.username ||
      baseUrl.password ||
      baseUrl.search ||
      baseUrl.hash ||
      (baseUrl.pathname !== "/" && baseUrl.pathname !== "")
    ) {
      return null;
    }
    return new URL("/v1/context", baseUrl);
  } catch {
    return null;
  }
}

const TRUSTED_INTERNAL_API_HOSTS = new Set([
  "api.authorityclosers.com",
  "api-staging.authorityclosers.com",
]);

function trustedInternalApiHost(rawHost: string | undefined): string | null {
  const host = rawHost?.trim().toLowerCase() ?? "";
  return TRUSTED_INTERNAL_API_HOSTS.has(host) ? host : null;
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
  const contextUrl = internalContextUrl(internalApiUrl);
  const apiHost = trustedInternalApiHost(internalApiHost);
  if (!contextUrl || !apiHost || !cookieHeader) return null;

  let response: Response;
  try {
    response = await fetcher(contextUrl, {
      method: "GET",
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(3_000),
      headers: {
        accept: "application/json",
        cookie: cookieHeader,
        host: apiHost,
      },
    });
  } catch {
    return null;
  }
  if (response.status !== 200) return null;

  let parsed: z.infer<typeof contextSchema>;
  try {
    parsed = contextSchema.parse(await response.json());
  } catch {
    return null;
  }
  const permissions = new Set(parsed.permissions);
  const adminRole =
    parsed.membership_role === "owner" ||
    parsed.membership_role === "admin" ||
    parsed.membership_role === "support";
  if (!parsed.tenant_id || !adminRole || !permissions.has("admin_surface")) {
    return null;
  }

  return {
    source: "verified-server-session",
    authenticated: true,
    adminSurfaceAuthorized: true,
    actorId: parsed.person_id,
    tenantId: parsed.tenant_id,
    permissions: [...permissions].sort(),
  };
}
