import { EventEmitter } from "node:events";
import type { IncomingMessage, RequestOptions } from "node:http";
import { PassThrough } from "node:stream";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nativeRequest = vi.hoisted(() => vi.fn());
vi.mock("node:https", () => ({ request: nativeRequest }));
import { fetchDevelopmentMediaUpstream } from "./dev-media-upstream";

const origin = "https://staging.authorityclosers.com";
const key = "tenants/t/media/video/a/v/original";
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
  return `${origin}/v1/media/playback/${encodeURIComponent(key)}?token=AC-MEDIA.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.${"s".repeat(43)}`;
}
function options(overrides: RequestInit = {}): RequestInit {
  return {
    method: "GET",
    redirect: "manual",
    cache: "no-store",
    signal: new AbortController().signal,
    headers: {
      origin,
      "accept-encoding": "identity",
      accept: "video/mp4",
      cookie: `__Host-ac_session=${"s".repeat(43)}`,
    },
    ...overrides,
  };
}
function harness(status = 200, headers: Record<string, string> = {}) {
  const message = Object.assign(new PassThrough({ highWaterMark: 16 * 1024 }), {
    statusCode: status,
    headers: { "content-type": "video/mp4", "content-length": "3", ...headers },
  });
  let receive: (message: IncomingMessage) => void;
  const request = Object.assign(new EventEmitter(), {
    end: vi.fn(),
    destroy: vi.fn(),
  });
  nativeRequest.mockImplementation(
    (_url: string, _options: RequestOptions, callback: typeof receive) => {
      receive = callback;
      return request;
    },
  );
  return {
    message,
    request,
    respond: () => receive(message as unknown as IncomingMessage),
  };
}

beforeEach(() => {
  nativeRequest.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error("Patched fetch must not run");
    }),
  );
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("uninstrumented development media upstream", () => {
  it("refuses native HTTP diagnostic activation before passing credentials to Node", async () => {
    vi.stubEnv("NODE_DEBUG", "https");
    await expect(
      fetchDevelopmentMediaUpstream(source(), options()),
    ).rejects.toThrow("Local media upstream is unavailable or cancelled.");
    expect(nativeRequest).not.toHaveBeenCalled();
  });
  it("streams exact bytes with original signed source and bounded headers, never global fetch", async () => {
    const native = harness(206, {
      "content-range": "bytes 0-2/3",
      "set-cookie": "never-forward",
      location: "https://elsewhere.example",
      etag: '"digest"',
    });
    const url = source();
    const init = options();
    const pending = fetchDevelopmentMediaUpstream(url, init);
    native.respond();
    const response = await pending;
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 0-2/3");
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(response.headers.has("location")).toBe(false);
    native.message.end(Buffer.from([1, 2, 3]));
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(
      new Uint8Array([1, 2, 3]),
    );
    expect(nativeRequest).toHaveBeenCalledWith(
      url,
      expect.objectContaining({
        method: "GET",
        agent: false,
        maxHeaderSize: 16384,
      }),
      expect.any(Function),
    );
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(native.request.end).toHaveBeenCalledOnce();
  });

  it.each(["HEAD", "GET"])(
    "supports a %s Request input without broadening headers",
    async (method) => {
      const native = harness();
      const pending = fetchDevelopmentMediaUpstream(
        new Request(source(), options({ method })),
      );
      native.respond();
      const response = await pending;
      if (method === "HEAD") {
        expect(response.body).toBeNull();
        expect(native.message.destroyed).toBe(true);
        expect(native.request.destroy).toHaveBeenCalledOnce();
      } else {
        native.message.end(Buffer.from([1, 2, 3]));
        expect((await response.arrayBuffer()).byteLength).toBe(3);
      }
    },
  );

  it.each([301, 302, 307, 308, 401, 403, 416, 500])(
    "returns %i for caller denial handling without following or caching",
    async (status) => {
      const native = harness(status, { location: source() });
      const pending = fetchDevelopmentMediaUpstream(source(), options());
      native.respond();
      const response = await pending;
      expect(response.status).toBe(status);
      expect(response.headers.has("location")).toBe(false);
      await response.body!.cancel();
      expect(nativeRequest).toHaveBeenCalledOnce();
      expect(native.request.destroy).toHaveBeenCalledOnce();
    },
  );

  it("rejects invalid origin, expired or malformed metadata before a socket exists", async () => {
    for (const value of [
      source().replace(origin, "http://staging.authorityclosers.com"),
      source().replace(origin, "https://app.authorityclosers.com"),
      source().replace(
        origin,
        "https://staging.authorityclosers.com.evil.example",
      ),
      source() + "&other=1",
      source({ exp: 1 }),
      source({ key: "wrong" }),
      source().replace("/playback/", "/other/"),
    ]) {
      await expect(
        fetchDevelopmentMediaUpstream(value, options()),
      ).rejects.toThrow("Local media upstream is unavailable or cancelled.");
    }
    expect(nativeRequest).not.toHaveBeenCalled();
  });

  it("rejects mutation, automatic redirects, absent signal and unsupported forwarded headers", async () => {
    for (const change of [
      { method: "POST" },
      { body: "data" },
      { redirect: "follow" as const },
      { signal: null },
    ]) {
      await expect(
        fetchDevelopmentMediaUpstream(source(), options(change)),
      ).rejects.toThrow("Local media upstream");
    }
    for (const [name, value] of [
      ["authorization", "Bearer synthetic"],
      ["host", "evil.example"],
      ["x-forwarded-host", "evil.example"],
      ["accept-encoding", "gzip"],
      ["origin", "https://evil.example"],
      ["cookie", "other=value"],
      ["range", "bytes=0-1,3-4"],
      ["accept", "x".repeat(1025)],
    ]) {
      const init = options();
      const headers = new Headers(init.headers);
      headers.set(name, value);
      await expect(
        fetchDevelopmentMediaUpstream(source(), { ...init, headers }),
      ).rejects.toThrow("Local media upstream");
    }
    expect(nativeRequest).not.toHaveBeenCalled();
  });

  it("forwards canonical Range and captions unchanged", async () => {
    const native = harness(200, { "content-type": "text/vtt" });
    const init = options();
    const headers = new Headers(init.headers);
    headers.set("range", "bytes=0-2");
    const pending = fetchDevelopmentMediaUpstream(source(), {
      ...init,
      headers,
    });
    native.respond();
    const response = await pending;
    expect(response.headers.get("content-type")).toBe("text/vtt");
    expect(nativeRequest.mock.calls[0][1].headers.range).toBe("bytes=0-2");
    await response.body!.cancel();
  });

  it("never opens a request for an already aborted signal", async () => {
    const controller = new AbortController();
    controller.abort(new Error(source()));
    await expect(
      fetchDevelopmentMediaUpstream(
        source(),
        options({ signal: controller.signal }),
      ),
    ).rejects.toThrow("Local media upstream");
    expect(nativeRequest).not.toHaveBeenCalled();
  });

  it("cancels a pending header request without exposing the abort reason", async () => {
    const native = harness();
    const controller = new AbortController();
    const pending = fetchDevelopmentMediaUpstream(
      source(),
      options({ signal: controller.signal }),
    );
    controller.abort(new Error(source()));
    await expect(pending).rejects.toThrow(
      "Local media upstream is unavailable or cancelled.",
    );
    expect(native.request.destroy).toHaveBeenCalledOnce();
    native.respond();
    expect(native.message.destroyed).toBe(true);
  });

  it("retains cancellation through body consumption and removes the listener afterwards", async () => {
    const native = harness();
    const controller = new AbortController();
    const remove = vi.spyOn(controller.signal, "removeEventListener");
    const pending = fetchDevelopmentMediaUpstream(
      source(),
      options({ signal: controller.signal }),
    );
    native.respond();
    const response = await pending;
    const reading = response.arrayBuffer();
    controller.abort(new Error(source()));
    await expect(reading).rejects.toThrow(
      "Local media upstream is unavailable or cancelled.",
    );
    expect(native.message.destroyed).toBe(true);
    expect(native.request.destroy).toHaveBeenCalledOnce();
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  it("sanitizes native request and truncated-body failures without framework/cache diagnostics", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const error = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const native = harness();
    const first = fetchDevelopmentMediaUpstream(source(), options());
    native.request.emit("error", new Error(source()));
    await expect(first).rejects.toThrow(
      "Local media upstream is unavailable or cancelled.",
    );
    const secondNative = harness();
    const second = fetchDevelopmentMediaUpstream(source(), options());
    secondNative.respond();
    const response = await second;
    const reading = response.arrayBuffer();
    secondNative.message.destroy(new Error(source()));
    await expect(reading).rejects.toThrow(
      "Local media upstream is unavailable or cancelled.",
    );
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("does not eagerly consume an entire unrequested upstream body", async () => {
    const native = harness();
    const pending = fetchDevelopmentMediaUpstream(source(), options());
    native.respond();
    const response = await pending;
    let written = 0;
    // Let the Node/Web bridge drain repeatedly without a downstream reader.
    // A chunk-count (rather than byte-count) high-water mark would buffer the
    // full synthetic MiB here; stop producing there even if the guard regresses.
    for (let turn = 0; turn < 20; turn += 1) {
      while (!native.message.writableNeedDrain && written < 1024 * 1024) {
        native.message.write(Buffer.alloc(16 * 1024));
        written += 16 * 1024;
      }
      await new Promise((resolve) => setImmediate(resolve));
    }
    expect(written).toBeLessThanOrEqual(128 * 1024);
    await response.body!.cancel();
    expect(native.message.destroyed).toBe(true);
  });
});

it("proves the installed Next no-store HMR fetch path can log synthetic signed input on a truncated body", () => {
  const require = createRequire(import.meta.url);
  const patchFetchModule = require.resolve("next/dist/server/lib/patch-fetch");
  const probe = spawnSync(
    process.execPath,
    [
      "-e",
      `
    globalThis.AsyncLocalStorage = require('node:async_hooks').AsyncLocalStorage;
    const { createPatchedFetcher } = require(${JSON.stringify(patchFetchModule)});
    const marker = 'synthetic-invalid-outbound-probe';
    const warnings = [];
    console.warn = (...args) => warnings.push(args.map(String).join(' '));
    console.error = (...args) => warnings.push(args.map(String).join(' '));
    const workStore = { route: '/v1/[...path]', forceDynamic: true, isStaticGeneration: false, incrementalCache: { generateCacheKey: async () => 'synthetic-cache-key' } };
    const unit = { type: 'request', phase: 'action', serverComponentsHmrCache: { get: () => undefined, set: () => {} } };
    const fetcher = createPatchedFetcher(async () => new Response(new ReadableStream({ pull(c) { c.error(new Error('Synthetic truncated upstream')); } }), { status: 200 }), { workAsyncStorage: { getStore: () => workStore }, workUnitAsyncStorage: { getStore: () => unit } });
    (async () => {
      try { const response = await fetcher('https://staging.authorityclosers.com/v1/media/playback/fixture?token=' + marker, { cache: 'no-store', signal: new AbortController().signal }); await response.arrayBuffer(); } catch {}
      await Promise.all(Object.values(workStore.pendingRevalidates || {}));
      process.stdout.write(JSON.stringify({ markerLogged: warnings.some(line => line.includes(marker)), count: warnings.length }));
    })().catch(() => { process.stderr.write('Synthetic framework probe failed'); process.exitCode = 1; });
  `,
    ],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        NODE_ENV: "development",
        NEXT_TRACE_SPAN_THRESHOLD_MS: "9007199254740991",
      },
      timeout: 15000,
    },
  );
  expect(probe.status).toBe(0);
  expect(probe.stderr).toBe("");
  expect(JSON.parse(probe.stdout)).toEqual({ markerLogged: true, count: 1 });
});
