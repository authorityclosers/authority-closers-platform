// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import {
  createPracticeFocusApi,
  PracticeFocusRequestError,
  type FocusRun,
  type FocusSummary,
} from "./practice-focus-api";

const attemptId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const otherId = "33333333-3333-4333-8333-333333333333";
const now = "2026-09-08T10:00:00+00:00";
const signal = () => new AbortController().signal;
const revision = () => ({ expected_revision: 2, expected_attempt_revision: 0 });
const run = (patch: Partial<FocusRun> = {}): FocusRun => ({
  id: runId,
  attempt_id: attemptId,
  set_id: "next-move",
  state: "active",
  started_at: now,
  finished_at: null,
  exit_cost: 0,
  completion_restore: 0,
  ...patch,
});
const summary = (patch: Partial<FocusSummary> = {}): FocusSummary => ({
  policy_version: "arcade-focus-local-2026-09-08-v1",
  charges: 3,
  capacity: 3,
  revision: 2,
  local_day: "2026-09-08",
  timezone: "Asia/Kolkata",
  active_run: null,
  ...patch,
});
const result = (
  value = run(),
  active: FocusRun | null = value.state === "active" ? value : null,
) => ({
  summary: summary({ active_run: active }),
  run: value,
});
const fetchReply = (value: unknown) =>
  vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
    async () => Response.json(value),
  );
afterEach(() => vi.useRealTimers());

it("reads the server summary without inventing timezone, balances or command headers", async () => {
  const absent = summary({ timezone: null, local_day: null, revision: 0 });
  const fetcher = fetchReply(absent);
  expect(await createPracticeFocusApi(fetcher).summary(signal())).toEqual(
    absent,
  );
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe("/v1/practice/focus");
  expect(options).toMatchObject({
    method: "GET",
    mode: "same-origin",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  expect(options?.body).toBeUndefined();
  expect([...new Headers(options?.headers).keys()]).toEqual(["accept"]);
});
it("starts and ends with exact relative routes, bounded revision bodies and caller-owned keys", async () => {
  const ended = run({ state: "ended", finished_at: now, exit_cost: 1 });
  const fetcher = vi.fn<
    (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
  >(async (input) =>
    Response.json(String(input).endsWith("/end") ? result(ended) : result()),
  );
  const api = createPracticeFocusApi(fetcher);
  expect(await api.start(attemptId, revision(), "start-key", signal())).toEqual(
    result(),
  );
  expect(await api.end(runId, revision(), "end-key", signal())).toEqual(
    result(ended),
  );
  expect(
    fetcher.mock.calls.map(([url, options]) => [
      url,
      options?.body,
      new Headers(options?.headers).get("idempotency-key"),
    ]),
  ).toEqual([
    [
      `/v1/practice/attempts/${attemptId}/focus`,
      JSON.stringify(revision()),
      "start-key",
    ],
    [
      `/v1/practice/focus/runs/${runId}/end`,
      JSON.stringify(revision()),
      "end-key",
    ],
  ]);
  for (const [, options] of fetcher.mock.calls) {
    expect(options).toMatchObject({
      method: "POST",
      mode: "same-origin",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
    const headers = new Headers(options?.headers);
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.has("origin")).toBe(false); // The browser supplies its real Origin.
    expect(headers.has("authorization")).toBe(false);
    expect(String(options?.body).length).toBeLessThan(100);
  }
});
it.each(["ended", "completed"] as const)(
  "accepts authoritative %s start replay alongside a different current active run",
  async (state) => {
    const closed = run({
      state,
      finished_at: now,
      completion_restore: state === "completed" ? 1 : 0,
    });
    const value = result(closed, run({ id: otherId, attempt_id: otherId }));
    const api = createPracticeFocusApi(fetchReply(value));
    expect(
      await api.start(attemptId, revision(), "replayed-key", signal()),
    ).toEqual(value);
    expect(
      await api.end(runId, revision(), "replayed-end-key", signal()),
    ).toEqual(value);
  },
);
it.each([0, 3])(
  "accepts the server charge boundary %s without local refill math",
  async (charges) => {
    const value = summary({ charges });
    expect(
      await createPracticeFocusApi(fetchReply(value)).summary(signal()),
    ).toEqual(value);
  },
);
it("snapshots mutable revisions, preserves stable keys and never retries or caches automatically", async () => {
  const fetcher = fetchReply(result());
  const api = createPracticeFocusApi(fetcher);
  const body = revision();
  const pending = api.start(attemptId, body, "stable-key", signal());
  body.expected_revision = 9;
  await pending;
  await api.start(attemptId, revision(), "stable-key", signal());
  fetcher.mockImplementationOnce(async () =>
    Response.json({ detail: "Key used for different input" }, { status: 409 }),
  );
  await expect(
    api.start(attemptId, body, "stable-key", signal()),
  ).rejects.toMatchObject({ status: 409, reason: "http" });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(fetcher.mock.calls.map(([, init]) => init?.body)).toEqual([
    JSON.stringify(revision()),
    JSON.stringify(revision()),
    JSON.stringify(body),
  ]);
  expect(
    fetcher.mock.calls.map(([, init]) =>
      new Headers(init?.headers).get("idempotency-key"),
    ),
  ).toEqual(["stable-key", "stable-key", "stable-key"]);
});
it.each([
  { charges: -1 },
  { charges: 4 },
  { charges: 1.5 },
  { charges: "1" },
  { capacity: 4 },
  { revision: -1 },
  { revision: Number.MAX_SAFE_INTEGER + 1 },
  { policy_version: "" },
  { local_day: "2026-02-30" },
  { local_day: null },
  { timezone: null },
  { timezone: "" },
  { credits_balance: 10 },
  { xp_total: 30 },
  { purchases_enabled: false },
  { tenant_id: otherId },
  { active_run: run({ state: "ended", finished_at: now }) },
  { active_run: run(), timezone: null, local_day: null },
])("rejects malformed or cross-domain summary %j", async (patch) => {
  await expect(
    createPracticeFocusApi(fetchReply({ ...summary(), ...patch })).summary(
      signal(),
    ),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it.each([
  { finished_at: now },
  { exit_cost: 1 },
  { completion_restore: 1 },
  { exit_cost: 2 },
  { state: "ended" },
  { state: "ended", finished_at: now, completion_restore: 1 },
  { state: "completed" },
  { state: "completed", finished_at: now, exit_cost: 1 },
  { id: "not-a-uuid" },
  { started_at: "yesterday" },
  { set_id: "../../admin" },
  { credits: 10 },
])("rejects incoherent lifecycle or run metadata %j", async (patch) => {
  const value = { ...run(), ...patch };
  await expect(
    createPracticeFocusApi(
      fetchReply({ summary: summary(), run: value }),
    ).start(attemptId, revision(), "key", signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it.each([
  result(run(), null),
  result(run(), run({ id: otherId })),
  result(run(), run({ started_at: "2026-09-08T11:00:00Z" })),
  result(run({ state: "ended", finished_at: now }), run()),
  { ...result(), receipt: { credits: 10 } },
])(
  "rejects disagreement between current summary and returned run",
  async (value) => {
    await expect(
      createPracticeFocusApi(fetchReply(value)).start(
        attemptId,
        revision(),
        "key",
        signal(),
      ),
    ).rejects.toMatchObject({ reason: "invalid_response" });
  },
);
it("checks exact command target identity and refuses an active end response", async () => {
  await expect(
    createPracticeFocusApi(
      fetchReply(result(run({ attempt_id: otherId }))),
    ).start(attemptId, revision(), "key", signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
  await expect(
    createPracticeFocusApi(
      fetchReply(
        result(run({ id: otherId, state: "ended", finished_at: now })),
      ),
    ).end(runId, revision(), "key", signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
  await expect(
    createPracticeFocusApi(fetchReply(result())).end(
      runId,
      revision(),
      "key",
      signal(),
    ),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it.each([
  "attempt_started",
  "not_eligible",
  "active_run_conflict",
  "focus_empty",
  "revision_conflict",
])(
  "exposes only allowlisted 409 reason %s, never server diagnostic text",
  async (reason) => {
    const marker = "SYNTHETIC_PRIVATE_DIAGNOSTIC";
    const fetcher = vi.fn(async () =>
      Response.json({ detail: { reason, message: marker } }, { status: 409 }),
    );
    const error = await createPracticeFocusApi(fetcher)
      .start(attemptId, revision(), "key", signal())
      .catch((value: unknown) => value);
    expect(error).toBeInstanceOf(PracticeFocusRequestError);
    expect(error).toMatchObject({ status: 409, reason });
    expect(String(error)).not.toContain(marker);
    expect(JSON.stringify(error)).not.toContain(marker);
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);
it.each([
  { detail: "revision_conflict" },
  { reason: "focus_empty" },
  { detail: { reason: "new_unknown_reason", message: "private" } },
  { detail: { reason: "focus_empty", message: "private", tenant: "private" } },
  { detail: { reason: "focus_empty" } },
])("retains generic 409 for unrecognized error envelopes", async (value) => {
  await expect(
    createPracticeFocusApi(async () =>
      Response.json(value, { status: 409 }),
    ).summary(signal()),
  ).rejects.toMatchObject({ status: 409, reason: "http" });
});
it.each([400, 401, 403, 404, 422, 500])(
  "does not interpret %s error bodies as domain conflicts",
  async (status) => {
    const cancelled = vi.fn();
    const response = new Response(new ReadableStream({ cancel: cancelled }), {
      status,
    });
    await expect(
      createPracticeFocusApi(async () => response).summary(signal()),
    ).rejects.toMatchObject({ status, reason: "http" });
    expect(cancelled).toHaveBeenCalledOnce();
  },
);
it.each([
  "../../admin",
  "https://external.invalid",
  `${attemptId}?person_id=${otherId}`,
])("refuses path injection %s before transport", (id) => {
  const fetcher = vi.fn();
  const api = createPracticeFocusApi(fetcher);
  expect(() => api.start(id, revision(), "key", signal())).toThrow(
    PracticeFocusRequestError,
  );
  expect(() => api.end(id, revision(), "key", signal())).toThrow(
    PracticeFocusRequestError,
  );
  expect(fetcher).not.toHaveBeenCalled();
});
it.each([
  { expected_revision: -1, expected_attempt_revision: 0 },
  { expected_revision: 0, expected_attempt_revision: 0.5 },
  { expected_revision: "1", expected_attempt_revision: 0 },
  {
    expected_revision: Number.MAX_SAFE_INTEGER + 1,
    expected_attempt_revision: 0,
  },
  { expected_revision: 0 },
  { ...revision(), credits: 999 },
  { ...revision(), person_id: otherId },
])("refuses unsupported revision bodies before transport", async (body) => {
  const fetcher = vi.fn();
  await expect(
    createPracticeFocusApi(fetcher).start(
      attemptId,
      body as never,
      "key",
      signal(),
    ),
  ).rejects.toMatchObject({ reason: "invalid_request" });
  expect(fetcher).not.toHaveBeenCalled();
});
it.each(["", "key\nforged", "white space", "x".repeat(129)])(
  "refuses an invalid caller command key before transport",
  async (key) => {
    const fetcher = vi.fn();
    await expect(
      createPracticeFocusApi(fetcher).start(
        attemptId,
        revision(),
        key,
        signal(),
      ),
    ).rejects.toMatchObject({ reason: "invalid_request" });
    expect(fetcher).not.toHaveBeenCalled();
  },
);
it("accepts exactly 128 visible ASCII key bytes and maximum safe revisions", async () => {
  const fetcher = fetchReply(result());
  await createPracticeFocusApi(fetcher).start(
    attemptId,
    {
      expected_revision: Number.MAX_SAFE_INTEGER,
      expected_attempt_revision: Number.MAX_SAFE_INTEGER,
    },
    "x".repeat(128),
    signal(),
  );
  expect(String(fetcher.mock.calls[0][1]?.body).length).toBeLessThan(100);
});
it.each([
  () => new Response("{}", { headers: { "content-type": "text/html" } }),
  () =>
    new Response("broken", { headers: { "content-type": "application/json" } }),
  () =>
    new Response(new Uint8Array([0xff]), {
      headers: { "content-type": "application/json" },
    }),
  () => new Response(null, { headers: { "content-type": "application/json" } }),
])(
  "refuses non-JSON, malformed, invalid UTF-8 and missing success bodies",
  async (response) => {
    await expect(
      createPracticeFocusApi(async () => response()).summary(signal()),
    ).rejects.toMatchObject({ reason: "invalid_response" });
  },
);
it("caps declared and streamed success body sizes before accepting any state", async () => {
  const cancel = vi.fn();
  const declared = new Response(new ReadableStream({ cancel }), {
    headers: {
      "content-type": "application/json",
      "content-length": String(64 * 1024 + 1),
    },
  });
  await expect(
    createPracticeFocusApi(async () => declared).summary(signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
  expect(cancel).toHaveBeenCalledOnce();
  const streamed = new Response(" ".repeat(64 * 1024 + 1), {
    headers: { "content-type": "application/json" },
  });
  await expect(
    createPracticeFocusApi(async () => streamed).summary(signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it("limits conflict diagnostics separately and falls back to generic HTTP status", async () => {
  const body = {
    detail: { reason: "focus_empty", message: "x".repeat(8 * 1024) },
  };
  await expect(
    createPracticeFocusApi(async () =>
      Response.json(body, { status: 409 }),
    ).summary(signal()),
  ).rejects.toMatchObject({ status: 409, reason: "http" });
});
it("redacts native network errors without retrying", async () => {
  const fetcher = vi.fn(async () => {
    throw new Error("SYNTHETIC_PRIVATE_DIAGNOSTIC");
  });
  const error = await createPracticeFocusApi(fetcher)
    .summary(signal())
    .catch((value: unknown) => value);
  expect(error).toMatchObject({ status: 0, reason: "network" });
  expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_DIAGNOSTIC");
  expect(fetcher).toHaveBeenCalledOnce();
});
it("does not fetch when the caller already aborted", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetcher = vi.fn();
  await expect(
    createPracticeFocusApi(fetcher).summary(controller.signal),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(fetcher).not.toHaveBeenCalled();
});
it("times out a non-cooperative fetch and cancels its late response", async () => {
  vi.useFakeTimers();
  let complete: (response: Response) => void = () => {};
  const fetcher = vi.fn<
    (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
  >(
    () =>
      new Promise<Response>((resolve) => {
        complete = resolve;
      }),
  );
  const pending = createPracticeFocusApi(fetcher).summary(signal());
  const assertion = expect(pending).rejects.toMatchObject({
    reason: "timeout",
  });
  await vi.advanceTimersByTimeAsync(12_000);
  await assertion;
  const cancel = vi.fn();
  complete(
    new Response(new ReadableStream({ cancel }), {
      headers: { "content-type": "application/json" },
    }),
  );
  await vi.runAllTimersAsync();
  expect(cancel).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
});
it.each([200, 409])(
  "cancels a stalled %s body, preserves AbortError and removes caller listeners",
  async (status) => {
    const cancel = vi.fn();
    const response = new Response(new ReadableStream({ cancel }), {
      status,
      headers: { "content-type": "application/json" },
    });
    const controller = new AbortController();
    const cleanup = vi.spyOn(controller.signal, "removeEventListener");
    const pending = createPracticeFocusApi(async () => response).summary(
      controller.signal,
    );
    const assertion = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    await Promise.resolve();
    controller.abort();
    await assertion;
    expect(cancel).toHaveBeenCalledOnce();
    expect(cleanup).toHaveBeenCalledWith("abort", expect.any(Function));
  },
);
