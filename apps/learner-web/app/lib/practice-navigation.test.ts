import { afterEach, expect, it, vi } from "vitest";
import { loadPracticeNavigationAvailability } from "./practice-navigation";

afterEach(() => vi.useRealTimers());
const profile = () =>
  vi.fn(async () => ({
    timezone: null,
    revision: 0,
    pending_timezone: null,
    pending_effective_at: null,
  }));
const response = (value: unknown) => Response.json(value);

it("requires runtime availability and a real admitted self profile with bounded private transport", async () => {
  const readProfile = profile();
  const fetcher = vi.fn(async () => response({ enabled: true }));
  expect(
    await loadPracticeNavigationAvailability(
      new AbortController().signal,
      fetcher,
      { profile: readProfile },
    ),
  ).toBe(true);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0]).toEqual([
    "/practice/availability",
    expect.objectContaining({
      method: "GET",
      mode: "same-origin",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal: expect.any(AbortSignal),
    }),
  ]);
  expect(readProfile).toHaveBeenCalledOnce();
});
it.each([false, "true", null, 1])(
  "does not infer admission from enabled=%j",
  async (enabled) => {
    const readProfile = profile();
    expect(
      await loadPracticeNavigationAvailability(
        new AbortController().signal,
        async () => response({ enabled }),
        { profile: readProfile },
      ),
    ).toBe(false);
    expect(readProfile).not.toHaveBeenCalled();
  },
);
it.each([401, 403, 404, 500])(
  "hides gracefully when runtime availability is HTTP %i",
  async (status) => {
    const readProfile = profile();
    expect(
      await loadPracticeNavigationAvailability(
        new AbortController().signal,
        async () => new Response("Unavailable", { status }),
        { profile: readProfile },
      ),
    ).toBe(false);
    expect(readProfile).not.toHaveBeenCalled();
  },
);
it("hides when current API tenant/session admission fails, with no fallback", async () => {
  const readProfile = vi.fn(async () => {
    throw new Error("private underlying failure");
  });
  expect(
    await loadPracticeNavigationAvailability(
      new AbortController().signal,
      async () => response({ enabled: true }),
      { profile: readProfile },
    ),
  ).toBe(false);
  expect(readProfile).toHaveBeenCalledOnce();
});
it.each([
  () =>
    new Response('{"enabled":true}', {
      headers: { "content-type": "text/html" },
    }),
  () => response({ enabled: true, tenant_id: "untrusted" }),
  () =>
    new Response("x".repeat(1025), {
      headers: { "content-type": "application/json", "content-length": "1" },
    }),
  () =>
    new Response("x".repeat(1025), {
      headers: { "content-type": "application/json" },
    }),
  () => new Response("{", { headers: { "content-type": "application/json" } }),
])("rejects malformed/unbounded runtime data", async (makeResponse) => {
  const readProfile = profile();
  expect(
    await loadPracticeNavigationAvailability(
      new AbortController().signal,
      async () => makeResponse(),
      { profile: readProfile },
    ),
  ).toBe(false);
  expect(readProfile).not.toHaveBeenCalled();
});
it("refuses redirects even when a fetch implementation returns them", async () => {
  const redirected = response({ enabled: true });
  Object.defineProperty(redirected, "redirected", { value: true });
  const readProfile = profile();
  expect(
    await loadPracticeNavigationAvailability(
      new AbortController().signal,
      async () => redirected,
      { profile: readProfile },
    ),
  ).toBe(false);
  expect(readProfile).not.toHaveBeenCalled();
});
it("does not fetch after caller cancellation", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetcher = vi.fn();
  expect(
    await loadPracticeNavigationAvailability(controller.signal, fetcher, {
      profile: profile(),
    }),
  ).toBe(false);
  expect(fetcher).not.toHaveBeenCalled();
});
it("bounds a stalled fetch and aborts its actual request", async () => {
  vi.useFakeTimers();
  let requestSignal: AbortSignal | undefined;
  const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    requestSignal = init?.signal ?? undefined;
    return new Promise<Response>(() => undefined);
  });
  const operation = loadPracticeNavigationAvailability(
    new AbortController().signal,
    fetcher,
    { profile: profile() },
  );
  await vi.advanceTimersByTimeAsync(6_000);
  expect(await operation).toBe(false);
  expect(requestSignal?.aborted).toBe(true);
});
it("cancels a stalled response body", async () => {
  const controller = new AbortController();
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({ cancel });
  const operation = loadPracticeNavigationAvailability(
    controller.signal,
    async () =>
      new Response(stream, { headers: { "content-type": "application/json" } }),
    { profile: profile() },
  );
  await Promise.resolve();
  await Promise.resolve();
  controller.abort();
  expect(await operation).toBe(false);
  expect(cancel).toHaveBeenCalledOnce();
});
