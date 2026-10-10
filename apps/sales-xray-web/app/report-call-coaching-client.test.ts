import { afterEach, expect, it, vi } from "vitest";
import {
  callCoachingBinding as binding,
  fictionalCallCoaching,
} from "./report-call-coaching.fixture";
import {
  parseCallCoaching,
  readCallCoaching,
} from "./report-call-coaching-client";

afterEach(() => vi.unstubAllGlobals());
it("reads one private own-call result with native evidence and one mission", async () => {
  const payload = fictionalCallCoaching();
  const fetcher = vi.fn(async () => new Response(JSON.stringify(payload)));
  vi.stubGlobal("fetch", fetcher);
  const signal = new AbortController().signal;
  const view = await readCallCoaching(binding, signal);
  expect(view.focus!.label).toBe("Fictional API focus");
  expect(fetcher).toHaveBeenCalledExactlyOnceWith(
    `/v1/me/coaching/calls/${binding.callId}`,
    {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
    },
  );
});
it.each([
  "person_id",
  "tenant_id",
  "session_id",
  "submission_id",
  "recording_id",
  "source_sha256",
  "transcript_revision",
])("rejects a crossed %s", (field) => {
  const payload = {
    ...fictionalCallCoaching(),
    [field]: "00000000-0000-0000-0000-000000000009",
  };
  expect(() => parseCallCoaching(payload, binding)).toThrow("unavailable");
});
it.each([
  "submission_id",
  "recording_id",
  "source_sha256",
  "transcript_revision",
  "segment_id",
  "quote",
])("rejects crossed or fabricated evidence %s", (field) => {
  const payload = fictionalCallCoaching();
  Object.assign(payload.evidence[0], { [field]: "wrong source" });
  expect(() => parseCallCoaching(payload, binding)).toThrow();
});
it("checks the native source window and the optional pinned report revision", () => {
  const payload = fictionalCallCoaching();
  payload.evidence[0].end_ms = binding.transcript!.duration_ms + 1;
  expect(() => parseCallCoaching(payload, binding)).toThrow();
  expect(() =>
    parseCallCoaching(fictionalCallCoaching(), {
      ...binding,
      reportRevision: "c".repeat(64),
    }),
  ).toThrow();
});
it("rejects an unbound old API result when the caller pins its current session", () => {
  const payload = fictionalCallCoaching();
  expect(() =>
    parseCallCoaching({ ...payload, session_id: undefined }, binding),
  ).toThrow();
  expect(() =>
    parseCallCoaching({ ...payload, session_id: null }, binding),
  ).toThrow();
});
it("keeps the lesson and mission on this one source and skill", () => {
  const payload = fictionalCallCoaching();
  payload.mission.origin_submission_id = binding.personId;
  expect(() => parseCallCoaching(payload, binding)).toThrow();
  payload.mission.origin_submission_id = binding.callId;
  payload.mission.skill_id = "qualification";
  expect(() => parseCallCoaching(payload, binding)).toThrow();
  payload.mission.skill_id = payload.focus.skill_id;
  payload.lesson.own_call.recording_id = binding.personId;
  expect(() => parseCallCoaching(payload, binding)).toThrow();
});
it("accepts explicitly general practice without pretending it has a call quote", () => {
  const payload = {
    ...fictionalCallCoaching(),
    basis: "general_practice",
    evidence: [],
    lesson: { ...fictionalCallCoaching().lesson, own_call: null },
  };
  expect(parseCallCoaching(payload, binding).evidence).toEqual([]);
});
it("only accepts unavailable coaching with every private field cleared", () => {
  const payload = {
    ...fictionalCallCoaching(),
    state: "unavailable",
    basis: "unavailable",
    focus: null,
    evidence: [],
    lesson: null,
    practice: null,
    mission: null,
  };
  expect(parseCallCoaching(payload, binding).state).toBe("unavailable");
  expect(() =>
    parseCallCoaching(
      { ...payload, evidence: fictionalCallCoaching().evidence },
      binding,
    ),
  ).toThrow();
});
it("refuses missing required lesson fields and unreviewed media", () => {
  const payload = fictionalCallCoaching();
  expect(() =>
    parseCallCoaching(
      { ...payload, lesson: { ...payload.lesson, framework: null } },
      binding,
    ),
  ).toThrow();
  expect(() =>
    parseCallCoaching(
      {
        ...payload,
        recommended_media: { url: "https://media.example.invalid" },
      },
      binding,
    ),
  ).toThrow();
});
it("bounds an adapter that ignores cancellation without printing private failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
  const controller = new AbortController();
  const pending = readCallCoaching(binding, controller.signal);
  controller.abort();
  await expect(pending).rejects.toThrow("unavailable");
});
it("never requests a query-supplied origin or an invalid call ID", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await expect(
    readCallCoaching(
      { ...binding, callId: "https://other.example/call" },
      new AbortController().signal,
    ),
  ).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});
it("degrades a missing API or redirected read with a bounded message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("Private error details", { status: 404 })),
  );
  await expect(
    readCallCoaching(binding, new AbortController().signal),
  ).rejects.toThrow("unavailable");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, redirected: true })),
  );
  await expect(
    readCallCoaching(binding, new AbortController().signal),
  ).rejects.toThrow("unavailable");
});
