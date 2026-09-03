import { describe, expect, it, vi } from "vitest";

import {
  InMemoryDevelopmentBridgeSessionStore,
  isStagingAuthenticatedBridge,
  isStagingAuthenticatedLearnerRequest,
  isStagingPublicCatalogPreview,
  isStagingPublicCatalogRequest,
  proxyDevelopmentLearnerApi,
  resolveDevAuthBridgeConfig,
  resolveDevApiTarget,
} from "./dev-api-proxy";

const AUTH_BRIDGE_ENV = {
  AC_DEV_AUTH_BRIDGE_ENABLED: "true",
  AC_DEV_AUTH_BRIDGE_ORIGIN: "http://localhost:3000",
  AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN: "https://staging.authorityclosers.com",
};
const STAGING_SESSION = "s".repeat(43);
const LOCAL_SESSION = "l".repeat(43);

function stagingSessionCookie(
  token = STAGING_SESSION,
  attributes = "Max-Age=28800; Path=/; HttpOnly; SameSite=Lax; Secure",
): string {
  return `__Host-ac_session=${token}; ${attributes}`;
}

function bridgeRequest(
  path: string,
  init: RequestInit = {},
  origin = "http://localhost:3000",
): Request {
  const headers = new Headers(init.headers);
  if (!headers.has("origin")) headers.set("origin", origin);
  return new Request(`http://localhost:3000${path}`, {
    ...init,
    headers,
  });
}

function localSessionFromResponse(response: Response): string {
  const cookie = response.headers.get("set-cookie") ?? "";
  const match = /^__Host-ac_dev_qa_session=([^;]+)/.exec(cookie);
  expect(match).not.toBeNull();
  return match?.[1] ?? "";
}

describe("development learner API proxy", () => {
  it("is disabled outside development", () => {
    expect(
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "production",
      ),
    ).toBeNull();
    expect(
      resolveDevAuthBridgeConfig(AUTH_BRIDGE_ENV, "production"),
    ).toBeNull();
  });

  it("keeps the authenticated bridge opt-in and exact-origin constrained", () => {
    expect(resolveDevAuthBridgeConfig({}, "development")).toBeNull();
    expect(
      resolveDevAuthBridgeConfig(
        { ...AUTH_BRIDGE_ENV, AC_DEV_AUTH_BRIDGE_ENABLED: "false" },
        "development",
      ),
    ).toBeNull();
    expect(resolveDevAuthBridgeConfig(AUTH_BRIDGE_ENV, "development")).toEqual({
      browserOrigin: "http://localhost:3000",
      upstreamOrigin: "https://staging.authorityclosers.com",
    });
    expect(resolveDevApiTarget(AUTH_BRIDGE_ENV, "development")).toEqual({
      mode: "staging-authenticated",
      origin: "https://staging.authorityclosers.com",
      browserOrigin: "http://localhost:3000",
    });
    expect(isStagingAuthenticatedBridge(AUTH_BRIDGE_ENV, "development")).toBe(
      true,
    );
    expect(isStagingAuthenticatedBridge(AUTH_BRIDGE_ENV, "production")).toBe(
      false,
    );
  });

  it("rejects missing, non-loopback, API-host, production, and pathful bridge targets", () => {
    expect(() =>
      resolveDevAuthBridgeConfig(
        { AC_DEV_AUTH_BRIDGE_ENABLED: "true" },
        "development",
      ),
    ).toThrow("AC_DEV_AUTH_BRIDGE_ORIGIN is required");
    expect(() =>
      resolveDevAuthBridgeConfig(
        { ...AUTH_BRIDGE_ENV, AC_DEV_AUTH_BRIDGE_ORIGIN: "https://qa.example" },
        "development",
      ),
    ).toThrow("exact http(s) loopback origin");
    for (const upstreamOrigin of [
      "https://api-staging.authorityclosers.com",
      "https://authorityclosers.com",
      "https://staging.authorityclosers.com/private",
    ]) {
      expect(() =>
        resolveDevAuthBridgeConfig(
          {
            ...AUTH_BRIDGE_ENV,
            AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN: upstreamOrigin,
          },
          "development",
        ),
      ).toThrow(/origin/);
    }
  });

  it("identifies only the exact development staging catalog mode", () => {
    expect(
      isStagingPublicCatalogPreview(
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "development",
      ),
    ).toBe(true);
    expect(
      isStagingPublicCatalogPreview(
        { AC_DEV_API_ORIGIN: "http://localhost:8000" },
        "development",
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogPreview(
        { AC_DEV_API_ORIGIN: "https://api.authorityclosers.com" },
        "development",
      ),
    ).toBe(false);
  });

  it("accepts loopback and the exact staging API but rejects arbitrary and production origins", () => {
    expect(resolveDevApiTarget({}, "development")).toEqual({
      mode: "local",
      origin: "http://127.0.0.1:8000",
    });
    expect(
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "development",
      ),
    ).toEqual({
      mode: "staging-public-catalog",
      origin: "https://api-staging.authorityclosers.com",
    });
    expect(() =>
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://api.authorityclosers.com" },
        "development",
      ),
    ).toThrow("Production and arbitrary remote origins are forbidden");
    expect(() =>
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://user:secret@localhost:8000/path" },
        "development",
      ),
    ).toThrow("only a scheme, host, and optional port");
  });

  it("cannot enable a hidden full-access staging proxy mode", () => {
    expect(
      resolveDevApiTarget(
        {
          AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com",
          AC_DEV_STAGING_FULL_ACCESS: "true",
        },
        "development",
      ),
    ).toEqual({
      mode: "staging-public-catalog",
      origin: "https://api-staging.authorityclosers.com",
    });
  });

  it("treats blank optional configuration as unset", () => {
    expect(
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "  ", AC_API_URL: "http://localhost:8000/" },
        "development",
      ),
    ).toEqual({ mode: "local", origin: "http://localhost:8000" });
  });

  it("allows only bounded catalog URLs for remote staging preview", () => {
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=50"),
      ),
    ).toBe(true);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs/free-course"),
      ),
    ).toBe(true);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=500"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=50&limit=51"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=050"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs/free-course/private"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(new URL("http://localhost:3000/v1/me")),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs/%2F"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL(`http://localhost:3000/v1/programs/${"a".repeat(121)}`),
      ),
    ).toBe(false);
  });

  it("allows only the learner routes used by the real UI", () => {
    for (const [method, path] of [
      ["POST", "/v1/auth/password/login"],
      ["POST", "/v1/auth/logout"],
      ["GET", "/v1/me"],
      ["GET", "/v1/context"],
      ["POST", "/v1/context"],
      ["GET", "/v1/onboarding"],
      ["PUT", "/v1/onboarding"],
      ["POST", "/v1/enrollments/free"],
      ["GET", "/v1/learning/lesson-1"],
      [
        "GET",
        "/v1/learning/lesson-1?enrollment_id=enrollment-1&program_version_id=version-1",
      ],
      ["GET", "/v1/activities/activity-1"],
      ["PUT", "/v1/activities/activity-1/draft"],
      ["POST", "/v1/activities/activity-1/evidence"],
      ["GET", "/v1/certificates/certificate-1"],
      ["GET", "/v1/programs"],
    ] as const) {
      expect(
        isStagingAuthenticatedLearnerRequest(
          new URL(`http://localhost:3000${path}`),
          method,
        ),
      ).toBe(true);
    }

    for (const [method, path] of [
      ["GET", "/v1/admin/people"],
      ["GET", "/v1/auth/google/start"],
      ["POST", "/v1/auth/password/recovery"],
      ["POST", "/v1/auth/password/register"],
      ["GET", "/v1/activities/activity-1/draft/"],
      ["POST", "/v1/activities/activity-1/evidence/extra"],
      ["GET", "/v1/learning/lesson-1?enrollment_id=one"],
      ["GET", "/v1/me?include=admin"],
      ["POST", "/v1/programs"],
    ] as const) {
      expect(
        isStagingAuthenticatedLearnerRequest(
          new URL(`http://localhost:3000${path}`),
          method,
        ),
      ).toBe(false);
    }
  });

  it("strips credentials and cookies in the staging catalog mode", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(
          "https://api-staging.authorityclosers.com/v1/programs?limit=50",
        );
        const headers = new Headers(init?.headers);
        expect(headers.has("cookie")).toBe(false);
        expect(headers.has("authorization")).toBe(false);
        expect(headers.has("x-api-key")).toBe(false);
        expect(headers.has("referer")).toBe(false);
        return Response.json(
          { items: [], next_cursor: null },
          {
            headers: {
              "content-encoding": "gzip",
              "set-cookie": "should-not-return=1",
            },
          },
        );
      },
    );
    const result = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=50", {
        headers: {
          authorization: "Bearer secret",
          cookie: "__Host-ac_session=secret",
          "x-api-key": "should-not-forward",
          referer: "http://localhost:3000/private?token=should-not-forward",
        },
      }),
      fetcher,
      { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
      "development",
    );

    expect(result.status).toBe(200);
    expect(result.headers.get("set-cookie")).toBeNull();
    expect(result.headers.get("content-encoding")).toBeNull();
    expect(result.headers.get("x-ac-dev-data-mode")).toBe(
      "staging-public-catalog",
    );
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("does not follow or expose redirects from the staging preview", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(null, {
          status: 302,
          headers: { location: "https://authorityclosers.com/private" },
        }),
    );
    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=50"),
      fetcher,
      { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
      "development",
    );

    expect(response.status).toBe(502);
    expect(response.headers.get("location")).toBeNull();
  });

  it("does not call upstream when the incoming request is already cancelled", async () => {
    const fetcher = vi.fn();
    const controller = new AbortController();
    controller.abort();

    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=50", {
        signal: controller.signal,
      }),
      fetcher,
      { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
      "development",
    );

    expect(response.status).toBe(504);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("blocks private reads and every mutation before remote staging is called", async () => {
    const fetcher = vi.fn();
    for (const request of [
      new Request("http://localhost:3000/v1/me"),
      new Request("http://localhost:3000/v1/programs", { method: "POST" }),
    ]) {
      const result = await proxyDevelopmentLearnerApi(
        request,
        fetcher,
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "development",
      );
      expect(result.status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not activate the authenticated bridge outside development", async () => {
    const fetcher = vi.fn();
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/me"),
      fetcher,
      AUTH_BRIDGE_ENV,
      "production",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(response.status).toBe(404);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("logs in through staging's normal cookie contract without returning its cookie", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(
          "https://staging.authorityclosers.com/v1/auth/password/login",
        );
        const headers = new Headers(init?.headers);
        expect(headers.get("origin")).toBe(
          "https://staging.authorityclosers.com",
        );
        expect(headers.has("cookie")).toBe(false);
        expect(headers.has("authorization")).toBe(false);
        expect(headers.has("x-api-key")).toBe(false);
        expect(headers.has("referer")).toBe(false);
        expect(await new Response(init?.body).text()).toContain("email");
        return new Response(
          JSON.stringify({
            authenticated: true,
            person_id: "person-1",
            email: "learner@example.test",
            display_name: "Learner",
          }),
          {
            status: 200,
            headers: {
              "content-type": "application/json",
              "set-cookie": stagingSessionCookie(),
            },
          },
        );
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/auth/password/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: "learner@example.test",
          password: "test-only",
        }),
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );

    const localSession = localSessionFromResponse(response);
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
    expect(response.headers.get("set-cookie")).toContain("SameSite=Lax");
    expect(response.headers.get("set-cookie")).toContain("Secure");
    expect(response.headers.get("set-cookie")).not.toContain(
      "__Host-ac_session",
    );
    expect(response.headers.get("set-cookie")).not.toContain(STAGING_SESSION);
    expect(store.get(localSession)).toBe(STAGING_SESSION);
    expect(await response.json()).toMatchObject({ authenticated: true });
  });

  it("maps the local HttpOnly session to staging server-side for learner reads", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    store.set(LOCAL_SESSION, STAGING_SESSION);
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(
          "https://staging.authorityclosers.com/v1/me",
        );
        const headers = new Headers(init?.headers);
        expect(headers.get("origin")).toBe(
          "https://staging.authorityclosers.com",
        );
        expect(headers.get("cookie")).toBe(
          `__Host-ac_session=${STAGING_SESSION}`,
        );
        expect(headers.has("authorization")).toBe(false);
        expect(headers.has("referer")).toBe(false);
        return new Response(JSON.stringify({ person_id: "person-1" }), {
          headers: {
            "content-type": "application/json",
            "set-cookie": stagingSessionCookie("r".repeat(43)),
          },
        });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/me", {
        headers: { cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}` },
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("x-ac-dev-data-mode")).toBe(
      "staging-authenticated",
    );
    expect(await response.json()).toEqual({ person_id: "person-1" });
  });

  it("keeps anonymous public catalog reads available while the bridge is enabled", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(
          "https://api-staging.authorityclosers.com/v1/programs?limit=50",
        );
        const headers = new Headers(init?.headers);
        expect(headers.has("cookie")).toBe(false);
        expect(headers.has("authorization")).toBe(false);
        return Response.json({
          items: [{ slug: "authority-closers-free-course" }],
        });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/programs?limit=50"),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-ac-dev-data-mode")).toBe(
      "staging-public-catalog",
    );
    expect(await response.json()).toEqual({
      items: [{ slug: "authority-closers-free-course" }],
    });
  });

  it("forwards only the learner mutation contract and keeps browser credentials out", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    store.set(LOCAL_SESSION, STAGING_SESSION);
    const body = JSON.stringify({ response: "draft response" });
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        const headers = new Headers(init?.headers);
        expect(headers.get("if-match")).toBe('"version-1"');
        expect(headers.get("idempotency-key")).toBe("idempotency-1");
        expect(headers.get("cookie")).toBe(
          `__Host-ac_session=${STAGING_SESSION}`,
        );
        expect(headers.has("authorization")).toBe(false);
        expect(headers.has("x-api-key")).toBe(false);
        expect(await new Response(init?.body).text()).toBe(body);
        return Response.json({ accepted: true });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/activities/activity-1/draft", {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
          "if-match": '"version-1"',
          "idempotency-key": "idempotency-1",
          referer: "http://localhost:3000/private?token=do-not-forward",
        },
        body,
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-ac-dev-data-mode")).toBe(
      "staging-authenticated",
    );
  });

  it("fails closed for wrong origins, direct staging cookies, client credentials, and invalid local sessions", async () => {
    const fetcher = vi.fn();
    const cases = [
      bridgeRequest("/v1/me", {}, "http://127.0.0.1:3000"),
      new Request("http://localhost:3000/v1/enrollments/free", {
        method: "POST",
      }),
      bridgeRequest("/v1/me"),
      bridgeRequest("/v1/me", {
        headers: { cookie: `__Host-ac_session=${STAGING_SESSION}` },
      }),
      bridgeRequest("/v1/me", {
        headers: {
          authorization: "Bearer should-not-be-used",
          cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
        },
      }),
      bridgeRequest("/v1/me", {
        headers: { cookie: "__Host-ac_dev_qa_session=malformed" },
      }),
    ];
    const statuses: number[] = [];
    for (const request of cases) {
      const response = await proxyDevelopmentLearnerApi(
        request,
        fetcher,
        AUTH_BRIDGE_ENV,
        "development",
        new InMemoryDevelopmentBridgeSessionStore(),
      );
      statuses.push(response.status);
    }
    expect(statuses).toEqual([403, 403, 401, 403, 400, 401]);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("expires the server-side mapping after upstream 401 and clears the local cookie", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    store.set(LOCAL_SESSION, STAGING_SESSION);
    const fetcher = vi.fn(async () => new Response(null, { status: 401 }));
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/me", {
        headers: { cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}` },
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );
    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
    expect(store.get(LOCAL_SESSION)).toBeNull();
  });

  it("logs out through staging and clears both server-side and browser-local state", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    store.set(LOCAL_SESSION, STAGING_SESSION);
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        const headers = new Headers(init?.headers);
        expect(headers.get("cookie")).toBe(
          `__Host-ac_session=${STAGING_SESSION}`,
        );
        return new Response(null, {
          status: 204,
          headers: { "set-cookie": stagingSessionCookie() },
        });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/auth/logout", {
        method: "POST",
        headers: { cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}` },
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );
    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
    expect(response.headers.get("set-cookie")).not.toContain(
      "__Host-ac_session",
    );
    expect(store.get(LOCAL_SESSION)).toBeNull();
  });

  it("rejects a successful staging login without a valid host-only session cookie", async () => {
    for (const cookie of [
      undefined,
      stagingSessionCookie(
        STAGING_SESSION,
        "Path=/; HttpOnly; SameSite=Lax; Secure; Domain=example.test",
      ),
      stagingSessionCookie(STAGING_SESSION, "Path=/; HttpOnly; SameSite=Lax"),
    ]) {
      const store = new InMemoryDevelopmentBridgeSessionStore();
      const fetcher = vi.fn(async () => {
        const response = new Response(JSON.stringify({ authenticated: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
        if (cookie) response.headers.append("set-cookie", cookie);
        return response;
      });
      const response = await proxyDevelopmentLearnerApi(
        bridgeRequest("/v1/auth/password/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            email: "learner@example.test",
            password: "test-only",
          }),
        }),
        fetcher,
        AUTH_BRIDGE_ENV,
        "development",
        store,
      );
      expect(response.status).toBe(502);
      expect(response.headers.get("set-cookie")).toBeNull();
    }
  });

  it("rejects duplicate upstream staging session cookies", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    const fetcher = vi.fn(async () => {
      const response = new Response(JSON.stringify({ authenticated: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
      response.headers.append("set-cookie", stagingSessionCookie());
      response.headers.append(
        "set-cookie",
        stagingSessionCookie("r".repeat(43)),
      );
      return response;
    });
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/auth/password/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: "learner@example.test",
          password: "test-only",
        }),
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );
    expect(response.status).toBe(502);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("does not expose a bearer token from a drifting login response", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            authenticated: true,
            access_token: "token-in-body",
          }),
          {
            status: 200,
            headers: {
              "content-type": "application/json",
              "set-cookie": stagingSessionCookie(),
            },
          },
        ),
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/auth/password/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: "learner@example.test",
          password: "test-only",
        }),
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );
    expect(response.status).toBe(502);
    expect((await response.text()).toLowerCase()).not.toContain(
      "token-in-body",
    );
  });

  it("hides upstream errors and redirects instead of exporting remote details", async () => {
    const throwingFetcher = vi.fn(async () => {
      throw new Error("upstream secret should stay server-side");
    });
    const errorResponse = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/auth/password/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: "learner@example.test",
          password: "test-only",
        }),
      }),
      throwingFetcher,
      AUTH_BRIDGE_ENV,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(errorResponse.status).toBe(502);
    expect(await errorResponse.text()).not.toContain("upstream secret");

    const redirectResponse = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/auth/password/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: "learner@example.test",
          password: "test-only",
        }),
      }),
      vi.fn(
        async () =>
          new Response(null, {
            status: 302,
            headers: {
              location: "https://staging.authorityclosers.com/private",
            },
          }),
      ),
      AUTH_BRIDGE_ENV,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(redirectResponse.status).toBe(502);
    expect(redirectResponse.headers.get("location")).toBeNull();
  });

  it("preserves the browser Origin and cookies for the loopback API", async () => {
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        const headers = new Headers(init?.headers);
        expect(headers.get("origin")).toBe("http://localhost:3000");
        expect(headers.get("cookie")).toBe("local-session=value");
        expect(init?.method).toBe("POST");
        return Response.json({ accepted: true });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/enrollments/free", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          cookie: "local-session=value",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ program_version_id: "version-1" }),
      }),
      fetcher,
      { AC_DEV_API_ORIGIN: "http://127.0.0.1:8000" },
      "development",
    );
    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
