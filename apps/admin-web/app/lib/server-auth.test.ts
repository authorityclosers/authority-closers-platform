import dns from "node:dns";
import { createServer, type Server } from "node:http";

import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveAdminServerContext } from "./server-auth";

const PRODUCTION_INTERNAL_API_HOST = "api.production.ac.internal.invalid";
const PRODUCTION_INTERNAL_API_URL = `http://${PRODUCTION_INTERNAL_API_HOST}:8000`;
const STAGING_INTERNAL_API_HOST = "api.staging.ac.internal.invalid";
const STAGING_INTERNAL_API_URL = `http://${STAGING_INTERNAL_API_HOST}:8000`;
const VALID_SESSION_TOKEN = "s".repeat(43);
const SECOND_VALID_SESSION_TOKEN = "t".repeat(43);

const verifiedContext = {
  person_id: "11111111-1111-4111-8111-111111111111",
  session_id: "22222222-2222-4222-8222-222222222222",
  tenant_id: "33333333-3333-4333-8333-333333333333",
  membership_role: "admin",
  permissions: ["catalog_publish", "admin_surface"],
};

const verifiedMe = {
  person_id: verifiedContext.person_id,
  email: "admin@authorityclosers.com",
  display_name: "AC Admin",
  email_verified_at: "2026-08-30T00:00:00Z",
  selected_tenant_id: verifiedContext.tenant_id,
  membership_role: "admin",
  permissions: ["catalog_publish", "admin_surface"],
};

async function listenOnInternalApiPort(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error) => reject(error);
    server.once("error", onError);
    server.listen(8000, "127.0.0.1", () => {
      server.off("error", onError);
      resolve();
    });
  });
}

async function closeServer(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

afterEach(() => vi.restoreAllMocks());

describe("server-owned admin context adapter", () => {
  it("forwards only __Host-ac_session to both canonical identity endpoints", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(verifiedMe))
      .mockResolvedValueOnce(Response.json(verifiedContext));

    const context = await resolveAdminServerContext({
      cookieHeader: `attacker_role=owner; CF_Authorization=cloudflare-token; __Host-ac_session=${VALID_SESSION_TOKEN}`,
      internalApiUrl: PRODUCTION_INTERNAL_API_URL,
      internalApiHost: PRODUCTION_INTERNAL_API_HOST,
      fetcher,
    });

    expect(context).toEqual({
      source: "verified-server-session",
      authenticated: true,
      adminSurfaceAuthorized: true,
      actorId: verifiedContext.person_id,
      tenantId: verifiedContext.tenant_id,
      permissions: ["admin_surface", "catalog_publish"],
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(timeout.mock.calls).toEqual([[3_000], [3_000]]);
    expect(fetcher.mock.calls.map(([url]) => url.toString())).toEqual([
      `${PRODUCTION_INTERNAL_API_URL}/v1/me`,
      `${PRODUCTION_INTERNAL_API_URL}/v1/context`,
    ]);
    for (const [, init] of fetcher.mock.calls) {
      expect(init?.method).toBe("GET");
      expect(init?.redirect).toBe("manual");
      expect(new Headers(init?.headers).get("cookie")).toBe(
        `__Host-ac_session=${VALID_SESSION_TOKEN}`,
      );
      expect(new Headers(init?.headers).has("host")).toBe(false);
    }
  });

  it("uses Node 24 DNS and fetch transport to send the canonical wire Host", async () => {
    const received: Array<{
      host: string | null;
      cookie: string | null;
      path: string | null;
    }> = [];
    const server = createServer((request, response) => {
      received.push({
        host: request.headers.host ?? null,
        cookie: request.headers.cookie ?? null,
        path: request.url ?? null,
      });
      response.setHeader("content-type", "application/json");
      if (request.url === "/v1/me") {
        response.end(JSON.stringify(verifiedMe));
      } else if (request.url === "/v1/context") {
        response.end(JSON.stringify(verifiedContext));
      } else {
        response.statusCode = 404;
        response.end("{}");
      }
    });
    await listenOnInternalApiPort(server);

    const lookupImplementation = ((
      hostname: string,
      options: unknown,
      maybeCallback?: unknown,
    ) => {
      if (hostname !== PRODUCTION_INTERNAL_API_HOST) {
        throw new Error(`Unexpected DNS lookup for ${hostname}`);
      }
      const callback = (
        typeof options === "function" ? options : maybeCallback
      ) as ((...args: unknown[]) => void) | undefined;
      if (!callback) throw new Error("DNS lookup callback is required");
      const all =
        typeof options === "object" &&
        options !== null &&
        "all" in options &&
        options.all === true;
      if (all) {
        callback(null, [{ address: "127.0.0.1", family: 4 }]);
      } else {
        callback(null, "127.0.0.1", 4);
      }
    }) as typeof dns.lookup;
    const lookup = vi
      .spyOn(dns, "lookup")
      .mockImplementation(lookupImplementation);

    try {
      await expect(
        resolveAdminServerContext({
          cookieHeader: `CF_Authorization=edge-token; __Host-ac_session=${VALID_SESSION_TOKEN}; ignored=value`,
          internalApiUrl: PRODUCTION_INTERNAL_API_URL,
          internalApiHost: PRODUCTION_INTERNAL_API_HOST,
        }),
      ).resolves.toEqual({
        source: "verified-server-session",
        authenticated: true,
        adminSurfaceAuthorized: true,
        actorId: verifiedContext.person_id,
        tenantId: verifiedContext.tenant_id,
        permissions: ["admin_surface", "catalog_publish"],
      });
    } finally {
      lookup.mockRestore();
      await closeServer(server);
    }

    expect(received).toEqual([
      {
        host: `${PRODUCTION_INTERNAL_API_HOST}:8000`,
        cookie: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
        path: "/v1/me",
      },
      {
        host: `${PRODUCTION_INTERNAL_API_HOST}:8000`,
        cookie: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
        path: "/v1/context",
      },
    ]);
  });

  it.each([
    [
      "unrelated and Cloudflare cookies",
      "attacker_role=owner; CF_Authorization=token",
    ],
    [
      "duplicate session cookies",
      `__Host-ac_session=${VALID_SESSION_TOKEN}; __Host-ac_session=${SECOND_VALID_SESSION_TOKEN}`,
    ],
    ["malformed session cookie", "__Host-ac_session=opaque value"],
    ["legacy session cookie", `ac_session=${VALID_SESSION_TOKEN}`],
  ])(
    "refuses %s without forwarding any cookie",
    async (_label, cookieHeader) => {
      const fetcher = vi.fn<typeof fetch>();

      await expect(
        resolveAdminServerContext({
          cookieHeader,
          internalApiUrl: PRODUCTION_INTERNAL_API_URL,
          internalApiHost: PRODUCTION_INTERNAL_API_HOST,
          fetcher,
        }),
      ).resolves.toBeNull();
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["API rejection", new Response("denied", { status: 401 })],
    [
      "learner role",
      new Response(
        JSON.stringify({ ...verifiedContext, membership_role: "learner" }),
        { status: 200 },
      ),
    ],
    [
      "missing admin permission",
      new Response(
        JSON.stringify({
          ...verifiedContext,
          permissions: ["catalog_publish"],
        }),
        { status: 200 },
      ),
    ],
    [
      "global context",
      new Response(JSON.stringify({ ...verifiedContext, tenant_id: null }), {
        status: 200,
      }),
    ],
    ["invalid body", new Response('{"role":"owner"}', { status: 200 })],
    ["redirect", new Response(null, { status: 302 })],
  ])("fails closed for %s", async (_label, response) => {
    const fetcher = vi.fn<typeof fetch>();
    if (response.status === 200) {
      fetcher
        .mockResolvedValueOnce(Response.json(verifiedMe))
        .mockResolvedValueOnce(response);
    } else {
      fetcher.mockResolvedValueOnce(response);
    }
    const context = await resolveAdminServerContext({
      cookieHeader: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
      internalApiUrl: PRODUCTION_INTERNAL_API_URL,
      internalApiHost: PRODUCTION_INTERNAL_API_HOST,
      fetcher,
    });

    expect(context).toBeNull();
  });

  it("does not make a request for missing cookies or malformed internal URLs", async () => {
    const fetcher = vi.fn<typeof fetch>();

    expect(
      await resolveAdminServerContext({
        cookieHeader: null,
        internalApiUrl: PRODUCTION_INTERNAL_API_URL,
        internalApiHost: PRODUCTION_INTERNAL_API_HOST,
        fetcher,
      }),
    ).toBeNull();
    expect(
      await resolveAdminServerContext({
        cookieHeader: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
        internalApiUrl: `https://user:password@evil.test/?next=${PRODUCTION_INTERNAL_API_URL}`,
        internalApiHost: PRODUCTION_INTERNAL_API_HOST,
        fetcher,
      }),
    ).toBeNull();
    expect(
      await resolveAdminServerContext({
        cookieHeader: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
        internalApiUrl: PRODUCTION_INTERNAL_API_URL,
        internalApiHost: "attacker.example",
        fetcher,
      }),
    ).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects an arbitrary external API destination before forwarding the cookie", async () => {
    const fetcher = vi.fn<typeof fetch>();

    const context = await resolveAdminServerContext({
      cookieHeader: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
      internalApiUrl: "https://evil.example",
      internalApiHost: PRODUCTION_INTERNAL_API_HOST,
      fetcher,
    });

    expect(context).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    [
      "canonical-host mismatch",
      PRODUCTION_INTERNAL_API_URL,
      STAGING_INTERNAL_API_HOST,
    ],
    [
      "external hostname",
      "http://evil.example:8000",
      PRODUCTION_INTERNAL_API_HOST,
    ],
    [
      "legacy public API hostname",
      "http://api.authorityclosers.com:8000",
      "api.authorityclosers.com",
    ],
    [
      "wrong internal port",
      `http://${PRODUCTION_INTERNAL_API_HOST}:8080`,
      PRODUCTION_INTERNAL_API_HOST,
    ],
    [
      "TLS on the internal hop",
      `https://${PRODUCTION_INTERNAL_API_HOST}:8000`,
      PRODUCTION_INTERNAL_API_HOST,
    ],
    [
      "userinfo",
      `http://user:password@${PRODUCTION_INTERNAL_API_HOST}:8000`,
      PRODUCTION_INTERNAL_API_HOST,
    ],
    [
      "non-root path",
      `${PRODUCTION_INTERNAL_API_URL}/internal`,
      PRODUCTION_INTERNAL_API_HOST,
    ],
    [
      "query",
      `${PRODUCTION_INTERNAL_API_URL}?next=1`,
      PRODUCTION_INTERNAL_API_HOST,
    ],
    [
      "fragment",
      `${PRODUCTION_INTERNAL_API_URL}#next`,
      PRODUCTION_INTERNAL_API_HOST,
    ],
    [
      "trailing slash",
      `${PRODUCTION_INTERNAL_API_URL}/`,
      PRODUCTION_INTERNAL_API_HOST,
    ],
  ])(
    "rejects %s before network",
    async (_label, internalApiUrl, internalApiHost) => {
      const fetcher = vi.fn<typeof fetch>();

      await expect(
        resolveAdminServerContext({
          cookieHeader: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
          internalApiUrl,
          internalApiHost,
          fetcher,
        }),
      ).resolves.toBeNull();
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it("uses the exact staging API target without overriding Host", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(verifiedMe))
      .mockResolvedValueOnce(Response.json(verifiedContext));

    await resolveAdminServerContext({
      cookieHeader: `__Host-ac_session=${VALID_SESSION_TOKEN}`,
      internalApiUrl: STAGING_INTERNAL_API_URL,
      internalApiHost: STAGING_INTERNAL_API_HOST,
      fetcher,
    });

    expect(fetcher.mock.calls.map(([url]) => url.toString())).toEqual([
      `${STAGING_INTERNAL_API_URL}/v1/me`,
      `${STAGING_INTERNAL_API_URL}/v1/context`,
    ]);
    for (const [, init] of fetcher.mock.calls) {
      expect(new Headers(init?.headers).has("host")).toBe(false);
    }
  });
});
