import { createServer } from "node:http";

import { describe, expect, it, vi } from "vitest";

import {
  developmentAdminLoginMode,
  proxyDevelopmentAdminApi,
  resolveDevAdminApiTarget,
  type DevAdminFetch,
} from "./dev-api-proxy";
import { loginLocalAdmin } from "./local-admin-login";
import { fetchLocalAdminWire } from "./local-admin-transport";

const PERSON = "11111111-1111-4111-8111-111111111111";
const TENANT = "22222222-2222-4222-8222-222222222222";
const SESSION = "33333333-3333-4333-8333-333333333333";
const PROGRAM = "44444444-4444-4444-8444-444444444444";
const ORIGIN = "http://admin.localhost:3101";
const environment = {
  AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
  AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: ORIGIN,
  AC_DEV_ADMIN_API_ORIGIN: "http://127.0.0.1:8000",
};

describe("explicit local admin sandbox", () => {
  it("requires opt-in, development, exact origin pair and no staging bridge", () => {
    expect(resolveDevAdminApiTarget(environment, "development")).toEqual({
      mode: "local-sandbox",
      origin: environment.AC_DEV_ADMIN_API_ORIGIN,
      browserOrigin: ORIGIN,
    });
    expect(developmentAdminLoginMode({}, "development")).toBeNull();
    expect(developmentAdminLoginMode(environment, "production")).toBeNull();
    for (const change of [
      { AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: undefined },
      { AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: "http://evil.test:3101" },
      { AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: "http://admin.localhost:3102" },
      { AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: ORIGIN + "/login" },
      { AC_DEV_ADMIN_API_ORIGIN: undefined },
      { AC_DEV_ADMIN_API_ORIGIN: "https://admin-staging.authorityclosers.com" },
      { AC_DEV_ADMIN_API_ORIGIN: "http://localhost:8000" },
      { AC_DEV_ADMIN_API_ORIGIN: "http://127.0.0.1:8001" },
      { AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true" },
    ]) {
      expect(() =>
        resolveDevAdminApiTarget({ ...environment, ...change }, "development"),
      ).toThrow();
      expect(
        developmentAdminLoginMode({ ...environment, ...change }, "development"),
      ).toBeNull();
    }
  });

  it("sets server-owned wire host and origin, forwards only real local cookie and command guards", async () => {
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockResolvedValue(Response.json({ ok: true }));
    const response = await proxyDevelopmentAdminApi(
      new Request(ORIGIN + `/v1/admin/program-versions/${PROGRAM}/publish`, {
        method: "POST",
        headers: {
          host: "admin.localhost:3101",
          origin: ORIGIN,
          "x-forwarded-host": "admin.localhost:3101",
          "x-forwarded-proto": "http",
          forwarded: "host=evil.test",
          "x-admin-role": "owner",
          authorization: "Bearer untrusted",
          cookie:
            "ac_session=local-fixture; CF_Authorization=remote; __Host-ac_session=remote; __Host-ac_dev_admin_qa_session=bridge",
          "if-match": '"fixture"',
          "idempotency-key": "fixture-key",
          "content-type": "application/json",
        },
        body: JSON.stringify({ reason: "local test" }),
      }),
      fetcher,
      environment,
      "development",
    );
    expect(response.status).toBe(200);
    expect(String(fetcher.mock.calls[0][0])).toBe(
      `http://127.0.0.1:8000/v1/admin/program-versions/${PROGRAM}/publish`,
    );
    const headers = new Headers(fetcher.mock.calls[0][1]?.headers);
    expect(headers.get("host")).toBe("admin.localhost:3101");
    expect(headers.get("origin")).toBe(ORIGIN);
    expect(headers.get("cookie")).toBe("ac_session=local-fixture");
    expect(headers.get("if-match")).toBe('"fixture"');
    expect(headers.get("idempotency-key")).toBe("fixture-key");
    for (const name of [
      "authorization",
      "forwarded",
      "x-forwarded-host",
      "x-forwarded-proto",
      "x-admin-role",
    ])
      expect(headers.has(name)).toBe(false);
  });

  it("rejects mismatched or absent mutation origins before opening any upstream connection", async () => {
    const fetcher = vi.fn<DevAdminFetch>();
    for (const headers of [
      {},
      { origin: "http://learner.localhost:3100" },
      { origin: ORIGIN, host: "evil.test" },
      { origin: ORIGIN, "x-forwarded-host": "evil.test" },
      { origin: ORIGIN, "x-forwarded-proto": "https" },
    ] as Record<string, string>[]) {
      const response = await proxyDevelopmentAdminApi(
        new Request(ORIGIN + "/v1/context", { method: "POST", headers }),
        fetcher,
        environment,
        "development",
      );
      expect(response.status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("allows canonical context selection only in the sandbox; denies unrelated or query-shaped routes", async () => {
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockImplementation(() => Promise.resolve(Response.json({ ok: true })));
    for (const [path, method, status] of [
      ["/v1/context", "POST", 200],
      ["/v1/me/studio-access", "GET", 200],
      ["/v1/context?tenant_id=forged", "POST", 403],
      ["/v1/auth/password/register", "POST", 403],
      ["/v1/dev-bridge/health", "GET", 403],
      ["/v1/admin/unknown", "POST", 403],
    ] as const) {
      const response = await proxyDevelopmentAdminApi(
        new Request(ORIGIN + path, { method, headers: { origin: ORIGIN } }),
        fetcher,
        environment,
        "development",
      );
      expect(response.status).toBe(status);
    }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe("local password and tenant selection", () => {
  function identityFetcher(hasStudio = true, selectedTenant = TENANT) {
    return vi.fn<typeof fetch>().mockImplementation((input) => {
      const path = String(input);
      if (path === "/v1/me")
        return Promise.resolve(
          Response.json({
            person_id: PERSON,
            email: "coach@example.test",
            display_name: null,
            email_verified_at: "2026-09-07T00:00:00Z",
            selected_tenant_id: selectedTenant,
            membership_role: "learner",
            permissions: [],
          }),
        );
      if (path === "/v1/context")
        return Promise.resolve(
          Response.json({
            person_id: PERSON,
            session_id: SESSION,
            tenant_id: selectedTenant,
            membership_role: "learner",
            permissions: [],
          }),
        );
      if (path === "/v1/me/studio-access")
        return Promise.resolve(
          Response.json({
            person_id: PERSON,
            session_id: SESSION,
            tenant_id: selectedTenant,
            studio_capabilities: hasStudio
              ? [
                  {
                    permission: "catalog_read",
                    scope_kind: "program",
                    tenant_id: selectedTenant,
                    program_id: PROGRAM,
                  },
                ]
              : [],
          }),
        );
      return Promise.resolve(Response.json({ authenticated: true }));
    });
  }

  it("authenticates normally then selects a real tenant and verifies scoped learner admission", async () => {
    const fetcher = identityFetcher();
    await loginLocalAdmin("coach@example.test", "test-only", TENANT, fetcher);
    expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
      "/v1/auth/password/login",
      "/v1/context",
      "/v1/me",
      "/v1/context",
      "/v1/me/studio-access",
    ]);
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({
      tenant_id: TENANT,
    });
    expect(
      fetcher.mock.calls.every(
        ([, init]) => init?.credentials === "same-origin",
      ),
    ).toBe(true);
    expect(
      fetcher.mock.calls.every(
        ([, init]) => !new Headers(init?.headers).has("authorization"),
      ),
    ).toBe(true);
  });

  it("does not send passwords for an invalid tenant ID or admit a missing/mismatched scope", async () => {
    const invalid = identityFetcher();
    await expect(
      loginLocalAdmin("coach@example.test", "test-only", "invalid", invalid),
    ).rejects.toThrow();
    expect(invalid).not.toHaveBeenCalled();
    for (const fetcher of [
      identityFetcher(false),
      identityFetcher(true, PROGRAM),
    ]) {
      await expect(
        loginLocalAdmin("coach@example.test", "test-only", TENANT, fetcher),
      ).rejects.toThrow();
      expect(fetcher.mock.calls.at(-1)?.[0]).toBe("/v1/auth/logout");
    }
  });

  it("stops after rejected credentials and cleans up after a rejected tenant selection", async () => {
    const rejectedLogin = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 401 }));
    await expect(
      loginLocalAdmin("coach@example.test", "test-only", TENANT, rejectedLogin),
    ).rejects.toThrow("could not be verified");
    expect(rejectedLogin).toHaveBeenCalledOnce();
    const rejectedContext = identityFetcher();
    rejectedContext
      .mockResolvedValueOnce(Response.json({ authenticated: true }))
      .mockResolvedValueOnce(new Response(null, { status: 403 }));
    await expect(
      loginLocalAdmin(
        "coach@example.test",
        "test-only",
        TENANT,
        rejectedContext,
      ),
    ).rejects.toThrow("tenant is unavailable");
    expect(rejectedContext.mock.calls.map(([path]) => path)).toEqual([
      "/v1/auth/password/login",
      "/v1/context",
      "/v1/auth/logout",
    ]);
  });
});

describe("local admin real HTTP wire", () => {
  it("preserves trusted Host and genuine cookie bytes without redirects on a numeric loopback connection", async () => {
    const observations: Array<{
      host?: string;
      cookie?: string;
      path?: string;
    }> = [];
    const server = createServer((request, response) => {
      observations.push({
        host: request.headers.host,
        cookie: request.headers.cookie,
        path: request.url,
      });
      response.writeHead(302, {
        location: "https://remote.example.test",
        "set-cookie":
          "ac_session=local-fixture; HttpOnly; Path=/; SameSite=Lax",
      });
      response.end("redirect is not followed");
    });
    await new Promise<void>((resolve) =>
      server.listen(0, "127.0.0.1", resolve),
    );
    try {
      const address = server.address();
      if (!address || typeof address === "string")
        throw new Error("Local test socket unavailable");
      const response = await fetchLocalAdminWire(
        new URL(`http://127.0.0.1:${address.port}/v1/context`),
        {
          method: "GET",
          headers: {
            host: "admin.localhost:3101",
            cookie: "ac_session=local-fixture",
          },
        },
      );
      expect(response.status).toBe(302);
      expect(response.headers.get("set-cookie")).toBe(
        "ac_session=local-fixture; HttpOnly; Path=/; SameSite=Lax",
      );
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(observations).toEqual([
        {
          host: "admin.localhost:3101",
          cookie: "ac_session=local-fixture",
          path: "/v1/context",
        },
      ]);
    } finally {
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });

  it("rejects remote, DNS and credentialed transport destinations before IO", async () => {
    for (const url of [
      "https://remote.example.test",
      "http://localhost:8000",
      "http://user:password@127.0.0.1:8000",
    ]) {
      await expect(fetchLocalAdminWire(url)).rejects.toThrow(
        "numeric HTTP loopback",
      );
    }
  });
});
