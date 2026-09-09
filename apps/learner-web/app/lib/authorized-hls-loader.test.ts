// @vitest-environment node
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import type {
  LoaderCallbacks,
  LoaderConfiguration,
  LoaderContext,
  LoaderResponse,
  LoaderStats,
} from "hls.js";
import { afterEach, expect, it, vi } from "vitest";
import { createAuthorizedHlsLoader } from "./authorized-hls-loader";

const source =
  "https://learner.example.invalid/v1/media/playback/approved?token=SYNTHETIC";
const manifest = "#EXTM3U\n#EXT-X-VERSION:3\n";
const context = (patch: Partial<LoaderContext> = {}): LoaderContext => ({
  url: source,
  responseType: "text",
  type: "manifest" as LoaderContext["type"],
  ...patch,
});
const fragment = (patch: Partial<LoaderContext> = {}) =>
  context({
    responseType: "arraybuffer",
    type: "media-fragment" as LoaderContext["type"],
    rangeStart: 0,
    rangeEnd: 0,
    ...patch,
  });
const config = (first = 5000, total = 10_000): LoaderConfiguration => ({
  loadPolicy: {
    maxTimeToFirstByteMs: first,
    maxLoadTimeMs: total,
    errorRetry: null,
    timeoutRetry: null,
  },
  maxRetry: 10,
  timeout: total,
  retryDelay: 1,
  maxRetryDelay: 10,
});
const response = (
  body: BodyInit | null = manifest,
  mime = "application/vnd.apple.mpegurl",
  headers: HeadersInit = {},
) =>
  new Response(body, {
    headers: {
      "content-type": mime,
      ...Object.fromEntries(new Headers(headers)),
    },
  });
const live: { destroy(): void }[] = [];
afterEach(() => {
  for (const loader of live.splice(0)) loader.destroy();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
type Outcome =
  | { kind: "success"; response: LoaderResponse; stats: LoaderStats }
  | { kind: "error"; code: number; text: string }
  | { kind: "timeout" | "abort" };
function harness(
  fetcher: typeof fetch,
  ctx = context(),
  policy = config(),
  allowedUrl: (url: string) => boolean = (url) => url === source,
) {
  let finish!: (value: Outcome) => void;
  const done = new Promise<Outcome>((resolve) => {
    finish = resolve;
  });
  const callbacks: LoaderCallbacks<LoaderContext> = {
    onSuccess: vi.fn((value, stats) =>
      finish({ kind: "success", response: value, stats }),
    ),
    onError: vi.fn((error) => finish({ kind: "error", ...error })),
    onTimeout: vi.fn(() => finish({ kind: "timeout" })),
    onAbort: vi.fn(() => finish({ kind: "abort" })),
    onProgress: vi.fn(),
  };
  const onDenied = vi.fn();
  const Loader = createAuthorizedHlsLoader({
    allowedUrl,
    fetch: fetcher,
    onDenied,
  });
  const loader = new Loader();
  live.push(loader);
  const stats = loader.stats;
  loader.load(ctx, policy, callbacks);
  return { loader, stats, callbacks, done, onDenied };
}
const fetchReply = (value: Response) => vi.fn<typeof fetch>(async () => value);

it("uses exact approved URL and strict fetch flags, never forwarding context headers", async () => {
  const fetcher = fetchReply(response());
  const ctx = context({
    headers: {
      Authorization: "PRIVATE",
      Cookie: "PRIVATE",
      "x-forwarded-host": "remote",
    },
  });
  const task = harness(fetcher, ctx);
  const result = await task.done;
  expect(result.kind).toBe("success");
  expect(fetcher).toHaveBeenCalledExactlyOnceWith(
    source,
    expect.objectContaining({
      method: "GET",
      mode: "same-origin",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal: expect.any(AbortSignal),
    }),
  );
  const headers = new Headers(fetcher.mock.calls[0][1]?.headers);
  expect([...headers.keys()]).toEqual(["accept"]);
  expect(task.callbacks.onSuccess).toHaveBeenCalledWith(
    expect.objectContaining({ url: source, data: manifest, code: 200 }),
    task.stats,
    ctx,
    null,
  );
  expect(task.callbacks.onProgress).toHaveBeenCalledExactlyOnceWith(
    task.stats,
    ctx,
    manifest,
    null,
  );
  expect(task.loader.stats).toBe(task.stats);
  expect(task.stats).toMatchObject({
    loaded: Buffer.byteLength(manifest),
    total: Buffer.byteLength(manifest),
    retry: 0,
    aborted: false,
  });
  expect(task.stats.loading.first).toBeGreaterThanOrEqual(
    task.stats.loading.start,
  );
  expect(task.stats.loading.end).toBeGreaterThanOrEqual(
    task.stats.loading.first,
  );
  expect(task.stats.bwEstimate).toBeGreaterThan(0);
});
it.each(["manifest", "level", "audioTrack", "subtitleTrack"])(
  "loads %s playlists",
  async (type) => {
    const task = harness(
      fetchReply(response()),
      context({ type: type as LoaderContext["type"] }),
    );
    expect((await task.done).kind).toBe("success");
  },
);
it.each([
  "application/vnd.apple.mpegurl",
  "application/x-mpegurl",
  "audio/mpegurl",
  "audio/x-mpegurl",
  "text/plain; charset=utf-8",
])("accepts actual HLS text MIME %s", async (mime) => {
  expect((await harness(fetchReply(response(manifest, mime))).done).kind).toBe(
    "success",
  );
});
it.each(["video/mp2t", "video/mp4", "audio/mp4", "application/mp4"])(
  "loads bounded %s fragments and treats installed zero/zero range as absent",
  async (mime) => {
    const fetcher = fetchReply(response(new Uint8Array([0x47, 1, 2]), mime));
    const result = await harness(fetcher, fragment()).done;
    expect(result.kind).toBe("success");
    if (result.kind === "success")
      expect(new Uint8Array(result.response.data as ArrayBuffer)).toEqual(
        new Uint8Array([0x47, 1, 2]),
      );
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).has("range")).toBe(
      false,
    );
  },
);
it("supports UTF-8 WebVTT subtitle fragments as arraybuffer, not as arbitrary TS content", async () => {
  const subtitle = { ...fragment(), frag: { type: "subtitle" } };
  const vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\nHello.\n";
  const task = harness(fetchReply(response(vtt, "text/vtt")), subtitle);
  const result = await task.done;
  expect(result.kind).toBe("success");
  if (result.kind === "success")
    expect(new TextDecoder().decode(result.response.data as ArrayBuffer)).toBe(
      vtt,
    );
  expect(
    (await harness(fetchReply(response("not-vtt", "text/vtt")), subtitle).done)
      .kind,
  ).toBe("error");
  expect(
    (await harness(fetchReply(response(vtt, "text/vtt")), fragment()).done)
      .kind,
  ).toBe("error");
  expect(
    (
      await harness(
        fetchReply(
          response("WEBVTT\n" + "x".repeat(2 * 1024 * 1024), "text/vtt"),
        ),
        subtitle,
      ).done
    ).kind,
  ).toBe("error");
});
it.each([
  "javascript:alert(1)",
  "https://user:password@learner.example.invalid/",
  `${source}#fragment`,
  `${source} `,
  "https://external.invalid/segment",
])("withholds unsafe/unapproved source before fetch", async (url) => {
  const fetcher = vi.fn<typeof fetch>();
  const task = harness(fetcher, context({ url }));
  expect(await task.done).toMatchObject({ kind: "error", code: 403 });
  expect(task.onDenied).toHaveBeenCalledOnce();
  expect(fetcher).not.toHaveBeenCalled();
});
it("fails closed if the URL predicate throws, without exposing its diagnostic", async () => {
  const fetcher = vi.fn<typeof fetch>();
  const task = harness(fetcher, context(), config(), () => {
    throw new Error("PRIVATE_PREDICATE");
  });
  expect(await task.done).toEqual({
    kind: "error",
    code: 403,
    text: "Authorized lesson media could not be loaded.",
  });
  expect(fetcher).not.toHaveBeenCalled();
});
it.each([
  "key",
  "steering-manifest",
  "server-certificate",
  "interstitial-asset-list",
])("does not activate unsupported %s requests", async (type) => {
  const fetcher = vi.fn<typeof fetch>();
  expect(
    (
      await harness(fetcher, context({ type: type as LoaderContext["type"] }))
        .done
    ).kind,
  ).toBe("error");
  expect(fetcher).not.toHaveBeenCalled();
});
it.each([
  context({ responseType: "arraybuffer" }),
  fragment({ responseType: "text" }),
  fragment({ rangeStart: -1, rangeEnd: 4 }),
  fragment({ rangeStart: 4, rangeEnd: 4 }),
  fragment({ rangeStart: 0, rangeEnd: 32 * 1024 * 1024 + 1 }),
  fragment({ rangeStart: 0.5, rangeEnd: 4 }),
  fragment({ rangeEnd: undefined }),
  context({ rangeStart: 0, rangeEnd: 4 }),
])(
  "rejects incompatible context and malformed ranges before network",
  async (ctx) => {
    const fetcher = vi.fn<typeof fetch>();
    expect((await harness(fetcher, ctx).done).kind).toBe("error");
    expect(fetcher).not.toHaveBeenCalled();
  },
);
it("sends exclusive rangeEnd as inclusive HTTP range and validates the actual partial response", async () => {
  const fetcher = fetchReply(
    new Response(new Uint8Array([1, 2, 3]), {
      status: 206,
      headers: {
        "content-type": "video/mp4",
        "content-range": "bytes 5-7/30",
        "content-length": "3",
      },
    }),
  );
  expect(
    (await harness(fetcher, fragment({ rangeStart: 5, rangeEnd: 8 })).done)
      .kind,
  ).toBe("success");
  expect(new Headers(fetcher.mock.calls[0][1]?.headers).get("range")).toBe(
    "bytes=5-7",
  );
});
it.each(["bytes 4-7/30", "bytes 5-8/30", "bytes 5-7/7", "bytes 5-7/*", ""])(
  "rejects range response mismatch %s",
  async (range) => {
    const reply = new Response(new Uint8Array([1, 2, 3]), {
      status: 206,
      headers: { "content-type": "video/mp4", "content-range": range },
    });
    expect(
      (
        await harness(
          fetchReply(reply),
          fragment({ rangeStart: 5, rangeEnd: 8 }),
        ).done
      ).kind,
    ).toBe("error");
  },
);
it.each([401, 403, 410])(
  "reports %s denial once without retry or native diagnostics",
  async (status) => {
    const cancelled = vi.fn();
    const fetcher = fetchReply(
      new Response(new ReadableStream({ cancel: cancelled }), {
        status,
        statusText: "PRIVATE_NATIVE_DETAIL",
      }),
    );
    const task = harness(fetcher);
    expect(await task.done).toEqual({
      kind: "error",
      code: status,
      text: "Authorized lesson media could not be loaded.",
    });
    expect(task.onDenied).toHaveBeenCalledOnce();
    expect(cancelled).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledOnce();
    expect(task.callbacks.onError).toHaveBeenCalledWith(
      expect.any(Object),
      expect.any(Object),
      null,
      task.stats,
    );
  },
);
it.each([404, 429, 500, 503])(
  "sanitizes ordinary HTTP %s failures without retries",
  async (status) => {
    const fetcher = fetchReply(new Response("PRIVATE", { status }));
    const task = harness(fetcher);
    expect(await task.done).toMatchObject({ kind: "error", code: status });
    expect(task.onDenied).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledOnce();
  },
);
it.each([
  () => response(manifest, "text/html"),
  () => response("not a playlist", "text/plain"),
  () => response(new Uint8Array([255]), "application/vnd.apple.mpegurl"),
  () => response(null),
  () =>
    response(manifest, "application/vnd.apple.mpegurl", {
      "content-length": "999",
    }),
  () =>
    response(manifest, "application/vnd.apple.mpegurl", {
      "content-length": "1",
    }),
  () =>
    response(manifest, "application/vnd.apple.mpegurl", {
      "content-length": "NaN",
    }),
  () =>
    response(manifest, "application/vnd.apple.mpegurl", {
      "content-encoding": "gzip",
    }),
])(
  "rejects malformed, mismatched or unsupported delivery before progress callbacks",
  async (make) => {
    const task = harness(fetchReply(make()));
    expect((await task.done).kind).toBe("error");
    expect(task.callbacks.onProgress).not.toHaveBeenCalled();
    expect(task.callbacks.onSuccess).not.toHaveBeenCalled();
  },
);
it.each([false, true])(
  "bounds streamed manifest bytes with declared length=%s",
  async (declared) => {
    const task = harness(
      fetchReply(
        response(
          "#EXTM3U\n" + "x".repeat(2 * 1024 * 1024),
          "application/vnd.apple.mpegurl",
          declared ? { "content-length": "8" } : {},
        ),
      ),
    );
    expect((await task.done).kind).toBe("error");
    expect(task.callbacks.onProgress).not.toHaveBeenCalled();
  },
);
it("rejects oversized declared segments without reading the body, and bounds chunked segments", async () => {
  const cancel = vi.fn();
  const declared = new Response(new ReadableStream({ cancel }), {
    headers: {
      "content-type": "video/mp4",
      "content-length": String(32 * 1024 * 1024 + 1),
    },
  });
  expect((await harness(fetchReply(declared), fragment()).done).kind).toBe(
    "error",
  );
  expect(cancel).toHaveBeenCalledOnce();
  const chunk = new Uint8Array(1024 * 1024);
  let count = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (++count <= 33) controller.enqueue(chunk);
      else controller.close();
    },
  });
  const task = harness(fetchReply(response(stream, "video/mp2t")), fragment());
  expect((await task.done).kind).toBe("error");
  expect(task.callbacks.onProgress).not.toHaveBeenCalled();
});
it("counts streamed bytes and waits for validation before emitting completed progress", async () => {
  let enqueue!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      enqueue = controller;
    },
  });
  const task = harness(fetchReply(response(stream, "video/mp2t")), fragment());
  await Promise.resolve();
  enqueue.enqueue(new Uint8Array([1, 2]));
  await vi.waitFor(() => expect(task.stats.loaded).toBe(2));
  expect(task.callbacks.onProgress).not.toHaveBeenCalled();
  enqueue.enqueue(new Uint8Array([3]));
  enqueue.close();
  expect((await task.done).kind).toBe("success");
  expect(task.stats.loaded).toBe(3);
  expect(task.callbacks.onProgress).toHaveBeenCalledOnce();
});
it("rechecks authorization before attaching received bytes", async () => {
  let allowed = true;
  const fetcher = vi.fn<typeof fetch>(async () => {
    allowed = false;
    return response();
  });
  const task = harness(fetcher, context(), config(), () => allowed);
  expect(await task.done).toMatchObject({ kind: "error", code: 403 });
  expect(task.onDenied).toHaveBeenCalledOnce();
  expect(task.callbacks.onSuccess).not.toHaveBeenCalled();
});
it("refuses redirected or different response URLs even from a custom fetcher", async () => {
  for (const field of ["redirected", "url"] as const) {
    const reply = response();
    Object.defineProperty(reply, field, {
      value: field === "redirected" ? true : "https://external.invalid/media",
    });
    expect((await harness(fetchReply(reply)).done).kind).toBe("error");
  }
});
it("real fetch refuses HTTP redirects without requesting their destination", async () => {
  let destinationCalls = 0;
  const server = createServer((request, reply) => {
    if (request.url === "/start")
      reply.writeHead(302, { location: "/destination" }).end();
    else {
      destinationCalls++;
      reply
        .writeHead(200, { "content-type": "application/vnd.apple.mpegurl" })
        .end(manifest);
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/start`;
  try {
    expect(
      (
        await harness(
          fetch,
          context({ url }),
          config(),
          (value) => value === url,
        ).done
      ).kind,
    ).toBe("error");
    expect(destinationCalls).toBe(0);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
it("sanitizes native fetch rejection and emits no console diagnostic", async () => {
  const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnLog = vi.spyOn(console, "warn").mockImplementation(() => {});
  const task = harness(
    vi.fn<typeof fetch>(async () => {
      throw new Error(`PRIVATE ${source}`);
    }),
  );
  expect(await task.done).toEqual({
    kind: "error",
    code: 0,
    text: "Authorized lesson media could not be loaded.",
  });
  expect(errorLog).not.toHaveBeenCalled();
  expect(warnLog).not.toHaveBeenCalled();
});
it("calls onTimeout and discards late responses even if fetch ignores cancellation", async () => {
  vi.useFakeTimers();
  let complete!: (value: Response) => void;
  const fetcher = vi.fn<typeof fetch>(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const task = harness(fetcher, context(), config(20, 100));
  await vi.advanceTimersByTimeAsync(20);
  expect(await task.done).toEqual({ kind: "timeout" });
  expect(task.stats.aborted).toBe(true);
  const cancel = vi.fn();
  complete(response(new ReadableStream({ cancel })));
  await vi.runAllTimersAsync();
  expect(cancel).toHaveBeenCalledOnce();
  expect(task.callbacks.onError).not.toHaveBeenCalled();
  expect(task.callbacks.onSuccess).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledOnce();
});
it("bounds invalid or infinite timeouts with a finite first-byte limit", async () => {
  vi.useFakeTimers();
  const task = harness(
    vi.fn<typeof fetch>(() => new Promise(() => {})),
    context(),
    config(Infinity, Number.NaN),
  );
  await vi.advanceTimersByTimeAsync(15_000);
  expect(await task.done).toEqual({ kind: "timeout" });
});
it("keeps the full-load deadline after receiving bytes and cancels a stalled reader", async () => {
  vi.useFakeTimers();
  const cancel = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array([0x47]));
    },
    cancel,
  });
  const task = harness(
    fetchReply(response(body, "video/mp2t")),
    fragment(),
    config(10, 40),
  );
  await vi.advanceTimersByTimeAsync(11);
  expect(task.stats.loaded).toBe(1);
  expect(task.callbacks.onTimeout).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(29);
  expect(await task.done).toEqual({ kind: "timeout" });
  expect(cancel).toHaveBeenCalledOnce();
});
it("abort notifies once and destroy silently cancels without late callbacks", async () => {
  const cancel = vi.fn();
  const task = harness(fetchReply(response(new ReadableStream({ cancel }))));
  await Promise.resolve();
  task.loader.abort();
  task.loader.abort();
  expect(await task.done).toEqual({ kind: "abort" });
  expect(cancel).toHaveBeenCalledOnce();
  expect(task.callbacks.onAbort).toHaveBeenCalledOnce();
  let complete!: (value: Response) => void;
  const late = harness(
    vi.fn<typeof fetch>(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    ),
  );
  late.loader.destroy();
  const lateCancel = vi.fn();
  complete(response(new ReadableStream({ cancel: lateCancel })));
  await Promise.resolve();
  await Promise.resolve();
  expect(lateCancel).toHaveBeenCalledOnce();
  for (const callback of Object.values(late.callbacks))
    expect(callback).not.toHaveBeenCalled();
  expect(late.loader.context).toBeNull();
});
it("cannot load after a pre-load abort or destroy", () => {
  const fetcher = vi.fn<typeof fetch>();
  const Loader = createAuthorizedHlsLoader({
    allowedUrl: () => true,
    fetch: fetcher,
  });
  for (const action of ["abort", "destroy"] as const) {
    const loader = new Loader();
    loader[action]();
    const callbacks: LoaderCallbacks<LoaderContext> = {
      onSuccess: vi.fn(),
      onError: vi.fn(),
      onTimeout: vi.fn(),
      onAbort: vi.fn(),
    };
    loader.load(context(), config(), callbacks);
    expect(fetcher).not.toHaveBeenCalled();
    for (const callback of Object.values(callbacks))
      expect(callback).not.toHaveBeenCalled();
  }
});
