import { afterEach, describe, expect, it, vi } from "vitest";
import {
  InMemoryDevelopmentBridgeSessionStore,
  proxyDevelopmentLearnerApi,
} from "./dev-api-proxy";
import { readDevelopmentMediaSource } from "./dev-media-transport";
import * as mediaUpstream from "./dev-media-upstream";

const origin = "http://localhost:3000";
const env = {
  AC_DEV_AUTH_BRIDGE_ENABLED: "true",
  AC_DEV_AUTH_BRIDGE_ORIGIN: origin,
  AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN: "https://staging.authorityclosers.com",
};
const local = "l".repeat(43);
const staging = "s".repeat(43);
const key = "tenants/t/media/video/a/v/original";
const registration = "/v1/dev-bridge/media";
function source(overrides: Record<string, unknown> = {}) {
  const iat = Math.floor(Date.now() / 1000);
  const claims = {
    typ: "AC-MEDIA",
    token_type: "playback",
    iat,
    exp: iat + 120,
    key,
    activity_id: "activity-1",
    activity_version: "activity-version-1",
    asset_id: "a",
    version_id: "v",
    binding_id: "binding-1",
    enrollment_id: "enrollment-1",
    delivery_grant_id: "grant-1",
    ...overrides,
  };
  return `https://staging.authorityclosers.com/v1/media/playback/${encodeURIComponent(key)}?token=AC-MEDIA.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.${"s".repeat(43)}`;
}
function request(path = registration, init: RequestInit = {}) {
  return new Request(origin + path, {
    ...init,
    headers: {
      origin,
      cookie: `__Host-ac_dev_qa_session=${local}`,
      ...Object.fromEntries(new Headers(init.headers)),
    },
  });
}
function setup() {
  const store = new InMemoryDevelopmentBridgeSessionStore();
  store.set(local, staging);
  const fetcher = vi.fn<
    (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
  >(
    async () =>
      new Response(new Uint8Array([1, 2]), {
        headers: { "content-type": "video/mp4", "content-length": "2" },
      }),
  );
  const run = (incoming: Request) =>
    proxyDevelopmentLearnerApi(incoming, fetcher, env, "development", store);
  const register = (sources = [source()], init: RequestInit = {}) =>
    run(
      request(registration, {
        method: "POST",
        body: JSON.stringify({ sources }),
        ...init,
        headers: {
          "content-type": "application/json",
          ...Object.fromEntries(new Headers(init.headers)),
        },
      }),
    );
  return { store, fetcher, run, register };
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("session-bound opaque local media registry", () => {
  it("defaults media to explicit native HTTPS while keeping ordinary API fetch unchanged", async () => {
    const { store } = setup();
    const result = store.registerMedia(local, [source()]);
    if (!Array.isArray(result)) throw new Error("Fixture registration failed");
    const native = vi
      .spyOn(mediaUpstream, "fetchDevelopmentMediaUpstream")
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1, 2]), {
          headers: { "content-type": "video/mp4", "content-length": "2" },
        }),
      );
    const ordinary = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json({ fixture: true }));
    const response = await proxyDevelopmentLearnerApi(
      request(result[0].path),
      undefined,
      env,
      "development",
      store,
    );
    expect(response.status).toBe(200);
    await response.arrayBuffer();
    expect(native).toHaveBeenCalledOnce();
    expect(ordinary).not.toHaveBeenCalled();
    await proxyDevelopmentLearnerApi(
      request("/v1/me"),
      undefined,
      env,
      "development",
      store,
    );
    expect(ordinary).toHaveBeenCalledOnce();
  });
  it("registers without upstream authority and emits only token-free session-bound locators", async () => {
    const { run, register, fetcher } = setup();
    const signed = source();
    const response = await register([signed]);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const text = await response.text();
    expect(text).not.toContain("AC-MEDIA");
    expect(text).not.toContain("token=");
    expect(text).not.toContain("staging.authorityclosers.com");
    expect(fetcher).not.toHaveBeenCalled();
    const { items } = JSON.parse(text);
    expect(items[0].path).toMatch(
      /^\/v1\/dev-bridge\/media\/[A-Za-z0-9_-]{43}$/,
    );
    expect(items[0].expires_at).toBe(
      readDevelopmentMediaSource(signed)!.expiresAt,
    );
    const get = await run(request(items[0].path));
    expect(get.status).toBe(200);
    expect((await get.arrayBuffer()).byteLength).toBe(2);
    expect(String(fetcher.mock.calls[0][0])).toBe(signed);
    const headers = new Headers(fetcher.mock.calls[0][1]?.headers);
    expect(headers.get("cookie")).toBe(`__Host-ac_session=${staging}`);
  });

  it("denies cross-session locators, missing sessions, extra queries and the legacy signed route", async () => {
    const { store, register, run, fetcher } = setup();
    const { items } = await (await register()).json();
    const other = "o".repeat(43);
    store.set(other, staging);
    expect(
      (
        await run(
          request(items[0].path, {
            headers: { cookie: `__Host-ac_dev_qa_session=${other}` },
          }),
        )
      ).status,
    ).toBe(404);
    expect(
      (await run(request(items[0].path, { headers: { cookie: "" } }))).status,
    ).toBe(401);
    expect((await run(request(items[0].path + "?token=fixture"))).status).toBe(
      403,
    );
    expect(
      (
        await run(
          request(new URL(source()).pathname + new URL(source()).search),
        )
      ).status,
    ).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("enforces Origin/credential/JSON boundaries before registration", async () => {
    const { register, run } = setup();
    for (const headers of [
      { origin: "https://evil.example" },
      { authorization: "Bearer synthetic" },
      { cookie: `__Host-ac_session=${staging}` },
      { "sec-fetch-site": "cross-site" },
      { "content-type": "text/plain" },
      { "content-encoding": "gzip" },
    ] as Record<string, string>[]) {
      expect([400, 403]).toContain(
        (await register(undefined, { headers })).status,
      );
    }
    const missingOrigin = request(registration, {
      method: "POST",
      body: "{}",
      headers: { "content-type": "application/json" },
    });
    missingOrigin.headers.delete("origin");
    expect((await run(missingOrigin)).status).toBe(403);
  });

  it("rejects untrusted source metadata, wrong origins and expired/extended grants", async () => {
    const { register } = setup();
    const now = Math.floor(Date.now() / 1000);
    for (const signed of [
      source({ exp: now }),
      source({ iat: now + 31 }),
      source({ exp: now + 3601 }),
      source({ exp: "9999999999" }),
      source({ typ: "other" }),
      source({ token_type: "read" }),
      source({ key: "another/object" }),
      source({ delivery_grant_id: "" }),
      source().replace(
        "staging.authorityclosers.com",
        "app.authorityclosers.com",
      ),
      source().replace("https://", "https://user@"),
      source() + "&extra=1",
    ])
      expect((await register([signed])).status).toBe(400);
  });

  it("bounds body size, batch size, per-session entries and registration rate", async () => {
    const { register, store } = setup();
    expect(
      (await register(undefined, { body: " ".repeat(65_537) })).status,
    ).toBe(413);
    expect(
      (
        await register(
          Array.from({ length: 13 }, (_, nonce) => source({ nonce })),
        )
      ).status,
    ).toBe(400);
    const signed = source();
    expect(store.registerMedia(local, [signed, signed])).toBeNull();
    for (let nonce = 0; nonce < 64; nonce++)
      expect(
        Array.isArray(store.registerMedia(local, [source({ nonce })])),
      ).toBe(true);
    expect(store.registerMedia(local, [source({ nonce: 65 })])).toBe("limited");
    const limited = setup();
    for (let index = 0; index < 30; index++)
      expect((await limited.register()).status).toBe(200);
    expect((await limited.register()).status).toBe(429);
  });

  it("purges on expiry, replacement, logout, eviction and session expiry", () => {
    vi.useFakeTimers();
    const { store } = setup();
    function locator() {
      const result = store.registerMedia(local, [source()]);
      if (!Array.isArray(result))
        throw new Error("Fixture registration failed");
      return result[0].path.slice(registration.length + 1);
    }
    const first = locator();
    store.set(local, staging);
    expect(store.mediaSource(local, first)).toBeNull();
    const second = locator();
    store.delete(local);
    expect(store.mediaSource(local, second)).toBeNull();
    store.set(local, staging);
    const third = locator();
    vi.advanceTimersByTime(120_001);
    expect(store.mediaSource(local, third)).toBeNull();
    const fourth = locator();
    for (let index = 0; index < 8; index++)
      store.set(`other-${index}`, staging);
    expect(store.mediaSource(local, fourth)).toBeNull();
    store.set(local, staging);
    const fifth = locator();
    vi.advanceTimersByTime(8 * 60 * 60 * 1000 + 1);
    expect(store.mediaSource(local, fifth)).toBeNull();
  });

  it("rejects a body finishing after even a same-cookie session replacement", async () => {
    const { store, run } = setup();
    let output!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        output = controller;
      },
    });
    const incoming = request(registration, {
      method: "POST",
      body,
      duplex: "half",
      headers: { "content-type": "application/json" },
    } as RequestInit);
    const pending = run(incoming);
    store.set(local, staging);
    output.enqueue(
      new TextEncoder().encode(JSON.stringify({ sources: [source()] })),
    );
    output.close();
    expect((await pending).status).toBe(401);
  });

  it("times out a stalled registration body and cancels its stream", async () => {
    vi.useFakeTimers();
    const { run } = setup();
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const pending = run(
      request(registration, {
        method: "POST",
        body,
        duplex: "half",
        headers: { "content-type": "application/json" },
      } as RequestInit),
    );
    await vi.advanceTimersByTimeAsync(12_001);
    expect((await pending).status).toBe(504);
    expect(cancel).toHaveBeenCalled();
  });
});
