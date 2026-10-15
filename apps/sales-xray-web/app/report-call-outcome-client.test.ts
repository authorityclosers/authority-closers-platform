import { afterEach, expect, it, vi } from "vitest";
import {
  CALL_OUTCOME_SCHEMA,
  parseCallOutcomeRecord,
  readCallOutcome,
  saveCallOutcome,
  type CallOutcomeRecord,
} from "./report-call-outcome-client";
import { parseHumanCallOutcome } from "./report-call-outcome-contract";

const binding = {
  personId: "00000000-0000-4000-8000-000000000001",
  tenantId: "00000000-0000-4000-8000-000000000002",
  sessionId: "00000000-0000-4000-8000-000000000003",
  callId: "00000000-0000-4000-8000-000000000004",
};
const prospectId = "00000000-0000-4000-8000-000000000005";
const membershipId = "00000000-0000-4000-8000-000000000006";
const otherPerson = "00000000-0000-4000-8000-000000000007";
const time = "2026-10-11T10:00:00Z";
const won = parseHumanCallOutcome({
  outcome: "won",
  deal_value: { amount: "125000.0000", currency_code: "INR" },
});
function unrecorded(): CallOutcomeRecord {
  return {
    schema: CALL_OUTCOME_SCHEMA,
    submission_id: binding.callId,
    person_id: binding.personId,
    tenant_id: binding.tenantId,
    session_id: binding.sessionId,
    revision: 0,
    value: null,
    basis: null,
    locked: false,
    set_by_person_id: null,
    set_at: null,
    prospect_binding: {
      prospect_id: prospectId,
      membership_id: membershipId,
      stage_revision: 2,
    },
    can_edit: true,
  };
}
function recorded(): CallOutcomeRecord {
  return {
    ...unrecorded(),
    revision: 1,
    value: structuredClone(won),
    basis: "person",
    locked: true,
    set_by_person_id: binding.personId,
    set_at: time,
    prospect_binding: {
      prospect_id: prospectId,
      membership_id: membershipId,
      stage_revision: 3,
    },
  };
}
function response(payload: unknown = recorded(), status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}
function respond(payload: unknown = recorded(), status = 200) {
  const fetcher = vi
    .fn()
    .mockImplementation(async () => response(payload, status));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
const save = (before = unrecorded(), requested: unknown = won, options = {}) =>
  saveCallOutcome(binding, before, requested, options);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("keeps an unrecorded read distinct from an unavailable route and No decision", async () => {
  const raw = unrecorded();
  delete (raw as Partial<CallOutcomeRecord>).can_edit;
  respond(raw);
  const result = await readCallOutcome(binding);
  expect(result).toMatchObject({
    status: "ready",
    data: { revision: 0, value: null, can_edit: false },
  });
  // Only the server's not_call_owner code is quiet; anything else is unavailable.
  respond({ detail: "not_call_owner" }, 403);
  expect(await readCallOutcome(binding)).toEqual({ status: "not_owner" });
  respond({ detail: "A current AC workspace is required." }, 403);
  expect((await readCallOutcome(binding)).status).toBe("unavailable");
  respond(null, 404);
  expect((await readCallOutcome(binding)).status).toBe("unavailable");
  respond(null, 503);
  expect(await readCallOutcome(binding)).toEqual({
    status: "unavailable",
    message: "Call outcome is unavailable. Try again.",
  });
  expect(
    parseCallOutcomeRecord(
      { ...recorded(), value: { outcome: "no_decision" } },
      binding,
    ).value?.outcome,
  ).toBe("no_decision");
});

it.each(["person_id", "tenant_id", "session_id", "submission_id"])(
  "withholds a response belonging to another %s",
  async (key) => {
    respond({ ...recorded(), [key]: otherPerson });
    expect((await readCallOutcome(binding)).status).toBe("unavailable");
    expect((await save()).status).toBe("unconfirmed");
  },
);

it.each([
  { value: undefined },
  { revision: -1 },
  { revision: 1.5 },
  { revision: Number.MAX_SAFE_INTEGER + 1 },
  { basis: "heard_in_call" },
  { locked: false },
  { set_by_person_id: null },
  { set_at: "2026-10-11T10:00:00" },
  { set_at: "2026-02-30T10:00:00Z" },
  { set_at: "2026-10-11T24:00:00Z" },
  { prospect_binding: undefined },
  {
    prospect_binding: {
      prospect_id: prospectId,
      membership_id: "../other",
      stage_revision: 2,
    },
  },
  {
    prospect_binding: {
      prospect_id: prospectId,
      membership_id: membershipId,
      stage_revision: -1,
    },
  },
  { can_edit: "true" },
])(
  "never admits AI, missing provenance or malformed revision/authority %#",
  async (patch) => {
    respond({ ...recorded(), ...patch });
    const result = await readCallOutcome(binding);
    expect(result.status).toBe("unavailable");
    expect(result).not.toHaveProperty("data");
  },
);

it.each([
  { revision: 1 },
  { basis: "person" },
  { locked: true },
  { set_by_person_id: otherPerson },
  { set_at: time },
])("refuses provenance attached to an absent outcome %#", (patch) => {
  expect(() =>
    parseCallOutcomeRecord({ ...unrecorded(), ...patch }, binding),
  ).toThrow("call_outcome_unavailable");
});

it("sends one explicit command with outcome, membership and human-stage revision fences", async () => {
  const fetcher = respond();
  const result = await save();
  expect(result).toEqual({ status: "saved", binding, data: recorded() });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith(
    `/v1/conversation/prospects/calls/${binding.callId}/outcome`,
    expect.objectContaining({
      method: "PUT",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      body: JSON.stringify({
        value: won,
        expected_revision: 0,
        expected_membership_id: membershipId,
        expected_prospect_stage_revision: 2,
      }),
    }),
  );
});

it("saves an unlinked call without inventing or assigning a prospect", async () => {
  const fetcher = respond({ ...recorded(), prospect_binding: null });
  expect((await save({ ...unrecorded(), prospect_binding: null })).status).toBe(
    "saved",
  );
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({
    expected_membership_id: null,
    expected_prospect_stage_revision: null,
  });
});

it("accepts an idempotent existing human fact while retaining the original actor/time", async () => {
  const before = { ...recorded(), set_by_person_id: otherPerson };
  respond(before);
  expect((await save(before)).status).toBe("saved");
});

it.each([
  { outcome: "lost", lost_reason: "दूसरा विकल्प चुना।" },
  { outcome: "follow_up", follow_up_on: "2026-10-12" },
  { outcome: "no_decision" },
])("accepts only the literal requested human fact %#", async (requested) => {
  const value = parseHumanCallOutcome(requested);
  respond({ ...recorded(), value });
  const result = await save(unrecorded(), requested);
  expect(result).toMatchObject({ status: "saved", data: { value } });
});

it("does not accept duplicate revisions for an idempotent fact or a backwards audit clock", async () => {
  respond({ ...recorded(), revision: 2 });
  expect((await save(recorded())).status).toBe("unconfirmed");
  respond({
    ...recorded(),
    revision: 2,
    value: parseHumanCallOutcome({ outcome: "no_decision" }),
    set_at: "2026-10-11T09:00:00Z",
  });
  expect((await save(recorded(), { outcome: "no_decision" })).status).toBe(
    "unconfirmed",
  );
});

it.each([
  "membership",
  "prospect",
  "linked",
  "unlinked",
  "stage",
  "old-stage",
  "actor",
  "revision",
  "old-revision",
  "value",
  "idempotent-actor",
  "idempotent-time",
  "idempotent-stage",
])("does not acknowledge a changed or stale %s", async (change) => {
  const raw = recorded();
  let before = unrecorded();
  if (change === "membership")
    raw.prospect_binding!.membership_id = otherPerson;
  if (change === "prospect") raw.prospect_binding!.prospect_id = otherPerson;
  if (change === "linked") before.prospect_binding = null;
  if (change === "unlinked") raw.prospect_binding = null;
  if (change === "stage") raw.prospect_binding!.stage_revision = 4;
  if (change === "old-stage") raw.prospect_binding!.stage_revision = 1;
  if (change === "actor") raw.set_by_person_id = otherPerson;
  if (change === "revision") raw.revision = 2;
  if (change === "old-revision") raw.revision = 0;
  if (change === "value") raw.value!.deal_value!.amount = "125000";
  if (change.startsWith("idempotent")) {
    before = recorded();
    if (change === "idempotent-actor") raw.set_by_person_id = otherPerson;
    if (change === "idempotent-time") raw.set_at = "2026-10-11T11:00:00Z";
    if (change === "idempotent-stage") raw.prospect_binding!.stage_revision = 4;
  }
  respond(raw);
  const result = await save(before);
  expect(result.status).toBe("unconfirmed");
  expect(result).not.toHaveProperty("data");
});

it.each([202, 302, 401, 403, 404, 409, 500])(
  "never retries HTTP %s or accepts its body as a save",
  async (status) => {
    const fetcher = respond(recorded(), status);
    expect((await save()).status).toBe(
      status === 409 ? "conflict" : "unconfirmed",
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

it("rejects invalid values and unavailable write authority before transport", async () => {
  const fetcher = respond();
  expect((await save(unrecorded(), { outcome: "lost" })).status).toBe(
    "invalid",
  );
  expect((await save({ ...unrecorded(), person_id: otherPerson })).status).toBe(
    "invalid",
  );
  expect((await save({ ...unrecorded(), can_edit: false })).status).toBe(
    "forbidden",
  );
  expect(
    (await save({ ...recorded(), revision: Number.MAX_SAFE_INTEGER })).status,
  ).toBe("invalid");
  expect(
    (await readCallOutcome({ ...binding, callId: "../other" })).status,
  ).toBe("unavailable");
  expect(fetcher).not.toHaveBeenCalled();
});

it.each(["json", "length", "stream", "utf8", "mime", "redirect", "network"])(
  "bounds and hides %s failures without repeating a write",
  async (kind) => {
    const fetcher = vi.fn(() => {
      if (kind === "network")
        throw new Error("private provider/account detail");
      const raw =
        kind === "utf8"
          ? new Uint8Array([0xff])
          : kind === "json"
            ? "private invalid JSON"
            : kind === "mime" || kind === "redirect"
              ? JSON.stringify(recorded())
              : "x".repeat(16385);
      const reply = new Response(raw, {
        headers: {
          "content-type": kind === "mime" ? "text/html" : "application/json",
          ...(kind === "length" ? { "content-length": "16385" } : {}),
        },
      });
      if (kind === "redirect")
        Object.defineProperty(reply, "redirected", { value: true });
      return Promise.resolve(reply);
    });
    vi.stubGlobal("fetch", fetcher);
    expect(await save()).toEqual({
      status: "unconfirmed",
      message: "This save could not be confirmed. Reload before saving again.",
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

it.each(["transport", "body"])(
  "times out a stalled %s, aborts and ignores a later acknowledgement",
  async (stage) => {
    vi.useFakeTimers();
    let signal!: AbortSignal, finish!: (response: Response) => void;
    const fetcher = vi.fn((_, options) => {
      signal = options.signal;
      return stage === "transport"
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(
            new Response(new ReadableStream({ start() {} }), {
              headers: { "content-type": "application/json" },
            }),
          );
    });
    vi.stubGlobal("fetch", fetcher);
    const pending = save();
    await vi.advanceTimersByTimeAsync(2500);
    const result = await pending;
    expect(result.status).toBe("unconfirmed");
    expect(signal.aborted).toBe(true);
    if (stage === "transport") finish(response());
    await vi.runAllTimersAsync();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result).not.toHaveProperty("data");
    expect(vi.getTimerCount()).toBe(0);
  },
);

it("never starts cancelled or invalid-deadline reads/writes, including cancellation before dispatch", async () => {
  const fetcher = respond();
  const cancelled = new AbortController();
  cancelled.abort();
  expect(
    (await save(unrecorded(), won, { signal: cancelled.signal })).status,
  ).toBe("unconfirmed");
  expect(
    (await readCallOutcome(binding, { signal: cancelled.signal })).status,
  ).toBe("unavailable");
  for (const deadlineMs of [0, Infinity, 15001]) {
    expect((await save(unrecorded(), won, { deadlineMs })).status).toBe(
      "unconfirmed",
    );
    expect((await readCallOutcome(binding, { deadlineMs })).status).toBe(
      "unavailable",
    );
  }
  const controller = new AbortController();
  const pending = save(unrecorded(), won, { signal: controller.signal });
  controller.abort();
  expect((await pending).status).toBe("unconfirmed");
  expect(fetcher).not.toHaveBeenCalled();
});

it.each(["read", "save"])(
  "discards a late %s reply after account/session cancellation",
  async (kind) => {
    const controller = new AbortController();
    let finish!: (response: Response) => void;
    const fetcher = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    const options = { signal: controller.signal };
    const pending =
      kind === "read"
        ? readCallOutcome(binding, options)
        : save(unrecorded(), won, options);
    await Promise.resolve();
    controller.abort();
    const result = await pending;
    expect(result.status).toBe(kind === "read" ? "unavailable" : "unconfirmed");
    finish(response());
    await Promise.resolve();
    expect(result).not.toHaveProperty("data");
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

it("reads a detached account/call once with no effect-driven or write operation", async () => {
  const fetcher = respond();
  const scope = { ...binding };
  const pending = readCallOutcome(scope);
  scope.sessionId = otherPerson;
  expect(await pending).toEqual({ status: "ready", binding, data: recorded() });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith(
    `/v1/conversation/prospects/calls/${binding.callId}/outcome`,
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
    }),
  );
});

it("detaches account, expected revisions and entered value before transport starts", async () => {
  const fetcher = respond();
  const scope = { ...binding },
    before = unrecorded(),
    requested = structuredClone(won);
  const pending = saveCallOutcome(scope, before, requested);
  scope.sessionId = otherPerson;
  before.prospect_binding!.membership_id = otherPerson;
  before.prospect_binding!.stage_revision = 8;
  requested.deal_value!.amount = "1";
  expect((await pending).status).toBe("saved");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({
    value: won,
    expected_membership_id: membershipId,
    expected_prospect_stage_revision: 2,
  });
});

it("returns detached human values and prospect revision provenance", () => {
  const raw = recorded();
  const result = parseCallOutcomeRecord(raw, binding);
  raw.value!.deal_value!.amount = "1";
  raw.prospect_binding!.stage_revision = 8;
  expect(result.value).toEqual(won);
  expect(result.prospect_binding?.stage_revision).toBe(3);
});
