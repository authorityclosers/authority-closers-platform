/**
 * OAuth discovery for Connect and the remote MCP server, served by the web app at
 * /.well-known/... because only /v1/* reaches the API.
 *
 * - RFC 8414 authorization server metadata (the API serves the same document at
 *   /v1/oauth/metadata, built from its own settings).
 * - RFC 9728 protected resource metadata for /v1/mcp and /v1/api.
 *
 * The origin comes from the request's host, and only Sales X-Ray's own hosts
 * (and a local dev host) get an answer, so this cannot describe another site.
 */

export const SCOPES = [
  "calls:read",
  "reports:read",
  "leads:read",
  "leads:write",
  "webhooks:manage",
] as const;

/** What the MCP server's tools use; the resource metadata offers these (webhooks:manage is the CLI's). */
export const MCP_SCOPES = [
  "calls:read",
  "reports:read",
  "leads:read",
  "leads:write",
] as const;

const AUTH_METHODS = ["none", "client_secret_basic", "client_secret_post"];
const PUBLIC_HOST = /^salesxray(-[a-z0-9]+)?\.authorityclosers\.com$/;
const LOCAL_HOST = /^(127\.0\.0\.1|localhost)(:[0-9]{2,5})?$/;
const RESOURCES = new Set(["/v1/mcp", "/v1/api"]);

/** The Sales X-Ray origin this request reached, or null for any other host. */
export function publicOrigin(headers: Headers): string | null {
  const raw =
    headers.get("x-forwarded-host")?.split(",")[0]?.trim() ??
    headers.get("host") ??
    "";
  const host = raw.toLowerCase();
  if (PUBLIC_HOST.test(host)) return `https://${host}`;
  if (LOCAL_HOST.test(host)) return `http://${host}`;
  return null;
}

export function authorizationServerMetadata(origin: string) {
  return {
    issuer: origin,
    authorization_endpoint: `${origin}/connect`,
    token_endpoint: `${origin}/v1/oauth/token`,
    revocation_endpoint: `${origin}/v1/oauth/revoke`,
    registration_endpoint: `${origin}/v1/oauth/register`,
    response_types_supported: ["code"],
    response_modes_supported: ["query"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: AUTH_METHODS,
    revocation_endpoint_auth_methods_supported: AUTH_METHODS,
    scopes_supported: [...SCOPES],
    service_documentation: `${origin}/developers`,
  };
}

/** RFC 9728 metadata for one protected path, or null for a path we don't serve. */
export function protectedResourceMetadata(origin: string, path: string) {
  const resource = path === "" || path === "/" ? "/v1/mcp" : path;
  if (!RESOURCES.has(resource)) return null;
  return {
    resource: `${origin}${resource}`,
    authorization_servers: [origin],
    bearer_methods_supported: ["header"],
    scopes_supported: [...MCP_SCOPES],
    resource_name: "Sales X-Ray",
    resource_documentation: `${origin}/developers`,
  };
}

export function discoveryAnswer(body: unknown) {
  return Response.json(body, {
    headers: {
      "cache-control": "public, max-age=300",
      "access-control-allow-origin": "*",
    },
  });
}

export function notHere() {
  return Response.json({ error: "not_found" }, { status: 404 });
}
