import { afterEach, expect, it, vi } from "vitest";
import {
  callCoachingBinding as binding,
  fictionalCallCoaching,
} from "./report-call-coaching.fixture";
import { readCallCoaching } from "./report-call-coaching-client";

afterEach(() => vi.unstubAllGlobals());

it("stops an oversized stream before its tail arrives", async () => {
  const cancel = vi.fn();
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(stream) {
        stream.enqueue(new Uint8Array(128_001));
      },
      cancel,
    }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
  const controller = new AbortController();
  let failure: unknown;
  const pending = readCallCoaching(binding, controller.signal).catch(
    (error: unknown) => {
      failure = error;
    },
  );
  try {
    await vi.waitFor(() => expect(failure).toBeInstanceOf(Error), {
      timeout: 150,
      interval: 10,
    });
    expect((failure as Error).message).toContain("unavailable");
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body?.locked).toBe(false);
  } finally {
    controller.abort();
    await pending;
    await response.body?.cancel();
  }
});

it("cancels a stalled body when its read scope expires", async () => {
  const cancel = vi.fn();
  let began: (() => void) | undefined;
  const reading = new Promise<void>((resolve) => {
    began = resolve;
  });
  const response = new Response(
    new ReadableStream<Uint8Array>({
      pull() {
        began?.();
        return new Promise(() => {});
      },
      cancel,
    }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
  const controller = new AbortController();
  const rejected = expect(
    readCallCoaching(binding, controller.signal),
  ).rejects.toThrow("unavailable");
  await reading;
  // Give the response reader time to acquire the body before scope loss.
  for (let index = 0; index < 8; index++) await Promise.resolve();
  controller.abort();
  try {
    await rejected;
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce());
    expect(response.body?.locked).toBe(false);
  } finally {
    await response.body?.cancel();
  }
});

it("rejects an oversized declared body without buffering it", async () => {
  const response = new Response(JSON.stringify(fictionalCallCoaching()), {
    headers: { "content-length": "128001" },
  });
  const buffer = vi.spyOn(response, "text");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
  await expect(
    readCallCoaching(binding, new AbortController().signal),
  ).rejects.toThrow("unavailable");
  expect(buffer).not.toHaveBeenCalled();
});

it("counts Devanagari UTF-8 bytes rather than decoded characters", async () => {
  const payload = {
    ...fictionalCallCoaching(),
    provider_extras: "अ".repeat(43_000),
  };
  const body = JSON.stringify(payload);
  expect(body.length).toBeLessThan(128_000);
  expect(new TextEncoder().encode(body).byteLength).toBeGreaterThan(128_000);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body)),
  );
  await expect(
    readCallCoaching(binding, new AbortController().signal),
  ).rejects.toThrow("unavailable");
});

it("decodes a valid Devanagari lesson across split UTF-8 chunks", async () => {
  const payload = fictionalCallCoaching();
  payload.lesson.quick_idea = "समस्या का असर क्या है?";
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const firstHindiByte = bytes.findIndex((value) => value >= 128);
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(stream) {
        stream.enqueue(bytes.slice(0, firstHindiByte + 1));
        stream.enqueue(bytes.slice(firstHindiByte + 1));
        stream.close();
      },
    }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
  const view = await readCallCoaching(binding, new AbortController().signal);
  expect(view.lesson?.quick_idea).toBe(payload.lesson.quick_idea);
  expect(view.evidence[0]).toEqual(payload.evidence[0]);
  expect(response.body?.locked).toBe(false);
});

it("rejects corrupt UTF-8 instead of showing a silently changed lesson", async () => {
  const body = new TextEncoder().encode(
    JSON.stringify(fictionalCallCoaching()),
  );
  const firstTitle = new TextDecoder().decode(body).indexOf("Fictional");
  body[firstTitle] = 0xff;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body)),
  );
  await expect(
    readCallCoaching(binding, new AbortController().signal),
  ).rejects.toThrow("unavailable");
});

it("rejects late bodies without publishing after cancellation", async () => {
  let resolve: ((response: Response) => void) | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    ),
  );
  const controller = new AbortController();
  const rejected = expect(
    readCallCoaching(binding, controller.signal),
  ).rejects.toThrow("unavailable");
  controller.abort();
  await rejected;
  const cancel = vi.fn();
  const response = new Response(new ReadableStream<Uint8Array>({ cancel }));
  resolve?.(response);
  await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce());
  expect(response.body?.locked).toBe(false);
});

it.each(["stalled", "rejected"])(
  "recovers from an oversized body even when cancellation is %s",
  async (kind) => {
    const cancel = vi.fn(() =>
      kind === "stalled"
        ? new Promise<void>(() => {})
        : Promise.reject(new Error("private adapter detail")),
    );
    const response = new Response(
      new ReadableStream<Uint8Array>({
        start(stream) {
          stream.enqueue(new Uint8Array(128_001));
        },
        cancel,
      }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response),
    );
    const controller = new AbortController();
    let failure: unknown;
    const pending = readCallCoaching(binding, controller.signal).catch(
      (error: unknown) => {
        failure = error;
      },
    );
    try {
      await vi.waitFor(() => expect(failure).toBeInstanceOf(Error), {
        timeout: 150,
        interval: 10,
      });
      expect((failure as Error).message).toContain("unavailable");
      expect((failure as Error).message).not.toContain("private");
      expect(cancel).toHaveBeenCalledOnce();
      expect(response.body?.locked).toBe(false);
    } finally {
      controller.abort();
      await pending;
    }
  },
);
