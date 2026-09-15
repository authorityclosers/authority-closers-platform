import { describe, expect, it, vi } from "vitest";

import { fetchLocalLearnerWire } from "./local-api-upstream";
import { fetchDevelopmentLocalApiUpstream } from "./dev-local-api-upstream";
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

vi.mock("./local-api-upstream", () => ({
  fetchLocalLearnerWire: vi.fn(),
}));
vi.mock("./dev-local-api-upstream", () => ({
  fetchDevelopmentLocalApiUpstream: vi.fn(),
}));

const AUTH_BRIDGE_ENV = {
  AC_DEV_AUTH_BRIDGE_ENABLED: "true",
  AC_DEV_AUTH_BRIDGE_ORIGIN: "http://localhost:3000",
  AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN: "https://staging.authorityclosers.com",
};

it("retains ordinary local private-read transport when sandbox is not opted in", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response("private-read", {
        headers: { "content-type": "image/webp" },
      }),
  );
  const response = await proxyDevelopmentLearnerApi(
    new Request("http://localhost:3000/v1/media/read/existing"),
    fetcher,
    {},
    "development",
  );
  expect(response.status).toBe(200);
  expect(fetcher).toHaveBeenCalledOnce();
});

describe("managed local learner wire selection", () => {
  it("uses the numeric loopback wire only for the exact learner sandbox", async () => {
    const nativeWire = vi.mocked(fetchLocalLearnerWire);
    nativeWire.mockResolvedValueOnce(Response.json({ accepted: true }));

    const response = await proxyDevelopmentLearnerApi(
      new Request("http://127.0.0.1:3100/v1/me", {
        headers: { host: "learner.localhost:3100" },
      }),
      undefined,
      {
        AC_DEV_API_ORIGIN: "http://127.0.0.1:8000",
        AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
      },
      "development",
    );

    expect(response.status).toBe(200);
    expect(nativeWire).toHaveBeenCalledOnce();
    const [input, init] = nativeWire.mock.calls[0] ?? [];
    expect(String(input)).toBe("http://127.0.0.1:8000/v1/me");
    expect(init?.redirect).toBe("manual");
    expect(new Headers(init?.headers).has("host")).toBe(false);
    expect(new Headers(init?.headers).has("x-forwarded-host")).toBe(false);
  });

  it("uses the bounded native transport for validated non-sandbox local development", async () => {
    const nativeWire = vi.mocked(fetchLocalLearnerWire);
    const developmentWire = vi.mocked(fetchDevelopmentLocalApiUpstream);
    nativeWire.mockClear();
    developmentWire.mockResolvedValueOnce(Response.json({ accepted: true }));

    const response = await proxyDevelopmentLearnerApi(
      new Request("http://127.0.0.1:3100/v1/me"),
      undefined,
      { AC_DEV_API_ORIGIN: "http://127.0.0.1:8000" },
      "development",
    );

    expect(response.status).toBe(200);
    expect(nativeWire).not.toHaveBeenCalled();
    expect(developmentWire).toHaveBeenCalledOnce();
    expect(String(developmentWire.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8000/v1/me",
    );
  });
});
const STAGING_SESSION = "s".repeat(43);
const LOCAL_SESSION = "l".repeat(43);
const MEDIA_KEY =
  "tenants/tenant-1/media/lesson_video/asset-1/version-1/original/renditions/lesson.mp4";
const LEGACY_MEDIA_PATH = `/v1/media/playback/${encodeURIComponent(MEDIA_KEY)}?token=AC-MEDIA.fixture.${"s".repeat(43)}`;
const MEDIA_LOCATOR = "m".repeat(43);
const MEDIA_PATH = `/v1/dev-bridge/media/${MEDIA_LOCATOR}`;
function mediaSource(key = MEDIA_KEY, overrides: Record<string, unknown> = {}) {
  const iat = Math.floor(Date.now() / 1000);
  const claims = {
    typ: "AC-MEDIA",
    token_type: "playback",
    iat,
    exp: iat + 3600,
    key,
    activity_id: "activity-1",
    activity_version: "activity-version-1",
    asset_id: "asset-1",
    version_id: "version-1",
    binding_id: "binding-1",
    enrollment_id: "enrollment-1",
    delivery_grant_id: "grant-1",
    ...overrides,
  };
  return `https://staging.authorityclosers.com/v1/media/playback/${encodeURIComponent(key)}?token=AC-MEDIA.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.${"s".repeat(43)}`;
}

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

describe("authenticated development media streaming", () => {
  function store(source = mediaSource()) {
    const value = new InMemoryDevelopmentBridgeSessionStore(
      Date.now,
      () => MEDIA_LOCATOR,
    );
    value.set(LOCAL_SESSION, STAGING_SESSION);
    value.registerMedia(LOCAL_SESSION, [source]);
    return value;
  }
  function request(init: RequestInit = {}, path = MEDIA_PATH) {
    return bridgeRequest(path, {
      ...init,
      headers: {
        cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
        ...Object.fromEntries(new Headers(init.headers)),
      },
    });
  }
  function bytes(
    body: BodyInit | null = new Uint8Array([1, 2, 3, 4]),
    init: ResponseInit = {},
  ) {
    return new Response(body, {
      ...init,
      headers: {
        "content-type": "video/mp4",
        "content-length": "4",
        "accept-ranges": "bytes",
        ...Object.fromEntries(new Headers(init.headers)),
      },
    });
  }
  const run = (
    incoming: Request,
    fetcher: Parameters<typeof proxyDevelopmentLearnerApi>[1],
    sessions = store(),
  ) =>
    proxyDevelopmentLearnerApi(
      incoming,
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      sessions,
    );

  it("streams GET from fixed staging with only the server-held cookie and safe headers", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toContain(
          "https://staging.authorityclosers.com/v1/media/playback/",
        );
        expect(new URL(String(input)).searchParams.get("token")).toMatch(
          /^AC-MEDIA\./,
        );
        expect(init?.method).toBe("GET");
        expect(init?.redirect).toBe("manual");
        expect(init?.credentials).toBe("omit");
        expect(init?.cache).toBe("no-store");
        expect(Object.fromEntries(new Headers(init?.headers))).toEqual({
          accept: "video/mp4",
          "accept-encoding": "identity",
          origin: "https://staging.authorityclosers.com",
          cookie: `__Host-ac_session=${STAGING_SESSION}`,
        });
        return bytes(undefined, {
          headers: {
            "set-cookie": stagingSessionCookie(),
            authorization: "Bearer fixture-secret",
            location: "https://evil.example",
            "x-provider-secret": "never-forward",
            "access-control-allow-origin":
              "https://staging.authorityclosers.com",
            etag: `"${"a".repeat(64)}"`,
          },
        });
      },
    );
    const response = await run(
      request({
        headers: {
          accept: "video/mp4",
          referer: "http://localhost:3000/private?token=fixture",
          "x-request-id": "untrusted",
          "if-range": '"untrusted"',
        },
      }),
      fetcher,
    );
    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(
      new Uint8Array([1, 2, 3, 4]),
    );
    expect(response.headers.get("content-length")).toBe("4");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    for (const header of [
      "set-cookie",
      "authorization",
      "location",
      "x-provider-secret",
      "access-control-allow-origin",
    ])
      expect(response.headers.has(header)).toBe(false);
  });

  it("forwards HEAD with the same MIME/range policy and no body", async () => {
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        expect(init?.method).toBe("HEAD");
        expect(new Headers(init?.headers).get("range")).toBe("bytes=0-3");
        return bytes(null, {
          status: 206,
          headers: { "content-range": "bytes 0-3/10" },
        });
      },
    );
    const response = await run(
      request({ method: "HEAD", headers: { range: "bytes=0-3" } }),
      fetcher,
    );
    expect(response.status).toBe(206);
    expect(response.body).toBeNull();
    expect(response.headers.get("content-range")).toBe("bytes 0-3/10");
    expect(response.headers.get("content-length")).toBe("4");
  });

  it("supports a single partial range and the existing extensionless caption namespace", async () => {
    const response = await run(
      request({ headers: { range: "bytes=5-8" } }),
      async (_input, init) => {
        expect(new Headers(init?.headers).get("range")).toBe("bytes=5-8");
        return bytes(undefined, {
          status: 206,
          headers: { "content-range": "bytes 5-8/12" },
        });
      },
    );
    expect(response.status).toBe(206);
    expect((await response.arrayBuffer()).byteLength).toBe(4);
    const caption = await run(
      request(),
      async () =>
        bytes("WEBVTT", {
          headers: {
            "content-type": "text/vtt",
            "content-length": "6",
            "accept-ranges": "none",
          },
        }),
      store(
        mediaSource(
          MEDIA_KEY.replace("lesson.mp4", "captions/en/captions/caption-1"),
        ),
      ),
    );
    expect(caption.status).toBe(200);
    expect(await caption.text()).toBe("WEBVTT");
  });

  it("does not read the complete upstream body before returning headers", async () => {
    const pull = vi.fn(
      (output: ReadableStreamDefaultController<Uint8Array>) => {
        output.enqueue(new Uint8Array([1, 2, 3, 4]));
        output.close();
      },
    );
    const response = await run(request(), async () =>
      bytes(new ReadableStream({ pull }, { highWaterMark: 0 })),
    );
    expect(pull).not.toHaveBeenCalled();
    expect(response.status).toBe(200);
    expect((await response.arrayBuffer()).byteLength).toBe(4);
    expect(pull).toHaveBeenCalledTimes(1);
  });

  it("rejects malformed paths/queries and disallowed methods before upstream", async () => {
    const fetcher = vi.fn();
    for (const path of [
      LEGACY_MEDIA_PATH,
      LEGACY_MEDIA_PATH.replace("%2F", "/"),
      LEGACY_MEDIA_PATH.replace("%2F", "%2f"),
      LEGACY_MEDIA_PATH.replace("%2F", "%252F"),
      LEGACY_MEDIA_PATH.replace("original", ".."),
      MEDIA_PATH + "&token=again",
      MEDIA_PATH + "&url=https://evil.example",
      MEDIA_PATH + "?token=fixture",
      MEDIA_PATH + "/extra",
      MEDIA_PATH.replace(MEDIA_LOCATOR, "%6D" + MEDIA_LOCATOR.slice(1)),
    ])
      expect((await run(request({}, path), fetcher)).status).toBe(403);
    for (const method of ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
      expect((await run(request({ method }), fetcher)).status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects invalid ranges before any upstream byte request", async () => {
    const fetcher = vi.fn();
    for (const range of [
      "bytes=-2",
      "bytes=0-1,3-4",
      "bytes=3-1",
      "bytes=8589934592-",
      "bytes=0-99999999999999999999999999999999999999999",
      "bytes=01-2",
    ])
      expect((await run(request({ headers: { range } }), fetcher)).status).toBe(
        416,
      );
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("retains exact origin, credential, local-cookie, and default-off boundaries for media", async () => {
    const fetcher = vi.fn();
    for (const headers of [
      { origin: "https://evil.example" },
      { host: "localhost:3001" },
      { "x-forwarded-host": "evil.example" },
      { "sec-fetch-site": "cross-site" },
      { authorization: "Bearer fixture" },
      { "x-api-key": "fixture" },
      { cookie: `__Host-ac_session=${STAGING_SESSION}` },
      { cookie: "" },
      {
        cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}; __Host-ac_dev_qa_session=${LOCAL_SESSION}`,
      },
      { cookie: `__Host-ac_dev_admin_qa_session=${LOCAL_SESSION}` },
    ] as Record<string, string>[])
      expect([400, 401, 403]).toContain(
        (await run(request({ headers }), fetcher)).status,
      );
    expect(
      (
        await proxyDevelopmentLearnerApi(
          request(),
          fetcher,
          AUTH_BRIDGE_ENV,
          "production",
          store(),
        )
      ).status,
    ).toBe(404);
    expect(
      (
        await proxyDevelopmentLearnerApi(
          request(),
          fetcher,
          { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
          "development",
          store(),
        )
      ).status,
    ).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects redirects, HTML/JSON/HLS successes, compressed or unbounded objects", async () => {
    for (const method of ["GET", "HEAD"]) {
      for (const headers of [
        { "content-type": "application/vnd.apple.mpegurl" },
        { "content-type": "application/json" },
        { "content-type": "text/html" },
        { "content-encoding": "gzip" },
        { "content-length": "8589934593" },
        { "content-length": "" },
      ] as Record<string, string>[]) {
        const response = await run(request({ method }), async () =>
          bytes("private fixture body", { headers }),
        );
        expect(response.status).toBe(502);
        expect(await response.text()).not.toContain("private fixture body");
      }
    }
    const response = await run(
      request(),
      async () =>
        new Response("private fixture body", {
          status: 302,
          headers: { location: "https://evil.example" },
        }),
    );
    expect(response.status).toBe(502);
    expect(response.headers.has("location")).toBe(false);
    expect(await response.text()).not.toContain("private fixture body");
  });

  it("rejects inconsistent partial ranges and preserves a sanitized 416", async () => {
    for (const range of [
      "bytes 1-4/10",
      "bytes 0-4/10",
      "bytes 0-3/3",
      "bytes 0-3/9999999999999999",
      "nonsense",
    ]) {
      const response = await run(
        request({ headers: { range: "bytes=0-3" } }),
        async () =>
          bytes(undefined, {
            status: 206,
            headers: { "content-range": range },
          }),
      );
      expect(response.status).toBe(502);
    }
    const response = await run(
      request({ headers: { range: "bytes=20-" } }),
      async () =>
        new Response("private fixture error", {
          status: 416,
          headers: { "content-range": "bytes */10" },
        }),
    );
    expect(response.status).toBe(416);
    expect(response.headers.get("content-range")).toBe("bytes */10");
    expect(response.body).toBeNull();
  });

  it("sanitizes upstream 401 and invalidates the local session; logout also blocks later bytes", async () => {
    const sessions = store();
    const response = await run(
      request(),
      async () => new Response("private fixture error", { status: 401 }),
      sessions,
    );
    expect(response.status).toBe(401);
    expect(await response.text()).not.toContain("private fixture error");
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
    expect(sessions.get(LOCAL_SESSION)).toBeNull();
    const nextFetch = vi.fn();
    expect((await run(request(), nextFetch, sessions)).status).toBe(401);
    expect(nextFetch).not.toHaveBeenCalled();
    sessions.set(LOCAL_SESSION, STAGING_SESSION);
    await run(
      request({ method: "POST" }, "/v1/auth/logout"),
      async () => new Response(null, { status: 204 }),
      sessions,
    );
    expect((await run(request(), nextFetch, sessions)).status).toBe(401);
  });

  it("keeps incoming cancellation active after headers and sanitizes stream errors", async () => {
    const incoming = new AbortController();
    let upstreamSignal: AbortSignal | null | undefined;
    const cancel = vi.fn();
    const response = await run(
      request({ signal: incoming.signal }),
      async (_input, init) => {
        upstreamSignal = init?.signal;
        return bytes(new ReadableStream({ cancel }, { highWaterMark: 0 }));
      },
    );
    const pending = response.body!.getReader().read();
    const observed = expect(pending).rejects.toThrow(
      "Local media stream is unavailable or cancelled.",
    );
    incoming.abort(new Error("private fixture reason"));
    await observed;
    expect(upstreamSignal?.aborted).toBe(true);
    expect(cancel).toHaveBeenCalled();
  });

  it("does not fetch already-aborted media requests", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetcher = vi.fn();
    expect(
      (await run(request({ signal: controller.signal }), fetcher)).status,
    ).toBe(504);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("times out waiting for upstream media headers without exposing its exception", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener(
              "abort",
              () => reject(new Error("private upstream URL fixture")),
              { once: true },
            );
          }),
      );
      const pending = run(request(), fetcher);
      await vi.advanceTimersByTimeAsync(12_001);
      const response = await pending;
      expect(response.status).toBe(504);
      expect(await response.text()).not.toContain(
        "private upstream URL fixture",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("aborts upstream when the response consumer cancels after receiving bytes", async () => {
    let upstreamSignal: AbortSignal | null | undefined;
    const cancel = vi.fn();
    const response = await run(request(), async (_input, init) => {
      upstreamSignal = init?.signal;
      return bytes(
        new ReadableStream(
          {
            pull(output) {
              output.enqueue(new Uint8Array([1]));
            },
            cancel,
          },
          { highWaterMark: 0 },
        ),
      );
    });
    const reader = response.body!.getReader();
    expect((await reader.read()).value).toEqual(new Uint8Array([1]));
    await reader.cancel("private consumer reason");
    expect(upstreamSignal?.aborted).toBe(true);
    expect(cancel).toHaveBeenCalled();
  });

  it("times out a stalled body read and an unconsumed long-lived response", async () => {
    vi.useFakeTimers();
    try {
      for (const read of [true, false]) {
        let upstreamSignal: AbortSignal | null | undefined;
        const response = await run(request(), async (_input, init) => {
          upstreamSignal = init?.signal;
          return bytes(new ReadableStream({}, { highWaterMark: 0 }));
        });
        const reader = response.body!.getReader();
        const pending = read ? reader.read() : null;
        const observed = pending
          ? expect(pending).rejects.toThrow("Local media stream")
          : null;
        await vi.advanceTimersByTimeAsync(read ? 30_001 : 30 * 60 * 1000 + 1);
        if (observed) await observed;
        else await expect(reader.read()).rejects.toThrow("Local media stream");
        expect(upstreamSignal?.aborted).toBe(true);
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects truncated/oversized bodies without forwarding raw provider errors", async () => {
    for (const body of [new Uint8Array([1]), new Uint8Array([1, 2, 3, 4, 5])]) {
      const response = await run(request(), async () => bytes(body));
      await expect(response.arrayBuffer()).rejects.toThrow(
        "Local media stream",
      );
    }
    const response = await run(request(), async () =>
      bytes(
        new ReadableStream(
          {
            pull() {
              throw new Error("private provider token details");
            },
          },
          { highWaterMark: 0 },
        ),
      ),
    );
    await expect(response.arrayBuffer()).rejects.toThrow(
      "Local media stream is unavailable or cancelled.",
    );
  });
});

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
      ["GET", "/v1/me/app-updates"],
      ["GET", "/v1/me/consent"],
      ["POST", "/v1/me/consent/renew"],
      ["POST", "/v1/me/app-updates/app-updates-v0-2-alpha/read"],
      ["GET", "/v1/context"],
      ["POST", "/v1/context"],
      ["GET", "/v1/onboarding"],
      ["PUT", "/v1/onboarding"],
      ["POST", "/v1/enrollments/free"],
      ["GET", "/v1/profile/avatar"],
      ["POST", "/v1/profile/avatar"],
      ["POST", "/v1/profile/avatar/upload-1/complete"],
      ["GET", "/v1/learning?limit=50"],
      ["GET", "/v1/learning?limit=50&cursor=cursor-2"],
      ["GET", "/v1/learning/lesson-1"],
      ["GET", "/v1/learning/insights"],
      ["GET", "/v1/learning/insights?period=week"],
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
      ["DELETE", "/v1/profile/avatar"],
      ["POST", "/v1/profile/avatar/upload-1/complete/extra"],
      ["GET", "/v1/learning"],
      ["GET", "/v1/learning?limit=49"],
      ["GET", "/v1/learning?limit=50&cursor="],
      ["GET", "/v1/learning?limit=50&cursor=one&cursor=two"],
      ["POST", "/v1/activities/activity-1/evidence/extra"],
      ["GET", "/v1/learning/lesson-1?enrollment_id=one"],
      ["GET", "/v1/learning/insights?period=year"],
      ["GET", "/v1/learning/insights?period=week&subject_person_id=other"],
      ["GET", "/v1/me?include=admin"],
      ["POST", "/v1/me/app-updates"],
      ["GET", "/v1/me/app-updates/app-updates-v0-2-alpha/read"],
      [
        "POST",
        "/v1/me/app-updates/app-updates-v0-2-alpha/read?person_id=another",
      ],
      ["POST", "/v1/me/app-updates/%2foutside/read"],
      ["POST", `/v1/me/app-updates/${"a".repeat(129)}/read`],
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

  it("clears a stale local session without blocking the public catalog", async () => {
    const fetcher = vi.fn(async () =>
      Response.json({ items: [], next_cursor: null }),
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/programs?limit=50", {
        headers: { cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}` },
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
    expect(fetcher).toHaveBeenCalledOnce();
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

  it("rejects an oversized learner mutation before buffering it upstream", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    store.set(LOCAL_SESSION, STAGING_SESSION);
    const fetcher = vi.fn();
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/activities/activity-1/draft", {
        method: "PUT",
        headers: {
          cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
          "content-type": "application/json",
        },
        body: "x".repeat(1024 * 1024 + 1),
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );

    expect(response.status).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("times out a stalled learner request body before any upstream call", async () => {
    vi.useFakeTimers();
    try {
      const store = new InMemoryDevelopmentBridgeSessionStore();
      store.set(LOCAL_SESSION, STAGING_SESSION);
      const fetcher = vi.fn();
      const request = bridgeRequest("/v1/activities/activity-1/draft", {
        method: "PUT",
        headers: {
          cookie: `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
          "content-type": "application/json",
        },
        body: new ReadableStream<Uint8Array>({}),
        duplex: "half",
      } as RequestInit);
      const pending = proxyDevelopmentLearnerApi(
        request,
        fetcher,
        AUTH_BRIDGE_ENV,
        "development",
        store,
      );

      await vi.advanceTimersByTimeAsync(12_001);
      const response = await pending;
      expect(response.status).toBe(504);
      expect(fetcher).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not accept the admin bridge handle as learner authentication", async () => {
    const fetcher = vi.fn();
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/me", {
        headers: {
          cookie: `__Host-ac_dev_admin_qa_session=${"a".repeat(43)}`,
        },
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );

    expect(response.status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses only the learner handle when both localhost bridge cookies arrive", async () => {
    const store = new InMemoryDevelopmentBridgeSessionStore();
    store.set(LOCAL_SESSION, STAGING_SESSION);
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        expect(new Headers(init?.headers).get("cookie")).toBe(
          `__Host-ac_session=${STAGING_SESSION}`,
        );
        return Response.json({ person_id: "learner-1" });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      bridgeRequest("/v1/me", {
        headers: {
          cookie: [
            `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
            `__Host-ac_dev_admin_qa_session=${"a".repeat(43)}`,
          ].join("; "),
        },
      }),
      fetcher,
      AUTH_BRIDGE_ENV,
      "development",
      store,
    );

    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();
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

  it("clears malformed and expired local bridge cookies before asking for sign-in", async () => {
    for (const cookie of [
      "__Host-ac_dev_qa_session=malformed",
      `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
    ]) {
      const response = await proxyDevelopmentLearnerApi(
        bridgeRequest("/v1/me", { headers: { cookie } }),
        vi.fn(),
        AUTH_BRIDGE_ENV,
        "development",
        new InMemoryDevelopmentBridgeSessionStore(),
      );
      expect(response.status).toBe(401);
      expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
    }
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

  it("preserves local API cookies while stripping both bridge handles", async () => {
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
          cookie: [
            "local-session=value",
            `__Host-ac_dev_qa_session=${LOCAL_SESSION}`,
            `__Host-ac_dev_admin_qa_session=${"a".repeat(43)}`,
          ].join("; "),
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

  it("preserves the package-owned learner Host across the managed local API hop", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const headers = new Headers(init?.headers);
        expect(String(input)).toBe(
          "http://learner.localhost:8000/v1/me/app-updates",
        );
        expect(headers.has("host")).toBe(false);
        expect(headers.has("forwarded")).toBe(false);
        expect(headers.has("x-forwarded-host")).toBe(false);
        expect(headers.has("x-forwarded-port")).toBe(false);
        expect(headers.has("x-forwarded-proto")).toBe(false);
        return Response.json({ accepted: true });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      new Request("http://127.0.0.1:3100/v1/me/app-updates", {
        headers: {
          host: "learner.localhost:3100",
        },
      }),
      fetcher,
      {
        AC_DEV_API_ORIGIN: "http://127.0.0.1:8000",
        AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
      },
      "development",
    );

    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("never derives the managed local learner Host from forwarded authority", async () => {
    const fetcher = vi.fn(async () => Response.json({ accepted: true }));
    const response = await proxyDevelopmentLearnerApi(
      new Request("http://127.0.0.1:3100/v1/me/app-updates", {
        headers: {
          host: "attacker.example",
          forwarded: "host=learner.localhost:3100;proto=http",
          "x-forwarded-host": "learner.localhost:3100",
          "x-forwarded-port": "3100",
          "x-forwarded-proto": "http",
        },
      }),
      fetcher,
      {
        AC_DEV_API_ORIGIN: "http://127.0.0.1:8000",
        AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
      },
      "development",
    );

    expect(response.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("accepts loopback requests with Host matching learner.localhost origin", async () => {
    const learnerEnv = {
      AC_DEV_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_AUTH_BRIDGE_ORIGIN: "http://learner.localhost:3000",
      AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://staging.authorityclosers.com",
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe(
        "https://api-staging.authorityclosers.com/v1/programs?limit=1",
      );
      return Response.json({ items: [] });
    });

    // Next.js dev server synthesizes request.url as http://localhost:3000/v1/...
    // while the client sets Host: learner.localhost:3000
    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=1", {
        headers: {
          host: "learner.localhost:3000",
        },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-ac-dev-data-mode")).toBe(
      "staging-public-catalog",
    );
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("accepts loopback requests when direct Host and forwarded headers agree on learner.localhost origin", async () => {
    const learnerEnv = {
      AC_DEV_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_AUTH_BRIDGE_ORIGIN: "http://learner.localhost:3000",
      AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://staging.authorityclosers.com",
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe(
        "https://api-staging.authorityclosers.com/v1/programs?limit=1",
      );
      return Response.json({ items: [] });
    });

    const response = await proxyDevelopmentLearnerApi(
      new Request("http://127.0.0.1:3000/v1/programs?limit=1", {
        headers: {
          host: "learner.localhost:3000",
          "x-forwarded-host": "learner.localhost:3000",
          "x-forwarded-proto": "http",
        },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );

    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();

    // Omitting direct Host header while supplying only x-forwarded-host must be rejected
    const rejectedWithoutHost = await proxyDevelopmentLearnerApi(
      new Request("http://127.0.0.1:3000/v1/programs?limit=1", {
        headers: {
          "x-forwarded-host": "learner.localhost:3000",
          "x-forwarded-proto": "http",
        },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(rejectedWithoutHost.status).toBe(403);
  });

  it("rejects loopback requests with mismatched Host or non-loopback URLs", async () => {
    const learnerEnv = {
      AC_DEV_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_AUTH_BRIDGE_ORIGIN: "http://learner.localhost:3000",
      AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://staging.authorityclosers.com",
    };
    const fetcher = vi.fn();

    // Wrong host: admin.localhost
    const res1 = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=1", {
        headers: { host: "admin.localhost:3001" },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(res1.status).toBe(403);

    // Wrong host: plain localhost when learner.localhost is expected
    const res2 = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=1", {
        headers: { host: "localhost:3000" },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(res2.status).toBe(403);

    // Hostile non-loopback URL even if host header claims learner.localhost
    const res3 = await proxyDevelopmentLearnerApi(
      new Request("http://evil.com/v1/programs?limit=1", {
        headers: { host: "learner.localhost:3000" },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(res3.status).toBe(403);

    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects conflicting or spoofed forwarded headers even if direct Host or forwarded-host looks valid", async () => {
    const learnerEnv = {
      AC_DEV_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_AUTH_BRIDGE_ORIGIN: "http://learner.localhost:3000",
      AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://staging.authorityclosers.com",
    };
    const fetcher = vi.fn();

    // Valid Host header, but spoofed/conflicting x-forwarded-host
    const resConflictingHost = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=1", {
        headers: {
          host: "learner.localhost:3000",
          "x-forwarded-host": "evil.com",
        },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(resConflictingHost.status).toBe(403);

    // Valid Host header, but spoofed/conflicting x-forwarded-proto (e.g. https when http is expected)
    const resConflictingProto = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=1", {
        headers: {
          host: "learner.localhost:3000",
          "x-forwarded-proto": "https",
        },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(resConflictingProto.status).toBe(403);

    // Does NOT solely trust x-forwarded-host if direct Host header is hostile
    const resHostileDirectHost = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=1", {
        headers: {
          host: "evil.com",
          "x-forwarded-host": "learner.localhost:3000",
        },
      }),
      fetcher,
      learnerEnv,
      "development",
      new InMemoryDevelopmentBridgeSessionStore(),
    );
    expect(resHostileDirectHost.status).toBe(403);

    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects malformed or ambiguous authority and forwarded headers", async () => {
    const learnerEnv = {
      AC_DEV_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_AUTH_BRIDGE_ORIGIN: "http://learner.localhost:3000",
      AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://staging.authorityclosers.com",
    };
    const fetcher = vi.fn();
    const malformedHeaders: Array<Record<string, string>> = [
      { host: "learner.localhost:3000/path" },
      { host: "learner.localhost:3000?query" },
      { host: "learner.localhost:3000#fragment" },
      { host: "evil.test@learner.localhost:3000" },
      { host: "learner.localhost:3000, evil.test" },
      { host: "learner.localhost:3002" },
      { host: "[::1]:3000" },
      { host: "" },
      { host: "learner.localhost:3000", "x-forwarded-host": "" },
      {
        host: "learner.localhost:3000",
        "x-forwarded-host": "learner.localhost:3000/path",
      },
      {
        host: "learner.localhost:3000",
        "x-forwarded-host": "evil.test@learner.localhost:3000",
      },
      {
        host: "learner.localhost:3000",
        "x-forwarded-host": "learner.localhost:3000, evil.test",
      },
      { host: "learner.localhost:3000", "x-forwarded-proto": "" },
      { host: "learner.localhost:3000", "x-forwarded-proto": "http:" },
      {
        host: "learner.localhost:3000",
        "x-forwarded-proto": "http,https",
      },
    ];

    for (const headers of malformedHeaders) {
      const response = await proxyDevelopmentLearnerApi(
        new Request("http://localhost:3000/v1/programs?limit=1", { headers }),
        fetcher,
        learnerEnv,
        "development",
        new InMemoryDevelopmentBridgeSessionStore(),
      );
      expect(response.status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("accepts canonical default-port Host forms for an exact default-port origin", async () => {
    const learnerEnv = {
      AC_DEV_AUTH_BRIDGE_ENABLED: "true",
      AC_DEV_AUTH_BRIDGE_ORIGIN: "http://learner.localhost",
      AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
        "https://staging.authorityclosers.com",
    };
    const fetcher = vi.fn(() => Promise.resolve(Response.json({ items: [] })));

    for (const host of ["learner.localhost", "learner.localhost:80"]) {
      const response = await proxyDevelopmentLearnerApi(
        new Request("http://localhost/v1/programs?limit=1", {
          headers: { host },
        }),
        fetcher,
        learnerEnv,
        "development",
        new InMemoryDevelopmentBridgeSessionStore(),
      );
      expect(response.status).toBe(200);
    }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("accepts exact IPv6 and HTTPS default-port loopback authorities", async () => {
    const fetcher = vi.fn(() => Promise.resolve(Response.json({ items: [] })));
    const cases: Array<{
      environment: {
        AC_DEV_AUTH_BRIDGE_ENABLED: string;
        AC_DEV_AUTH_BRIDGE_ORIGIN: string;
        AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN: string;
      };
      url: string;
      headers: Record<string, string>;
    }> = [
      {
        environment: {
          AC_DEV_AUTH_BRIDGE_ENABLED: "true",
          AC_DEV_AUTH_BRIDGE_ORIGIN: "http://[::1]:3000",
          AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
            "https://staging.authorityclosers.com",
        },
        url: "http://localhost:3000/v1/programs?limit=1",
        headers: { host: "[::1]:3000" },
      },
      {
        environment: {
          AC_DEV_AUTH_BRIDGE_ENABLED: "true",
          AC_DEV_AUTH_BRIDGE_ORIGIN: "https://learner.localhost",
          AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN:
            "https://staging.authorityclosers.com",
        },
        url: "https://localhost/v1/programs?limit=1",
        headers: {
          host: "learner.localhost:443",
          "x-forwarded-host": "learner.localhost",
          "x-forwarded-proto": "https",
        },
      },
    ];

    for (const testCase of cases) {
      const response = await proxyDevelopmentLearnerApi(
        new Request(testCase.url, { headers: testCase.headers }),
        fetcher,
        testCase.environment,
        "development",
        new InMemoryDevelopmentBridgeSessionStore(),
      );
      expect(response.status).toBe(200);
    }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
