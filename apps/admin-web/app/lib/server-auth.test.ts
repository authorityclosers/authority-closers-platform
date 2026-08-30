import { describe, expect, it, vi } from "vitest";

import { resolveAdminServerContext } from "./server-auth";

const verifiedContext = {
  person_id: "11111111-1111-4111-8111-111111111111",
  session_id: "22222222-2222-4222-8222-222222222222",
  tenant_id: "33333333-3333-4333-8333-333333333333",
  membership_role: "admin",
  permissions: ["catalog_publish", "admin_surface"],
};

describe("server-owned admin context adapter", () => {
  it("forwards only the opaque cookie to the fixed internal context endpoint", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(verifiedContext), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const context = await resolveAdminServerContext({
      cookieHeader: "ac_session=opaque-value; attacker_role=owner",
      internalApiUrl: "http://api:8000",
      internalApiHost: "api.authorityclosers.com",
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
    expect(fetcher).toHaveBeenCalledOnce();
    const [url, init] = fetcher.mock.calls[0];
    expect(url.toString()).toBe("http://api:8000/v1/context");
    expect(init?.method).toBe("GET");
    expect(init?.redirect).toBe("manual");
    expect(new Headers(init?.headers).get("cookie")).toContain(
      "ac_session=opaque-value",
    );
    expect(new Headers(init?.headers).get("host")).toBe(
      "api.authorityclosers.com",
    );
  });

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
    const context = await resolveAdminServerContext({
      cookieHeader: "ac_session=opaque-value",
      internalApiUrl: "http://api:8000",
      internalApiHost: "api.authorityclosers.com",
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(response),
    });

    expect(context).toBeNull();
  });

  it("does not make a request for missing cookies or malformed internal URLs", async () => {
    const fetcher = vi.fn<typeof fetch>();

    expect(
      await resolveAdminServerContext({
        cookieHeader: null,
        internalApiUrl: "http://api:8000",
        internalApiHost: "api.authorityclosers.com",
        fetcher,
      }),
    ).toBeNull();
    expect(
      await resolveAdminServerContext({
        cookieHeader: "ac_session=opaque",
        internalApiUrl: "https://user:password@evil.test/?next=http://api:8000",
        internalApiHost: "api.authorityclosers.com",
        fetcher,
      }),
    ).toBeNull();
    expect(
      await resolveAdminServerContext({
        cookieHeader: "ac_session=opaque",
        internalApiUrl: "http://api:8000",
        internalApiHost: "attacker.example",
        fetcher,
      }),
    ).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses the explicit staging API host without changing the image", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(verifiedContext), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await resolveAdminServerContext({
      cookieHeader: "ac_session=opaque-value",
      internalApiUrl: "http://api:8000",
      internalApiHost: "api-staging.authorityclosers.com",
      fetcher,
    });

    const [, init] = fetcher.mock.calls[0];
    expect(new Headers(init?.headers).get("host")).toBe(
      "api-staging.authorityclosers.com",
    );
  });
});
