import { describe, expect, it, vi } from "vitest";

import {
  InMemoryDevelopmentAdminSessionStore,
  isStagingAdminRequest,
  isCoachApiRequest,
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

it("admits only the bounded Admin directory POST without client scope", () => {
  expect(
    isStagingAdminRequest(
      new URL("https://admin.example.test/v1/admin/people/directory"),
      "POST",
    ),
  ).toBe(true);
  expect(
    isStagingAdminRequest(
      new URL("https://admin.example.test/v1/admin/people/directory"),
      "GET",
    ),
  ).toBe(false);
  expect(
    isStagingAdminRequest(
      new URL(
        "https://admin.example.test/v1/admin/people/directory?tenant_id=" +
          ADMIN_TENANT,
      ),
      "POST",
    ),
  ).toBe(false);
  expect(
    isCoachApiRequest(
      new URL("https://coach.example.test/v1/admin/people/directory"),
      "POST",
    ),
  ).toBe(false);
});

it("admits the dedicated reviewer API while rejecting scope selectors", () => {
  const assignment = "44444444-4444-4444-8444-444444444444";
  expect(isStagingAdminRequest(new URL("http://admin.localhost:3101/v1/reviewer/me"), "GET")).toBe(true);
  expect(isStagingAdminRequest(new URL("http://admin.localhost:3101/v1/reviewer/auth/request"), "POST")).toBe(true);
  expect(isStagingAdminRequest(new URL(`http://admin.localhost:3101/v1/reviewer/review-assignments/${assignment}/submissions`), "POST")).toBe(true);
  expect(isStagingAdminRequest(new URL("http://admin.localhost:3101/v1/reviewer/review-assignments?tenant_id=other"), "GET")).toBe(false);
  expect(isStagingAdminRequest(new URL(`http://admin.localhost:3101/v1/reviewer/review-assignments/${assignment}?include=transcript`), "GET")).toBe(false);
});

describe("course-scoped video upload admission proxy", () => {
  const prefix = `/v1/admin/studio/programs/${TARGET_ID}/video-uploads`;
  it("admits only exact create and status methods on Admin and Coach", () => {
    for (const admit of [isStagingAdminRequest, isCoachApiRequest]) {
      for (const [path, method, expected] of [
        [prefix, "POST", true],
        [`${prefix}/${ADMIN_SESSION}`, "GET", true],
        [prefix, "GET", false],
        [`${prefix}/${ADMIN_SESSION}`, "POST", false],
        [`${prefix}/${ADMIN_SESSION}/complete`, "POST", false],
        [`${prefix}?tenant_id=${ADMIN_TENANT}`, "POST", false],
        [`${prefix}/invalid`, "GET", false],
        [prefix.replace(TARGET_ID, "invalid"), "POST", false],
      ] as const) {
        expect(
          admit(new URL(path, "http://coach.localhost:3102"), method),
        ).toBe(expected);
      }
    }
  });
});

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

function studioAccess() {
  return {
    person_id: ADMIN_PERSON,
    session_id: ADMIN_SESSION,
    tenant_id: ADMIN_TENANT,
    studio_capabilities: [],
  };
}

function successfulLoginFetcher(
  role: "owner" | "admin" | "support" | "learner" = "owner",
  identity: {
    me?: ReturnType<typeof adminMe>;
    context?: ReturnType<typeof adminContext>;
    access?: unknown;
  } = {},
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
      return Promise.resolve(Response.json(identity.me ?? adminMe(role)));
    }
    if (url.pathname === "/v1/context") {
      return Promise.resolve(
        Response.json(identity.context ?? adminContext(role)),
      );
    }
    if (url.pathname === "/v1/me/studio-access") {
      return Promise.resolve(Response.json(identity.access ?? studioAccess()));
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
    ["POST", "/v1/admin/learners/lookup", true],
    ["GET", "/v1/admin/learners/lookup", false],
    ["POST", "/v1/admin/learners/lookup?query=private", false],
    ["POST", "/v1/admin/learners/lookup?tenant_id=other", false],
    [
      "GET",
      `/v1/admin/learners/${TARGET_ID}/diagnosis?purpose=learner_support`,
      true,
    ],
    [
      "GET",
      `/v1/admin/learners/${TARGET_ID}/diagnosis?purpose=safeguarding_review`,
      true,
    ],
    [
      "GET",
      `/v1/admin/learners/${TARGET_ID}/diagnosis?purpose=accessibility_review`,
      true,
    ],
    [
      "POST",
      `/v1/admin/learners/${TARGET_ID}/diagnosis?purpose=learner_support`,
      false,
    ],
    ["GET", `/v1/admin/learners/${TARGET_ID}/diagnosis`, false],
    ["GET", `/v1/admin/learners/${TARGET_ID}/diagnosis?purpose=unknown`, false],
    [
      "GET",
      `/v1/admin/learners/${TARGET_ID}/diagnosis?purpose=learner_support&purpose=learner_support`,
      false,
    ],
    [
      "GET",
      `/v1/admin/learners/${TARGET_ID}/diagnosis?purpose=learner_support&tenant_id=other`,
      false,
    ],
    [
      "GET",
      "/v1/admin/learners/invalid/diagnosis?purpose=learner_support",
      false,
    ],
  ] as const)(
    "admits only exact People reads to Admin: %s %s",
    (method, path, expected) => {
      const url = new URL(path, "http://admin.localhost:3101");
      expect(isStagingAdminRequest(url, method)).toBe(expected);
      expect(isCoachApiRequest(url, method)).toBe(false);
    },
  );

  const videoRoutes: [string, string, boolean][] = [
    ["POST", "/v1/admin/studio/programs", true],
    ["POST", "/v1/admin/studio/programs?tenant_id=other", false],
    ["PATCH", "/v1/admin/studio/programs", false],
    ["DELETE", "/v1/admin/studio/programs", false],
    ["POST", `/v1/admin/studio/programs/${TARGET_ID}`, false],
    ["GET", `/v1/admin/studio/programs/${TARGET_ID}/videos`, true],
    ["GET", `/v1/admin/studio/programs/${TARGET_ID}/videos?limit=24`, true],
    [
      "GET",
      `/v1/admin/studio/programs/${TARGET_ID}/videos?limit=50&after=${ADMIN_SESSION}`,
      true,
    ],
    ["POST", `/v1/admin/studio/programs/${TARGET_ID}/videos`, false],
    ["GET", "/v1/admin/studio/programs/not-a-uuid/videos", false],
    ...[
      "limit=0",
      "limit=51",
      "limit=24&limit=24",
      "limit=1.5",
      "limit=NaN",
      "after=bad",
      `after=${ADMIN_SESSION}&after=${ADMIN_SESSION}`,
      "tenant_id=other",
      "include=all",
      "limit=24&force=true",
    ].map((query): [string, string, boolean] => [
      "GET",
      `/v1/admin/studio/programs/${TARGET_ID}/videos?${query}`,
      false,
    ]),
    [
      "GET",
      `/v1/admin/studio/programs/${TARGET_ID}/activities/${ADMIN_SESSION}/video`,
      true,
    ],
    [
      "POST",
      `/v1/admin/studio/programs/${TARGET_ID}/activities/${ADMIN_SESSION}/video`,
      true,
    ],
    [
      "PATCH",
      `/v1/admin/studio/programs/${TARGET_ID}/activities/${ADMIN_SESSION}/video`,
      false,
    ],
    [
      "DELETE",
      `/v1/admin/studio/programs/${TARGET_ID}/activities/${ADMIN_SESSION}/video`,
      false,
    ],
    [
      "GET",
      `/v1/admin/studio/programs/${TARGET_ID}/activities/bad/video`,
      false,
    ],
    [
      "POST",
      `/v1/admin/studio/programs/${TARGET_ID}/activities/${ADMIN_SESSION}/video?force=true`,
      false,
    ],
    ["POST", "/v1/media/activity-bindings", false],
  ];
  it.each(videoRoutes)(
    "scopes Studio video routes for Admin and Coach: %s %s",
    (method, path, expected) => {
      const url = new URL(`http://coach.localhost:3102${path}`);
      expect(isStagingAdminRequest(url, method)).toBe(expected);
      expect(isCoachApiRequest(url, method)).toBe(expected);
    },
  );
  it.each([
    ["GET", "/v1/dev-bridge/health"],
    ["POST", "/v1/auth/password/login"],
    ["POST", "/v1/auth/logout"],
    ["GET", "/v1/me"],
    ["GET", "/v1/context"],
    ["GET", "/v1/me/studio-access"],
    ["GET", "/v1/admin/studio/readiness"],
    ["GET", "/v1/admin/studio/programs"],
    ["POST", "/v1/admin/studio/programs"],
    ["GET", `/v1/admin/studio/programs/${TARGET_ID}`],
    ["POST", `/v1/admin/studio/program-versions/${TARGET_ID}/revision`],
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
    ["POST", "/v1/me/studio-access"],
    ["POST", "/v1/admin/studio/readiness"],
    ["PATCH", "/v1/admin/studio/programs"],
    ["POST", `/v1/admin/studio/programs/${TARGET_ID}`],
    ["GET", `/v1/admin/studio/program-versions/${TARGET_ID}/revision`],
    ["PATCH", `/v1/admin/studio/program-versions/${TARGET_ID}/revision`],
    [
      "POST",
      `/v1/admin/studio/program-versions/${TARGET_ID}/revision?copy=all`,
    ],
    ["POST", "/v1/admin/studio/program-versions/not-a-uuid/revision"],
    ["GET", "/v1/admin/studio/programs/not-a-uuid"],
    ["GET", `/v1/admin/studio/programs/${TARGET_ID}?include=drafts`],
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
  it("forwards only the dedicated reviewer cookie and returns a validated host-only cookie", async () => {
    const reviewerToken = "r".repeat(43);
    const reviewerState = "q".repeat(43);
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: {
            "content-type": "application/json",
              "set-cookie": `__Host-ac_reviewer_session=${reviewerToken}; Max-Age=28800; Path=/; HttpOnly; SameSite=Lax; Secure, __Host-ac_reviewer_state=${reviewerState}; Max-Age=900; Path=/; HttpOnly; SameSite=Lax; Secure`,
          },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          person_id: ADMIN_PERSON,
          email: "reviewer@example.test",
          display_name: "Reviewer",
          expires_at_epoch: 1_800_000_000,
        }),
      );
    const verified = await proxyDevelopmentAdminApi(
      request("/v1/reviewer/auth/verify", {
        method: "POST",
        headers: {
          origin: "http://localhost:3001",
          "content-type": "application/json",
          cookie: `__Host-ac_session=${"a".repeat(43)}; __Host-ac_reviewer_state=${reviewerState}`,
        },
        body: JSON.stringify({ token: "v".repeat(43) }),
      }),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    expect(verified.status).toBe(200);
    expect(verified.headers.get("set-cookie")).toContain(
      `__Host-ac_reviewer_session=${reviewerToken}`,
    );
    const verifyHeaders = new Headers(fetcher.mock.calls[0][1]?.headers);
    expect(verifyHeaders.get("cookie")).toBe(`CF_Authorization=${ACCESS_JWT}; __Host-ac_reviewer_state=${reviewerState}`);

    const me = await proxyDevelopmentAdminApi(
      request("/v1/reviewer/me", {
        headers: {
          cookie: `__Host-ac_session=${"a".repeat(43)}; __Host-ac_reviewer_session=${reviewerToken}; __Host-ac_reviewer_state=${reviewerState}`,
        },
      }),
      fetcher,
      bridgeEnvironment,
      "development",
    );
    expect(me.status).toBe(200);
    const meHeaders = new Headers(fetcher.mock.calls[1][1]?.headers);
    expect(meHeaders.get("cookie")).toBe(
      `CF_Authorization=${ACCESS_JWT}; __Host-ac_reviewer_session=${reviewerToken}; __Host-ac_reviewer_state=${reviewerState}`,
    );
  });

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
    expect(fetcher).toHaveBeenCalledTimes(4);
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
    expect(fetcher).toHaveBeenCalledTimes(5);
    expect(new URL(String(fetcher.mock.calls[4][0])).pathname).toBe(
      "/v1/auth/logout",
    );
  });

  it("maps a learner session only when its current Studio assignment is verified", async () => {
    const access = {
      ...studioAccess(),
      studio_capabilities: [
        {
          permission: "catalog_read",
          scope_kind: "program",
          tenant_id: ADMIN_TENANT,
          program_id: TARGET_ID,
        },
      ],
    };
    const fetcher = successfulLoginFetcher("learner", { access });
    const store = new InMemoryDevelopmentAdminSessionStore();
    const response = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login"),
      fetcher,
      bridgeEnvironment,
      "development",
      store,
    );
    expect(response.status).toBe(200);
    expect(store.get(localHandle(response))).toBe(STAGING_SESSION);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it.each([
    [
      "person ID mismatch",
      { context: { ...adminContext(), person_id: TARGET_ID } },
    ],
    [
      "tenant ID mismatch",
      { context: { ...adminContext(), tenant_id: TARGET_ID } },
    ],
    [
      "selected tenant mismatch",
      { me: { ...adminMe(), selected_tenant_id: TARGET_ID } },
    ],
    [
      "membership role mismatch",
      { me: { ...adminMe(), membership_role: "admin" as const } },
    ],
  ])("rejects admin identity/context %s", async (_label, identity) => {
    const fetcher = successfulLoginFetcher("owner", identity);
    const response = await proxyDevelopmentAdminApi(
      mutation("/v1/auth/password/login"),
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
    expect(fetcher).toHaveBeenCalledTimes(5);
    expect(new URL(String(fetcher.mock.calls[4][0])).pathname).toBe(
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

  it("times out a stalled admin request body before any upstream call", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn<DevAdminFetch>();
      const stalled = request("/v1/auth/password/login", {
        method: "POST",
        headers: {
          origin: "http://localhost:3001",
          "content-type": "application/json",
        },
        body: new ReadableStream<Uint8Array>({}),
        duplex: "half",
      } as RequestInit);
      const pending = proxyDevelopmentAdminApi(
        stalled,
        fetcher,
        bridgeEnvironment,
        "development",
        new InMemoryDevelopmentAdminSessionStore(),
      );

      await vi.advanceTimersByTimeAsync(12_001);
      const response = await pending;
      expect(response.status).toBe(504);
      expect(await response.json()).toMatchObject({
        code: "admin_bridge_upstream_timeout",
      });
      expect(fetcher).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not accept the learner bridge handle as admin authentication", async () => {
    const fetcher = vi.fn<DevAdminFetch>();
    const response = await proxyDevelopmentAdminApi(
      request("/v1/me", {
        headers: { cookie: `__Host-ac_dev_qa_session=${"l".repeat(43)}` },
      }),
      fetcher,
      bridgeEnvironment,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );

    expect(response.status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses only the admin handle when both localhost bridge cookies arrive", async () => {
    const handle = "h".repeat(43);
    const store = new InMemoryDevelopmentAdminSessionStore();
    store.set(handle, STAGING_SESSION);
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockImplementation((_input, init) => {
        const cookie = new Headers(init?.headers).get("cookie") ?? "";
        expect(cookie).toContain(`CF_Authorization=${ACCESS_JWT}`);
        expect(cookie).toContain(`__Host-ac_session=${STAGING_SESSION}`);
        expect(cookie).not.toContain("__Host-ac_dev_qa_session");
        expect(cookie).not.toContain("__Host-ac_dev_admin_qa_session");
        return Promise.resolve(Response.json(adminMe()));
      });
    const response = await proxyDevelopmentAdminApi(
      request("/v1/me", {
        headers: {
          cookie: [
            `__Host-ac_dev_admin_qa_session=${handle}`,
            `__Host-ac_dev_qa_session=${"l".repeat(43)}`,
          ].join("; "),
        },
      }),
      fetcher,
      bridgeEnvironment,
      "development",
      store,
    );

    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();
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
  it("preserves the normal local API path but strips both bridge handles", async () => {
    const fetcher = vi.fn<DevAdminFetch>().mockImplementation((input, init) => {
      expect(String(input)).toBe("http://localhost:8000/v1/me");
      expect(new Headers(init?.headers).get("cookie")).toBe(
        "local-admin-session=value",
      );
      return Promise.resolve(Response.json({ ok: true }));
    });
    const response = await proxyDevelopmentAdminApi(
      request("/v1/me", {
        headers: {
          cookie: [
            "local-admin-session=value",
            `__Host-ac_dev_admin_qa_session=${"a".repeat(43)}`,
            `__Host-ac_dev_qa_session=${"l".repeat(43)}`,
          ].join("; "),
        },
      }),
      fetcher,
      { AC_API_URL: "http://localhost:8000" },
      "development",
    );
    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("accepts loopback requests with Host matching admin.localhost origin", async () => {
    const adminEnv = {
      AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "http://admin.localhost:3001",
      AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://admin-staging.authorityclosers.com",
      AC_DEV_ADMIN_ACCESS_JWT:
        "t".repeat(32) + "." + "p".repeat(32) + "." + "s".repeat(32),
    };
    const fetcher = vi
      .fn<DevAdminFetch>()
      .mockImplementation(() =>
        Promise.resolve(
          Response.json(
            { code: "authentication_required" },
            { status: 401, headers: { "content-type": "application/json" } },
          ),
        ),
      );

    const response = await proxyDevelopmentAdminApi(
      new Request("http://localhost:3001/v1/dev-bridge/health", {
        headers: {
          host: "admin.localhost:3001",
        },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );

    expect(response.status).toBe(200);
    const body = (await response.json()) as {
      status: string;
      transport: string;
    };
    expect(body.status).toBe("ok");
    expect(body.transport).toBe("connected");

    // Omitting direct Host header while supplying only x-forwarded-host must be rejected
    const rejectedWithoutHost = await proxyDevelopmentAdminApi(
      new Request("http://127.0.0.1:3001/v1/dev-bridge/health", {
        headers: {
          "x-forwarded-host": "admin.localhost:3001",
          "x-forwarded-proto": "http",
        },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(rejectedWithoutHost.status).toBe(403);
  });

  it("rejects loopback requests with mismatched Host or non-loopback URLs", async () => {
    const adminEnv = {
      AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "http://admin.localhost:3001",
      AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://admin-staging.authorityclosers.com",
      AC_DEV_ADMIN_ACCESS_JWT:
        "t".repeat(32) + "." + "p".repeat(32) + "." + "s".repeat(32),
    };
    const fetcher = vi.fn<DevAdminFetch>();

    // Wrong host: learner.localhost
    const res1 = await proxyDevelopmentAdminApi(
      new Request("http://localhost:3001/v1/dev-bridge/health", {
        headers: { host: "learner.localhost:3000" },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(res1.status).toBe(403);

    // Wrong host: plain localhost when admin.localhost is expected
    const res2 = await proxyDevelopmentAdminApi(
      new Request("http://localhost:3001/v1/dev-bridge/health", {
        headers: { host: "localhost:3001" },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(res2.status).toBe(403);

    // Hostile non-loopback URL
    const res3 = await proxyDevelopmentAdminApi(
      new Request("http://evil.com/v1/dev-bridge/health", {
        headers: { host: "admin.localhost:3001" },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(res3.status).toBe(403);

    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects conflicting or spoofed forwarded headers even if direct Host or forwarded-host looks valid", async () => {
    const adminEnv = {
      AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "http://admin.localhost:3001",
      AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://admin-staging.authorityclosers.com",
      AC_DEV_ADMIN_ACCESS_JWT:
        "t".repeat(32) + "." + "p".repeat(32) + "." + "s".repeat(32),
    };
    const fetcher = vi.fn<DevAdminFetch>();

    // Valid direct Host header, but spoofed/conflicting x-forwarded-host
    const resConflictingHost = await proxyDevelopmentAdminApi(
      new Request("http://localhost:3001/v1/dev-bridge/health", {
        headers: {
          host: "admin.localhost:3001",
          "x-forwarded-host": "evil.com",
        },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(resConflictingHost.status).toBe(403);

    // Valid direct Host header, but spoofed/conflicting x-forwarded-proto
    const resConflictingProto = await proxyDevelopmentAdminApi(
      new Request("http://localhost:3001/v1/dev-bridge/health", {
        headers: {
          host: "admin.localhost:3001",
          "x-forwarded-proto": "https",
        },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(resConflictingProto.status).toBe(403);

    // Does NOT solely trust x-forwarded-host if direct Host header is hostile
    const resHostileDirectHost = await proxyDevelopmentAdminApi(
      new Request("http://localhost:3001/v1/dev-bridge/health", {
        headers: {
          host: "evil.com",
          "x-forwarded-host": "admin.localhost:3001",
        },
      }),
      fetcher,
      adminEnv,
      "development",
      new InMemoryDevelopmentAdminSessionStore(),
    );
    expect(resHostileDirectHost.status).toBe(403);

    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects malformed or ambiguous authority and forwarded headers", async () => {
    const adminEnv = {
      AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "http://admin.localhost:3001",
      AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://admin-staging.authorityclosers.com",
      AC_DEV_ADMIN_ACCESS_JWT:
        "t".repeat(32) + "." + "p".repeat(32) + "." + "s".repeat(32),
    };
    const fetcher = vi.fn<DevAdminFetch>();
    const malformedHeaders: Array<Record<string, string>> = [
      { host: "admin.localhost:3001/path" },
      { host: "admin.localhost:3001?query" },
      { host: "admin.localhost:3001#fragment" },
      { host: "evil.test@admin.localhost:3001" },
      { host: "admin.localhost:3001, evil.test" },
      { host: "admin.localhost:3002" },
      { host: "[::1]:3001" },
      { host: "" },
      { host: "admin.localhost:3001", "x-forwarded-host": "" },
      {
        host: "admin.localhost:3001",
        "x-forwarded-host": "admin.localhost:3001/path",
      },
      {
        host: "admin.localhost:3001",
        "x-forwarded-host": "evil.test@admin.localhost:3001",
      },
      {
        host: "admin.localhost:3001",
        "x-forwarded-host": "admin.localhost:3001, evil.test",
      },
      { host: "admin.localhost:3001", "x-forwarded-proto": "" },
      { host: "admin.localhost:3001", "x-forwarded-proto": "http:" },
      {
        host: "admin.localhost:3001",
        "x-forwarded-proto": "http,https",
      },
    ];

    for (const headers of malformedHeaders) {
      const response = await proxyDevelopmentAdminApi(
        new Request("http://localhost:3001/v1/dev-bridge/health", {
          headers,
        }),
        fetcher,
        adminEnv,
        "development",
        new InMemoryDevelopmentAdminSessionStore(),
      );
      expect(response.status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("accepts canonical default-port Host forms for an exact default-port origin", async () => {
    const adminEnv = {
      AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "http://admin.localhost",
      AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://admin-staging.authorityclosers.com",
      AC_DEV_ADMIN_ACCESS_JWT:
        "t".repeat(32) + "." + "p".repeat(32) + "." + "s".repeat(32),
    };
    const fetcher = vi.fn<DevAdminFetch>(() =>
      Promise.resolve(
        Response.json({ code: "authentication_required" }, { status: 401 }),
      ),
    );

    for (const host of ["admin.localhost", "admin.localhost:80"]) {
      const response = await proxyDevelopmentAdminApi(
        new Request("http://localhost/v1/dev-bridge/health", {
          headers: { host },
        }),
        fetcher,
        adminEnv,
        "development",
        new InMemoryDevelopmentAdminSessionStore(),
      );
      expect(response.status).toBe(200);
    }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("accepts exact IPv6 and HTTPS default-port loopback authorities", async () => {
    const fetcher = vi.fn<DevAdminFetch>(() =>
      Promise.resolve(
        Response.json({ code: "authentication_required" }, { status: 401 }),
      ),
    );
    const accessJwt =
      "t".repeat(32) + "." + "p".repeat(32) + "." + "s".repeat(32);
    const cases: Array<{
      environment: {
        AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: string;
        AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: string;
        AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN: string;
        AC_DEV_ADMIN_ACCESS_JWT: string;
      };
      url: string;
      headers: Record<string, string>;
    }> = [
      {
        environment: {
          AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
          AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "http://[::1]:3001",
          AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
            "https://admin-staging.authorityclosers.com",
          AC_DEV_ADMIN_ACCESS_JWT: accessJwt,
        },
        url: "http://localhost:3001/v1/dev-bridge/health",
        headers: { host: "[::1]:3001" },
      },
      {
        environment: {
          AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED: "true",
          AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN: "https://admin.localhost",
          AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN:
            "https://admin-staging.authorityclosers.com",
          AC_DEV_ADMIN_ACCESS_JWT: accessJwt,
        },
        url: "https://localhost/v1/dev-bridge/health",
        headers: {
          host: "admin.localhost:443",
          "x-forwarded-host": "admin.localhost",
          "x-forwarded-proto": "https",
        },
      },
    ];

    for (const testCase of cases) {
      const response = await proxyDevelopmentAdminApi(
        new Request(testCase.url, { headers: testCase.headers }),
        fetcher,
        testCase.environment,
        "development",
        new InMemoryDevelopmentAdminSessionStore(),
      );
      expect(response.status).toBe(200);
    }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
