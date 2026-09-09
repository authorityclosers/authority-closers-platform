import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  loadPlatformIdentity,
  readPlatformJson,
  verifyPlatformIdentity,
} from "@ac/operations-web/platform-identity";
import { resolvePlatformServerContext } from "@ac/operations-web/server-auth";
import * as serverAuth from "@ac/operations-web/server-auth";
import {
  isCoachApiRequest,
  isStagingAdminRequest,
} from "@ac/operations-web/dev-proxy";
import { proxy } from "../../proxy";
const person = "11111111-1111-4111-8111-111111111111",
  session = "22222222-2222-4222-8222-222222222222";
const me = {
  person_id: person,
  email: "synthetic@example.test",
  display_name: "Synthetic",
  email_verified_at: "2026-09-08",
  selected_tenant_id: null,
  membership_role: null,
  permissions: [],
};
const context = {
  person_id: person,
  session_id: session,
  tenant_id: null,
  membership_role: null,
  permissions: [],
};
const access = {
  person_id: person,
  session_id: session,
  selected_tenant_id: null,
  platform_permissions: ["platform_tenants_read"],
};
const identity = verifyPlatformIdentity(me, context, access)!;
const options = {
  cookieHeader: "__Host-ac_session=" + "s".repeat(43),
  internalApiHost: "api.production.ac.internal.invalid",
  internalApiUrl: "http://api.production.ac.internal.invalid:8000",
};
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});
describe("separate Platform Admin admission", () => {
  it("accepts a verified exact grant without changing membership or requiring selected tenant", () => {
    expect(identity).toMatchObject({
      personId: person,
      sessionId: session,
      selectedTenantId: null,
      permissions: ["platform_tenants_read"],
    });
    expect(
      verifyPlatformIdentity(me, context, {
        ...access,
        platform_permissions: [],
      }),
    ).toBeNull();
  });
  it.each([
    { person_id: session },
    { session_id: person },
    { selected_tenant_id: person },
    { platform_permissions: ["admin_surface"] },
    { platform_permissions: ["catalog_read"] },
    {
      platform_permissions: ["platform_tenants_read", "platform_tenants_read"],
    },
    { role: "owner" },
  ])("rejects mismatched or forged projection %j", (change) =>
    expect(
      verifyPlatformIdentity(me, context, { ...access, ...change }),
    ).toBeNull(),
  );
  it.each([
    { person_id: session },
    { tenant_id: person },
    { membership_role: "owner" },
    { permissions: ["admin_surface"] },
  ])("rejects inconsistent canonical snapshots %j", (change) =>
    expect(
      verifyPlatformIdentity(me, { ...context, ...change }, access),
    ).toBeNull(),
  );
  it("reads canonical identity with same-origin no-store, no redirects and abort bounds", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(me))
      .mockResolvedValueOnce(Response.json(context))
      .mockResolvedValueOnce(Response.json(access));
    expect(await loadPlatformIdentity({ fetcher })).toEqual(identity);
    expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
      "/v1/me",
      "/v1/context",
      "/v1/me/platform-access",
    ]);
    for (const [, init] of fetcher.mock.calls)
      expect(init).toMatchObject({
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: expect.any(AbortSignal),
      });
  });
  it.each([401, 403, 500, 302])("fails closed for HTTP %i", async (status) =>
    expect(
      await loadPlatformIdentity({
        fetcher: vi.fn().mockResolvedValue(new Response(null, { status })),
      }),
    ).toBeNull(),
  );
  it("cancels oversized streams before allocating an unlimited response", async () => {
    const cancel = vi.fn();
    const response = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array(65537));
        },
        cancel,
      }),
    );
    await expect(readPlatformJson(response)).rejects.toThrow("limit");
    expect(cancel).toHaveBeenCalledOnce();
  });
  it("sends only opaque cookie to the fixed internal host", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(me))
      .mockResolvedValueOnce(Response.json(context))
      .mockResolvedValueOnce(Response.json(access));
    expect(
      await resolvePlatformServerContext({
        ...options,
        cookieHeader:
          options.cookieHeader + "; CF_Authorization=ignored; role=owner",
        fetcher,
      }),
    ).toEqual(identity);
    for (const [path, init] of fetcher.mock.calls) {
      expect(String(path)).toMatch(
        /^http:\/\/api.production.ac.internal.invalid:8000\/v1\//,
      );
      expect(init?.redirect).toBe("manual");
      expect(init?.headers).toEqual({
        accept: "application/json",
        cookie: options.cookieHeader,
      });
    }
  });
  it.each([
    { cookieHeader: null },
    { cookieHeader: options.cookieHeader + "; " + options.cookieHeader },
    { internalApiHost: "evil.test" },
    { internalApiUrl: "https://api.production.ac.internal.invalid:8000" },
    { internalApiUrl: options.internalApiUrl + "?override=1" },
  ])("never contacts an untrusted transport %j", async (change) => {
    const fetcher = vi.fn();
    expect(
      await resolvePlatformServerContext({ ...options, ...change, fetcher }),
    ).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("admits only /platform and does not broaden legacy People or Coach routes", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.spyOn(serverAuth, "resolvePlatformServerContext").mockResolvedValue(
      identity,
    );
    vi.spyOn(serverAuth, "resolveAdminServerContext").mockResolvedValue(null);
    const admitted = await proxy(
      new NextRequest("https://admin.authorityclosers.com/platform"),
    );
    expect(admitted.headers.get("x-middleware-next")).toBe("1");
    expect(admitted.headers.get("cache-control")).toContain("no-store");
    const home = await proxy(
      new NextRequest("https://admin.authorityclosers.com/"),
    );
    expect(home.headers.get("location")).toBe("/platform");
    const people = await proxy(
      new NextRequest("https://admin.authorityclosers.com/people"),
    );
    expect(people.headers.get("x-middleware-next")).toBeNull();
  });
  it("ignores stale dev flags on production Platform page", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "true");
    vi.spyOn(serverAuth, "resolvePlatformServerContext").mockResolvedValue(
      null,
    );
    const denied = await proxy(
      new NextRequest("https://admin.authorityclosers.com/platform?role=owner"),
    );
    expect(denied.status).toBe(307);
    expect(denied.headers.get("location")).toBe("/login");
  });
  it.each([
    "/v1/me/platform-access",
    "/v1/platform/tenants",
    "/v1/platform/tenants?after_id=" + person,
  ])("keeps new read route off Coach and denies writes %s", (path) => {
    const url = new URL(path, "http://admin.localhost:3101");
    expect(isStagingAdminRequest(url, "GET")).toBe(true);
    expect(isStagingAdminRequest(url, "POST")).toBe(false);
    expect(isCoachApiRequest(url, "GET")).toBe(false);
  });
  it.each([
    "?person_id=" + person,
    "?after_id=bad",
    "?after_id=" + person + "&after_id=" + session,
  ])("rejects new platform selectors %s", (query) =>
    expect(
      isStagingAdminRequest(
        new URL("/v1/platform/tenants" + query, "http://admin.localhost:3101"),
        "GET",
      ),
    ).toBe(false),
  );
});
