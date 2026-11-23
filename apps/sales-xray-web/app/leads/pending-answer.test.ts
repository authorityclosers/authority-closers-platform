import { afterEach, expect, it } from "vitest";

import { FRESH_MS } from "./after-call";
import type { NativeCall } from "./native-phone";
import {
  answerAccount,
  answeredCallFor,
  callToAnswer,
  dialledLead,
  forgetDial,
  releaseCallToAnswer,
  rememberCallToAnswer,
  rememberDial,
} from "./pending-answer";

// "After the call … it should lock until answered" (owner, 19 Nov 2026).
const ME = "tenant-1:person-1";
const NOW = Date.parse("2026-11-19T12:00:00Z");

const call = (overrides: Partial<NativeCall> = {}): NativeCall => ({
  leadId: "lead-1",
  number: "+919876543210",
  startedMs: NOW - 120_000,
  endedMs: NOW - 30_000,
  durationSeconds: null,
  connected: null,
  result: "answered",
  recording: null,
  final: true,
  ...overrides,
});

afterEach(() => localStorage.clear());

it("holds the seller to a call the phone placed until its answer is saved", () => {
  expect(rememberCallToAnswer(ME, call(), NOW)).toBe(true);
  expect(callToAnswer(ME, NOW)).toEqual({
    leadId: "lead-1",
    startedMs: NOW - 120_000,
  });
  // Another account on this phone isn't held by it.
  expect(callToAnswer("tenant-1:person-2", NOW)).toBeNull();
  answeredCallFor(ME, "lead-1");
  expect(callToAnswer(ME, NOW)).toBeNull();
  // The phone reports the same call again once its recording is final: an
  // answered call never asks again.
  expect(rememberCallToAnswer(ME, call(), NOW)).toBe(false);
  expect(callToAnswer(ME, NOW)).toBeNull();
});

it("holds nothing for a call that never connected, never ended or is old", () => {
  expect(rememberCallToAnswer(ME, call({ connected: false }), NOW)).toBe(false);
  expect(rememberCallToAnswer(ME, call({ endedMs: null }), NOW)).toBe(false);
  expect(
    rememberCallToAnswer(
      ME,
      call({ startedMs: NOW - FRESH_MS - 90_000, endedMs: NOW - FRESH_MS - 1 }),
      NOW,
    ),
  ).toBe(false);
  expect(rememberCallToAnswer(null, call(), NOW)).toBe(false);
  expect(callToAnswer(ME, NOW)).toBeNull();
  // Held, then too old: it no longer holds anyone.
  rememberCallToAnswer(ME, call(), NOW);
  expect(callToAnswer(ME, NOW + FRESH_MS)).toBeNull();
});

it("answering another lead leaves the held call held", () => {
  rememberCallToAnswer(ME, call(), NOW);
  answeredCallFor(ME, "lead-2");
  expect(callToAnswer(ME, NOW)?.leadId).toBe("lead-1");
});

it("keys the hold by workspace and person", () => {
  expect(answerAccount({ personId: "p", tenantId: "t" })).toBe("t:p");
  expect(answerAccount({ personId: "p", tenantId: null })).toBeNull();
  expect(answerAccount(null)).toBeNull();
});

it("remembers the lead being dialled until its call's end is known", () => {
  rememberDial("lead-1", NOW);
  expect(dialledLead(NOW)).toBe("lead-1");
  expect(dialledLead(NOW + FRESH_MS + 1)).toBeNull();
  forgetDial("lead-2");
  expect(dialledLead(NOW)).toBe("lead-1");
  forgetDial("lead-1");
  expect(dialledLead(NOW)).toBeNull();
});

it("lets go of a held call whose lead was given to someone else (Wise Life, 23 Nov 2026)", () => {
  rememberDial("lead-1", NOW);
  rememberCallToAnswer(ME, call(), NOW);
  // Another lead going away changes nothing.
  releaseCallToAnswer(ME, "lead-2");
  expect(callToAnswer(ME, NOW)?.leadId).toBe("lead-1");
  releaseCallToAnswer(ME, "lead-1");
  expect(callToAnswer(ME, NOW)).toBeNull();
  expect(dialledLead(NOW)).toBeNull();
  // The phone's second report of that call (final recording) holds no one again.
  expect(rememberCallToAnswer(ME, call(), NOW)).toBe(false);
  expect(callToAnswer(ME, NOW)).toBeNull();
});
