import { describe, expect, it, vi } from "vitest";

import {
  InMemoryDevelopmentAdminSessionStore,
  isStagingAdminRequest,
  proxyDevelopmentAdminApi,
  resolveDevAdminApiTarget,
  type DevAdminFetch,
} from "./dev-api-proxy";

const ACCESS_JWT = `${"a".repeat(32)}.${"b".repeat(64)}.${"c".repeat(32)}`;
const STAGING_SESSION = "s".repeat(43);
const ADMIN_PERSON = "11111111-1111-4111-8111-111111111111";
const ADMIN_TENANT = "22222222-2222-4222-8222-222222222222";
const ADMIN_SESSION = "33333333-3333-4333-8333-333333333333";
const TARGET_ID = "44444444-4444-4444-8444-444444444444";

const bridgeEnvironment = {
  AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
  AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "http://localhost:3001",
  AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
    "https://admin-staging.authorityclosers.com",
  AC_DEV_ADMIN_ACCESS_JWT: ACCESS_JWT,
};

function request(
  path: string,
  init: RequestInit = {},
  origin = "http://localhost:3001",
) {
  return new Request(`${origin}${path}`, init);
}

function mutation(path: string, body: unknown = {}) {
  return request(path, {
    method: "POST",
    headers: {
      origin: "http://localhost:3001",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

function stagingCookie(value = STAGING_SESSION) {
  return `__Host-ac_session=${value}; Path=/; Secure; HttpOnly; SameSite=Lax`;
}

function adminMe(role: "owner" | "admin" | "support" | "learner" = "owner") {
  return {
    person_id: ADMIN_PERSON,
    email: "admin@example.test",
    display_name: "Test Admin",
    email_verified_at: "2026-09-04T00:00:00Z",
    selected_tenant_id: ADMIN_TENANT,
    membership_role: role,
    permissions: role === "learner" ? [] : ["admin_surface", "catalog_publish"],
  };
}

function adminContext(
  role: "owner" | "admin" | "support" | "learner" = "owner",
) {
  return {
    person_id: ADMIN_PERSON,
    session_id: ADMIN_SESSION,
    tenant_id: ADMIN_TENANT,
    membership_role: role,
    permissions: role === "learner" ? [] : ["admin_surface", "catalog_publish"],
  };
}

function successfulLoginFetcher(
  role: "owner" | "admin" | "support" | "learner" = "owner",
) {
  return vi.fn<DevAdminFetch>().mockImplementation((input, init) => {
    const url = new URL(String(input));
    if (url.pathname === "/v1/auth/password/login") {
      expect(init?.headers).toBeInstanceOf(Headers);
      const headers = init?.headers as Headers;
      expect(headers.get("origin")).toBe(
        "https://admin-staging.authorityclosers.com",
      );
      expect(headers.get("cookie")).toBe(`CF_Authorization=${ACCESS_JWT}`);
      expect(headers.has("authorization")).toBe(false);
      return Promise.resolve(
        Response.json(
          { authenticated: true, person_id: ADMIN_PERSON },
          { headers: { "set-cookie": stagingCookie() } },
        ),
      );
    }
    if (url.pathname === "/v1/me") {
      expect(String(new Headers(init?.headers).get("cookie"))).toContain(
        `__Host-ac_session=${STAGING_SESSION}`,
      );
      return Promise.resolve(Response.json(adminMe(role)));
    }
    if (url.pathname === "/v1/context") {
      return Promise.resolve(Response.json(adminContext(role)));
    }
    if (url.pathname === "/v1/auth/logout") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    throw new Error(`Unexpected upstream path: ${url.pathname}`);
  });
}

function localHandle(response: Response): string {
  const cookie = response.headers.get("set-cookie") ?? "";
  const match = /__Host-ac_dev_admin_qa_session=([A-Za-z0-9_-]{43})/.exec(
    cookie,
  );
  if (!match) throw new Error("local session cookie missing");
  return match[1];
}

describe("development admin API target", () => {
  it("is development-only and defaults to the loopback API", () => {
    expect(resolveDevAdminApiTarget({}, "production")).toBeNull();
    expect(resolveDevAdminApiTarget({}, "development")).toEqual({
      mode: "local",
      origin: "http://127.0.0.1:8000",
    });
  });

  it("accepts only an exact loopback browser and staging admin upstream", () => {
    expect(resolveDevAdminApiTarget(bridgeEnvironment, "development")).toEqual({
      mode: "staging-authenticated",
      origin: "https://admin-staging.authorityclosers.com",
      browserOrigin: "http://localhost:3001",
      accessJwt: ACCESS_JWT,
    });

    for (const environment of [
      {
        ...bridgeEnvironment,
        AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "https://evil.test",
      },
      {
        ...bridgeEnvironment,
        AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
          "https://admin.authorityclosers.com",
      },
      {
        ...bridgeEnvironment,
        AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
          "https://api-staging.authorityclosers.com",
      },
      { ...bridgeEnvironment, AC_DEV_ADMIN_ACCESS_JWT: "not-a-jwt" },
    ]) {
      expect(() =>
        resolveDevAdminApiTarget(environment, "development"),
      ).toThrow();
    }
  });

  it("rejects remote, credentialed, and pathful local API origins", () => {
    for (const value of [
      "https://api-staging.authorityclosers.com",
      "https://api.authorityclosers.com",
      "http://user:password@localhost:8000",
      "http://localhost:8000/v1",
      "file:///tmp/api",
    ]) {
      expect(() =>
        resolveDevAdminApiTarget(
          { AC_DEV_ADMIN_API_ORIGIN: value },
          "development",
        ),
      ).toThrow();
    }
  });
});

describe("admin bridge route allowlist", () => {
  it.each([
    ["GET", "/v1/dev-bridge/health"],
    ["POST", "/v1/auth/password/login"],
    ["POST", "/v1/auth/logout"],
    ["GET", "/v1/me"],
    ["GET", "/v1/context"],
    ["POST", "/v1/admin/corrections"],
    ["POST", "/v1/admin/enrollment-grants"],
    ["POST", `/v1/admin/program-versions/${TARGET_ID}/publish`],
    ["POST", `/v1/admin/jobs/${TARGET_ID}/retry`],
    ["POST", "/v1/admin/recovery/reconcile"],
  ])("allows %s %s", (method, path) => {
    expect(
      isStagingAdminRequest(new URL(`http://localhost:3001${path}`), method),
    ).toBe(true);
  });

  it.each([
    ["GET", "/v1/admin/corrections"],
    ["POST", "/v1/context"],
    ["GET", "/v1/auth/google/start"],
    ["POST", "/v1/auth/password/recovery"],
    ["POST", "/v1/auth/password/register"],
    ["GET", "/internal/v1/jobs"],
    ["POST", "/v1/admin/unknown"],
    ["POST", "/v1/admin/jobs/not-a-uuid/retry"],
    ["POST", `/v1/admin/jobs/${TARGET_ID}/retry?force=true`],
  ])("denies %s %s", (method, path) => {
    expect(
      isStagingAdminRequest(new URL(`http://localhost:3001${path}`), method),
    ).toBe(false);
  });
});

describe("authenticated staging admin bridge", () => {
  it("proves Cloudflare Access transport without creating a product session", async () => {
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockResolvedValue(
        Response.json({ code: "authentication_required" }, { status: 401 }),
      );
    const response = await proxyDevelopmentAdminApi(
      request("/v1/dev-bridge/health"),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "ok",
      transport: "connected",
      product_session: "sign_in_required",
      upstream: "staging-admin",
    });
    const headers = new Headers(fetcher.mock.calls[0][1]?.headers);
    expect(headers.get("cookie")).toBe(`CF_Authorization=${ACCESS_JWT}`);
  });

  it("turns an Access redirect into an actionable transport error", async () => {
    const response = await proxyDevelopmentAdminApi(
      request("/v1/dev-bridge/health"),
      vi.fn<DevAdminFetch>().mockResolvedValue(
        new Response(null, {
          status: 302,
          headers: { location: "https://access.example.test" },
        }),
      ),
      bridgeEnvironment,
      "development",
    );
    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      code: "admin_bridge_access_required",
    });
    expect(response.headers.has("location")).toBe(false);
  });

  it("maps a password session only after server-owned admin verification", async () => {
    const store = new InMemoryDevelopmentAdminSessionStore();
    const fetcher = successfulLoginFetcher();
    const response = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login", {
        email: "admin@example.test",
        password: "not-recorded-by-the-proxy",
      }),
      fetcher,
      bridgeEnvironment,
      "development",
      store,
    );

    expect(response.status).toBe(200);
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("__Host-ac_dev_admin_qa_session=");
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).not.toContain(STAGING_SESSION);
    expect(store.get(localHandle(response))).toBe(STAGING_SESSION);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("rejects learner credentials and revokes the unmapped upstream session", async () => {
    const fetcher = successfulLoginFetcher("learner");
    const response = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login", {
        email: "learner@example.test",
        password: "not-recorded-by-the-proxy",
      }),
      fetcher,
      bridgeEnvironment,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      code: "admin_bridge_authorization_denied",
    });
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(4);
    expect(new URL(String(fetcher.mock.calls[3][0])).pathname).toBe(
      "/v1/auth/logout",
    );
  });

  it("rejects a login response that drifts to a browser credential contract", async () => {
    const fetcher = vi.fn<DevAdminFetch>().mockImplementation((input) => {
      const path = new URL(String(input)).pathname;
      if (path === "/v1/auth/password/login") {
        return Promise.resolve(
          Response.json(
            { access_token: "must-never-reach-the-browser" },
            { headers: { "set-cookie": stagingCookie() } },
          ),
        );
      }
      if (path === "/v1/auth/logout") {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      throw new Error(`Unexpected path: ${path}`);
    });
    const response = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login"),
      fetcher,
      bridgeEnvironment,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      code: "admin_bridge_credential_contract_invalid",
    });
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("rejects browser-supplied remote credentials before contacting staging", async () => {
    const fetcher = vi.fn<DevAdminFetch>();
    const browserCredentials: Array<Record<string, string>> = [
      { cookie: `__Host-ac_session=${STAGING_SESSION}` },
      { cookie: `CF_Authorization=${ACCESS_JWT}` },
      { authorization: "Bearer browser-token" },
      { "cf-access-token": ACCESS_JWT },
      { "cf-access-client-id": "client.access" },
    ];
    for (const headers of browserCredentials) {
      const response = await proxyDevelopmentAdminApi(
        request("/v1/me", { headers }),
        fetcher,
        bridgeEnvironment,
        "development",
      );
      expect(response.status).toBe(403);
      expect(await response.json()).toMatchObject({
        code: "admin_bridge_browser_credential_denied",
      });
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects an oversized admin mutation before buffering it upstream", async () => {
    const fetcher = vi.fn<DevAdminFetch>();
    const response = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login", {
        reason: "x".repeat(1024 * 1024 + 1),
      }),
      fetcher,
      bridgeEnvironment,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );

    expect(response.status).toBe(413);
    expect(await response.json()).toMatchObject({
      code: "admin_bridge_request_too_large",
    });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("requires the exact loopback request and unsafe Origin", async () => {
    const fetcher = vi.fn<DevAdminFetch>();
    const wrongHost = await proxyDevelopmentAdminApi(
      request("/v1/me", {}, "http://127.0.0.1:3001"),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    const missingOrigin = await proxyDevelopmentAdminApi(
      request("/v1/auth/password/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      }),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    expect(wrongHost.status).toBe(403);
    expect(missingOrigin.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses the local handle for allowlisted requests and clears it on logout", async () => {
    const store = new InMemoryDevelopmentAdminSessionStore();
    const login = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login"),
      successfulLoginFetcher(),
      bridgeEnvironment,
      "development",
      store,
    );
    const handle = localHandle(login);
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const logout = await proxyDevelopmentAdminApi(
      request("/v1/auth/logout", {
        method: "POST",
        headers: {
          origin: "http://localhost:3001",
          cookie: `__Host-ac_dev_admin_qa_session=${handle}`,
        },
      }),
      fetcher,
      bridgeEnvironment,
      "development",
      store,
    );
    expect(logout.status).toBe(204);
    expect(store.get(handle)).toBeNull();
    expect(logout.headers.get("set-cookie")).toContain("Max-Age=0");
    const upstreamCookie = new Headers(fetcher.mock.calls[0][1]?.headers).get(
      "cookie",
    );
    expect(upstreamCookie).toContain(`CF_Authorization=${ACCESS_JWT}`);
    expect(upstreamCookie).toContain(`__Host-ac_session=${STAGING_SESSION}`);
    expect(upstreamCookie).not.toContain(handle);
  });

  it("fails closed on a missing local session and unsupported route", async () => {
    const fetcher = vi.fn<DevAdminFetch>();
    const missing = await proxyDevelopmentAdminApi(
      request("/v1/me"),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    const unsupported = await proxyDevelopmentAdminApi(
      request("/v1/admin/users"),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    expect(missing.status).toBe(401);
    expect(missing.headers.get("set-cookie")).toContain("Max-Age=0");
    expect(unsupported.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("clears malformed and expired local admin handles", async () => {
    for (const cookie of [
      "__Host-ac_dev_admin_qa_session=malformed",
      `__Host-ac_dev_admin_qa_session=${"l".repeat(43)}`,
    ]) {
      const response = await proxyDevelopmentAdminApi(
        request("/v1/me", { headers: { cookie } }),
        vi.fn<DevAdminFetch>(),
        bridgeEnvironment,
        "development",
        new InMemoryDevelopmentAdminSessionStore(),
      );
      expect(response.status).toBe(401);
      expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
    }
  });

  it("rejects a drifting host-only session contract", async () => {
    const fetcher = vi.fn<DevAdminFetch>().mockResolvedValue(
      Response.json(
        { authenticated: true },
        {
          headers: {
            "set-cookie": `__Host-ac_session=${STAGING_SESSION}; Domain=authorityclosers.com; Secure; HttpOnly; SameSite=Lax; Path=/`,
          },
        },
      ),
    );
    const response = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login"),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      code: "admin_bridge_session_contract_invalid",
    });
  });
});

describe("development admin session store", () => {
  it("expires and caps ephemeral mappings", () => {
    let now = 0;
    const store = new InMemoryDevelopmentAdminSessionStore(() => now);
    for (let index = 0; index < 5; index += 1) {
      store.set(`l${index}`, `s${index}`);
    }
    expect(store.get("l0")).toBeNull();
    expect(store.get("l4")).toBe("s4");
    now = 8 * 60 * 60 * 1000;
    expect(store.get("l4")).toBeNull();
  });
});

describe("loopback admin proxy", () => {
  it("preserves the normal local API path without accepting a remote origin", async () => {
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockResolvedValue(Response.json({ ok: true }));
    const response = await proxyDevelopmentAdminApi(
      request("/v1/me"),
      fetcher,
      { AC_API_URL: "http://localhost:8000" },
      "development",
    );
    expect(response.status).toBe(200);
    expect(String(fetcher.mock.calls[0][0])).toBe(
      "http://localhost:8000/v1/me",
    );
  });
});
