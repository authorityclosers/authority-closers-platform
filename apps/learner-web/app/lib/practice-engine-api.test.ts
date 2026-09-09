// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import {
  createPracticeEngineApi,
  PracticeEngineRequestError,
} from "./practice-engine-api";

const attemptId = "11111111-1111-4111-8111-111111111111";
const responseId = "22222222-2222-4222-8222-222222222222";
const now = "2026-09-08T10:00:00+00:00";
const signal = () => new AbortController().signal;
const profile = {
  timezone: "Asia/Kolkata",
  revision: 1,
  pending_timezone: null,
  pending_effective_at: null,
};
const publicSet = {
  id: "next-move",
  version: 1,
  title: "Choose your next move",
  kind: "choice",
  skill: "Discovery",
  description: "Practice a question.",
  art: "discovery-compass",
  color: "cobalt",
  estimated_minutes: 4,
  item_count: 1,
  mode: "editorial_preview",
  items: [
    {
      id: "choice-01",
      kind: "choice",
      prompt: "What could clarify?",
      hint: "Ask a question.",
      options: [
        { id: 0, text: "Ask what matters." },
        { id: 1, text: "Assume the answer." },
      ],
    },
  ],
};
const feedback = {
  kind: "feedback",
  reference_match: true,
  explanation: "This asks for clarification.",
  course_progress_affected: false,
  responses_stored: true,
};
const receipt = {
  id: responseId,
  kind: "daily_set",
  credits: 10,
  xp: 30,
  local_day: "2026-09-08",
  week_start: "2026-09-07",
  created_at: now,
};
const attempt = () => ({
  id: attemptId,
  set_id: "next-move",
  set_version: 1,
  content_digest: "d".repeat(64),
  state: "in_progress",
  revision: 2,
  issued_at: now,
  completed_at: null,
  set: structuredClone(publicSet),
  acknowledged_item_ids: [],
  item_states: [
    {
      item_id: "choice-01",
      response_id: responseId,
      selections: [0],
      feedback: structuredClone(feedback),
      acknowledged: false,
    },
  ],
  reward_receipts: [],
  responses_stored: true,
  course_progress_affected: false,
});
const progress = () => ({
  profile,
  credits_balance: 10,
  xp_total: 30,
  actual_practice_days_this_week: 1,
  policy_version: "earned-pilot-v1",
  recent_attempts: [
    {
      id: attemptId,
      set_id: "next-move",
      set_version: 1,
      title: "Choose your next move",
      state: "completed",
      revision: 3,
      acknowledged_count: 1,
      item_count: 1,
      issued_at: now,
      completed_at: now,
    },
  ],
  recent_awards: [receipt],
  purchases_enabled: false,
  course_progress_affected: false,
});
const reply = (data: unknown) => Response.json(data);
afterEach(() => vi.useRealTimers());

it("uses same-origin no-store reads with strict authoritative counters and no mutation headers", async () => {
  const fetcher = vi.fn(async () => reply(progress()));
  const api = createPracticeEngineApi(fetcher);
  expect(await api.progress(signal())).toEqual(progress());
  const [url, options] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(url).toBe("/v1/practice/progress");
  expect(options).toMatchObject({
    method: "GET",
    credentials: "same-origin",
    mode: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  expect(options.body).toBeUndefined();
  expect(new Headers(options.headers).has("idempotency-key")).toBe(false);
});
it("accepts an unconfigured profile and pending timezone projection without inventing state", async () => {
  const absent = {
    timezone: null,
    revision: 0,
    pending_timezone: null,
    pending_effective_at: null,
  };
  const fetcher = vi.fn(async () => reply(absent));
  expect(await createPracticeEngineApi(fetcher).profile(signal())).toEqual(
    absent,
  );
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/practice/profile",
    expect.any(Object),
  );
  const pending = {
    ...profile,
    pending_timezone: "Europe/London",
    pending_effective_at: now,
  };
  expect(
    await createPracticeEngineApi(async () => reply(pending)).profile(signal()),
  ).toEqual(pending);
});
it("returns the exact shared attempt shape from issue, read, response and acknowledgement", async () => {
  const fetcher = vi.fn(
    async (_url: RequestInfo | URL, options?: RequestInit) =>
      reply(options?.method === "PUT" ? profile : attempt()),
  );
  const api = createPracticeEngineApi(fetcher);
  expect(
    await api.updateProfile(
      { timezone: "Asia/Kolkata", expected_revision: 0 },
      "profile-key",
      signal(),
    ),
  ).toEqual(profile);
  expect(await api.issue("next-move", "issue-key", signal())).toEqual(
    attempt(),
  );
  expect(await api.attempt(attemptId, signal())).toEqual(attempt());
  expect(
    await api.respond(
      attemptId,
      { item_id: "choice-01", selections: [0], expected_revision: 1 },
      "respond-key",
      signal(),
    ),
  ).toEqual(attempt());
  expect(
    await api.acknowledge(
      attemptId,
      responseId,
      { expected_revision: 2 },
      "ack-key",
      signal(),
    ),
  ).toEqual(attempt());
  expect(
    fetcher.mock.calls.map(([url, options]) => [
      url,
      options?.method,
      new Headers(options?.headers).get("idempotency-key"),
      options?.body,
    ]),
  ).toEqual([
    [
      "/v1/practice/profile",
      "PUT",
      "profile-key",
      '{"timezone":"Asia/Kolkata","expected_revision":0}',
    ],
    ["/v1/practice/sets/next-move/attempts", "POST", "issue-key", "{}"],
    [`/v1/practice/attempts/${attemptId}`, "GET", null, undefined],
    [
      `/v1/practice/attempts/${attemptId}/responses`,
      "POST",
      "respond-key",
      '{"item_id":"choice-01","selections":[0],"expected_revision":1}',
    ],
    [
      `/v1/practice/attempts/${attemptId}/feedback/${responseId}/acknowledge`,
      "POST",
      "ack-key",
      '{"expected_revision":2}',
    ],
  ]);
});
it("pins caller payload synchronously and preserves the provided key across explicit retries", async () => {
  const fetcher = vi.fn(async () => reply(attempt()));
  const api = createPracticeEngineApi(fetcher);
  const input = { item_id: "choice-01", selections: [0], expected_revision: 1 };
  const first = api.respond(attemptId, input, "logical-response", signal());
  input.selections[0] = 1;
  input.expected_revision = 2;
  await first;
  await api.respond(
    attemptId,
    { item_id: "choice-01", selections: [0], expected_revision: 1 },
    "logical-response",
    signal(),
  );
  const options = fetcher.mock.calls.map(
    (call) => (call as unknown as [string, RequestInit])[1],
  );
  expect(options[0].body).toBe(options[1].body);
  expect(JSON.parse(String(options[0].body))).toEqual({
    item_id: "choice-01",
    selections: [0],
    expected_revision: 1,
  });
  expect(
    options.map((option) => new Headers(option.headers).get("idempotency-key")),
  ).toEqual(["logical-response", "logical-response"]);
});
it("does not cache a response or silently change keys for a changed payload", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(reply(attempt()))
    .mockResolvedValueOnce(
      Response.json({ secret: "not forwarded" }, { status: 409 }),
    );
  const api = createPracticeEngineApi(fetcher);
  await api.respond(
    attemptId,
    { item_id: "choice-01", selections: [0], expected_revision: 1 },
    "same-key",
    signal(),
  );
  await expect(
    api.respond(
      attemptId,
      { item_id: "choice-01", selections: [1], expected_revision: 1 },
      "same-key",
      signal(),
    ),
  ).rejects.toMatchObject({ status: 409 });
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(
    new Headers(fetcher.mock.calls[1][1].headers).get("idempotency-key"),
  ).toBe("same-key");
});
it.each([
  { purchases_enabled: true },
  { course_progress_affected: true },
  { credits_balance: -1 },
  { xp_total: 1.5 },
  { actual_practice_days_this_week: "1" },
  { credits_balance: Number.MAX_SAFE_INTEGER + 1 },
  { invented_streak: 5 },
])("fails closed on unsupported or malformed progress %j", async (patch) => {
  await expect(
    createPracticeEngineApi(async () =>
      reply({ ...progress(), ...patch }),
    ).progress(signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it.each([
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    responses_stored: false,
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    course_progress_affected: true,
  }),
  (value: ReturnType<typeof attempt>) => ({ ...value, set_id: "other" }),
  (value: ReturnType<typeof attempt>) => ({ ...value, set_version: 2 }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    set: { ...value.set, official_score: 100 },
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    set: { ...value.set, items: [{ ...value.set.items[0], answer: 0 }] },
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    set: {
      ...value.set,
      items: [
        {
          ...value.set.items[0],
          options: [{ id: 0, text: "Public", correct: true }],
        },
      ],
    },
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    item_states: [
      {
        ...value.item_states[0],
        feedback: { ...feedback, responses_stored: false },
      },
    ],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    issued_at: "not-an-instant",
  }),
])(
  "strictly validates pinned public content, identity and stored feedback",
  async (patch) => {
    await expect(
      createPracticeEngineApi(async () => reply(patch(attempt()))).attempt(
        attemptId,
        signal(),
      ),
    ).rejects.toMatchObject({ reason: "invalid_response" });
  },
);
it("retains exact branch continuation and terminal reward receipts without interpreting amounts", async () => {
  const value = {
    ...attempt(),
    item_states: [
      {
        ...attempt().item_states[0],
        feedback: {
          kind: "continue",
          node: {
            buyer: "Please clarify.",
            options: [{ id: 0, text: "What matters?" }],
          },
        },
      },
    ],
    reward_receipts: [receipt],
  };
  expect(
    await createPracticeEngineApi(async () => reply(value)).attempt(
      attemptId,
      signal(),
    ),
  ).toEqual(value);
});
it.each([
  { pending_timezone: "Europe/London", pending_effective_at: null },
  { pending_timezone: null, pending_effective_at: now },
])("rejects half-populated pending timezone fields", async (patch) => {
  await expect(
    createPracticeEngineApi(async () =>
      reply({ ...profile, ...patch }),
    ).profile(signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it.each([
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    acknowledged_item_ids: ["choice-01", "choice-01"],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    acknowledged_item_ids: ["other"],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    item_states: [value.item_states[0], value.item_states[0]],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    item_states: [{ ...value.item_states[0], item_id: "other" }],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    acknowledged_item_ids: ["choice-01"],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    item_states: [{ ...value.item_states[0], acknowledged: true }],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    state: "completed",
    completed_at: now,
  }),
  (value: ReturnType<typeof attempt>) => ({ ...value, completed_at: now }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    state: "completed",
    acknowledged_item_ids: ["choice-01"],
    item_states: [{ ...value.item_states[0], acknowledged: true }],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    acknowledged_item_ids: ["choice-01"],
    item_states: [{ ...value.item_states[0], acknowledged: true }],
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    set: { ...value.set, items: [value.set.items[0], value.set.items[0]] },
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    set: { ...value.set, item_count: 2 },
  }),
  (value: ReturnType<typeof attempt>) => ({
    ...value,
    reward_receipts: [receipt, receipt],
  }),
])(
  "rejects incoherent authoritative attempt progress before rendering",
  async (patch) => {
    await expect(
      createPracticeEngineApi(async () => reply(patch(attempt()))).attempt(
        attemptId,
        signal(),
      ),
    ).rejects.toMatchObject({ reason: "invalid_response" });
  },
);
it("accepts completion only with all pinned items acknowledged and a completion timestamp", async () => {
  const value = {
    ...attempt(),
    state: "completed",
    completed_at: now,
    acknowledged_item_ids: ["choice-01"],
    item_states: [{ ...attempt().item_states[0], acknowledged: true }],
    reward_receipts: [receipt],
  };
  expect(
    await createPracticeEngineApi(async () => reply(value)).attempt(
      attemptId,
      signal(),
    ),
  ).toEqual(value);
});
it.each([
  { actual_practice_days_this_week: 8 },
  { recent_awards: [receipt, receipt] },
  {
    recent_attempts: [
      { ...progress().recent_attempts[0], acknowledged_count: 2 },
    ],
  },
])(
  "rejects incoherent progress counters or duplicate receipts",
  async (patch) => {
    await expect(
      createPracticeEngineApi(async () =>
        reply({ ...progress(), ...patch }),
      ).progress(signal()),
    ).rejects.toMatchObject({ reason: "invalid_response" });
  },
);
it("rejects arbitrary paths and request-side policy injection before transport", async () => {
  const fetcher = vi.fn();
  const api = createPracticeEngineApi(fetcher);
  expect(() => api.issue("../../admin", "key", signal())).toThrow(
    PracticeEngineRequestError,
  );
  expect(() => api.attempt("https://remote.example", signal())).toThrow(
    PracticeEngineRequestError,
  );
  expect(() =>
    api.respond(
      attemptId,
      {
        item_id: "choice-01",
        selections: [0],
        expected_revision: 1,
        xp: 300,
      } as never,
      "key",
      signal(),
    ),
  ).toThrow(PracticeEngineRequestError);
  expect(() =>
    api.respond(
      attemptId,
      { item_id: "choice-01", selections: [-1], expected_revision: 1 },
      "key",
      signal(),
    ),
  ).toThrow(PracticeEngineRequestError);
  await expect(
    api.issue("next-move", "key\nforged", signal()),
  ).rejects.toMatchObject({ reason: "invalid_request" });
  expect(fetcher).not.toHaveBeenCalled();
});
it("rejects a huge caller body before fetch", async () => {
  const fetcher = vi.fn();
  const api = createPracticeEngineApi(fetcher);
  await expect(
    api.respond(
      attemptId,
      {
        item_id: "choice-01",
        selections: Array(40000).fill(0),
        expected_revision: 1,
      },
      "key",
      signal(),
    ),
  ).rejects.toMatchObject({ reason: "invalid_request" });
  expect(fetcher).not.toHaveBeenCalled();
});
it("refuses HTTP errors and native diagnostic text without copying private details", async () => {
  const marker = "SYNTHETIC_PRIVATE_DIAGNOSTIC";
  await expect(
    createPracticeEngineApi(async () => {
      throw new Error(marker);
    }).progress(signal()),
  ).rejects.toMatchObject({ reason: "network" });
  try {
    await createPracticeEngineApi(
      async () => new Response(marker, { status: 403 }),
    ).progress(signal());
  } catch (error) {
    expect(String(error)).not.toContain(marker);
    expect(error).toMatchObject({ status: 403 });
  }
});
it.each([
  new Response("{}", { headers: { "content-type": "text/html" } }),
  new Response("broken", { headers: { "content-type": "application/json" } }),
])("rejects non-JSON or malformed JSON replies", async (response) => {
  await expect(
    createPracticeEngineApi(async () => response).progress(signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it("bounds streamed response size", async () => {
  const response = new Response("x".repeat(2 * 1024 * 1024 + 1), {
    headers: { "content-type": "application/json" },
  });
  await expect(
    createPracticeEngineApi(async () => response).progress(signal()),
  ).rejects.toMatchObject({ reason: "invalid_response" });
});
it("aborts before fetch for an already-cancelled caller", async () => {
  const fetcher = vi.fn();
  const controller = new AbortController();
  controller.abort();
  await expect(
    createPracticeEngineApi(fetcher).progress(controller.signal),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(fetcher).not.toHaveBeenCalled();
});
it("bounds a fetcher that ignores timeout and discards late bodies", async () => {
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
  const pending = createPracticeEngineApi(fetcher).progress(signal());
  const assertion = expect(pending).rejects.toMatchObject({
    reason: "timeout",
  });
  await vi.advanceTimersByTimeAsync(12000);
  await assertion;
  const cancelled = vi.fn();
  complete(
    new Response(new ReadableStream({ cancel: cancelled }), {
      headers: { "content-type": "application/json" },
    }),
  );
  await vi.runAllTimersAsync();
  expect(cancelled).toHaveBeenCalled();
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
});
it("cancels a stalled response body and cleans up caller listeners", async () => {
  const cancelled = vi.fn();
  const response = new Response(
    new ReadableStream({ pull() {}, cancel: cancelled }),
    { headers: { "content-type": "application/json" } },
  );
  const controller = new AbortController();
  const cleanup = vi.spyOn(controller.signal, "removeEventListener");
  const pending = createPracticeEngineApi(async () => response).progress(
    controller.signal,
  );
  const assertion = expect(pending).rejects.toMatchObject({
    name: "AbortError",
  });
  await Promise.resolve();
  controller.abort();
  await assertion;
  expect(cancelled).toHaveBeenCalled();
  expect(cleanup).toHaveBeenCalledWith("abort", expect.any(Function));
});
