import { afterEach, expect, it, vi } from "vitest";
import { fictionalCoaching } from "./coaching.fixture";
import { recurringIssue, resetRecurringIssue } from "./recurring-issue";

const A = "00000000-0000-0000-0000-0000000000a1";
const B = "00000000-0000-0000-0000-0000000000b2";
const C = "00000000-0000-0000-0000-0000000000c3";
const me = {
  personId: fictionalCoaching.person_id,
  tenantId: fictionalCoaching.tenant_id,
  sessionId: "session-a",
};
const row = (id: string, recurring?: boolean | null) => ({
  submission_id: id,
  call_label: "Fictional call",
  created_at: "2026-10-09T10:00:00Z",
  state: "ready",
  focus_label: "Explore the consequence",
  ...(recurring === undefined ? {} : { recurring }),
});
const coaching = (body = {}) =>
  new Response(
    JSON.stringify({
      ...fictionalCoaching,
      calls: [row(A, true), row(B, false), row(C)],
      ...body,
    }),
    { headers: { "content-type": "application/json" } },
  );
afterEach(() => {
  resetRecurringIssue();
  vi.unstubAllGlobals();
});

it("says whether a call's issue recurs from one shared My coaching read", async () => {
  const fetch = vi.fn(async () => coaching());
  vi.stubGlobal("fetch", fetch);
  expect(await recurringIssue(A, me)).toEqual({
    recurring: true,
    href: "/coaching",
  });
  expect(await recurringIssue(B, me)).toEqual({
    recurring: false,
    href: "/coaching",
  });
  // Unknown (older API, no assessed skill) and unlisted calls show nothing.
  expect(await recurringIssue(C, me)).toBeNull();
  expect(await recurringIssue(fictionalCoaching.person_id, me)).toBeNull();
  expect(fetch).toHaveBeenCalledOnce();
});

it("never answers for another account and stops quietly on failure or abort", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      coaching({ person_id: "00000000-0000-0000-0000-0000000000ff" }),
    ),
  );
  expect(await recurringIssue(A, me)).toBeNull();
  resetRecurringIssue();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("no", { status: 500 })),
  );
  expect(await recurringIssue(A, me)).toBeNull();
  resetRecurringIssue();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => coaching()),
  );
  const controller = new AbortController();
  controller.abort();
  expect(await recurringIssue(A, me, controller.signal)).toBeNull();
  // Another session is a new read, not the previous account's answer.
  expect(await recurringIssue(A, { ...me, sessionId: "session-b" })).toEqual({
    recurring: true,
    href: "/coaching",
  });
});
