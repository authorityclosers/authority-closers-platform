import { expect, it } from "vitest";

import { FRESH_MS, afterCall } from "./after-call";
import type { LeadEvent } from "./leads-client";
import type { NativeCall } from "./native-phone";

// "How did it go?" only after a real call (owner, 23 Oct 2026); a light
// "Log this" chip after anything else.
const LEAD = "11111111-1111-4111-8111-111111111111";
const NOW = Date.parse("2026-10-23T06:00:00Z");
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

const event = (overrides: Partial<LeadEvent>): LeadEvent => ({
  kind: "call",
  at: ago(5),
  actor_name: null,
  stage: null,
  stage_label: null,
  reason: null,
  reason_label: null,
  connected: null,
  note: null,
  next_action_at: null,
  owner_name: null,
  previous_owner_name: null,
  allocation_reason: null,
  source_label: null,
  submission_id: null,
  simulated: null,
  duration_seconds: null,
  ...overrides,
});

const phoneCall = (overrides: Partial<NativeCall>): NativeCall => ({
  leadId: LEAD,
  number: "+919876543210",
  startedMs: NOW - 120_000,
  endedMs: NOW - 30_000,
  durationSeconds: 75,
  connected: true,
  result: "answered",
  recording: null,
  final: true,
  ...overrides,
});

const ask = (input: {
  phoneCall?: NativeCall | null;
  back?: boolean;
  events?: LeadEvent[];
}) =>
  afterCall({
    leadId: LEAD,
    name: "Asha",
    phoneCall: input.phoneCall ?? null,
    back: input.back ?? false,
    events: input.events ?? [],
    now: NOW,
  });

const dialled = (overrides: Partial<LeadEvent> = {}) =>
  event({
    via: "phone",
    direction: "outgoing",
    duration_seconds: 82,
    connected: true,
    ...overrides,
  });

it("asks after the phone app's own call when it connected", () => {
  const call = phoneCall({});
  expect(ask({ phoneCall: call })).toEqual({ ask: true, heard: call });
  // No word on connecting, but talk time: it connected.
  expect(
    ask({ phoneCall: phoneCall({ connected: null, durationSeconds: 40 }) }).ask,
  ).toBe(true);
});

it("offers the chip after a missed or unanswered call, saying what the phone saw", () => {
  const missed = phoneCall({
    connected: false,
    result: "no_answer",
    durationSeconds: 0,
  });
  expect(ask({ phoneCall: missed })).toEqual({
    ask: false,
    heard: missed,
    hint: "Your phone says nobody answered.",
  });
  expect(
    ask({ phoneCall: phoneCall({ connected: null, durationSeconds: 0 }) }),
  ).toMatchObject({ ask: false, hint: null });
});

it("asks after a call the phone logged from its own dialler, with talk time", () => {
  const result = ask({ events: [dialled()] });
  expect(result.ask).toBe(true);
  expect(result.heard).toMatchObject({
    leadId: LEAD,
    connected: true,
    durationSeconds: 82,
    startedMs: Date.parse(ago(5)),
  });
  // An incoming call they picked up counts too.
  expect(ask({ events: [dialled({ direction: "incoming" })] }).ask).toBe(true);
});

it("doesn't ask about a dialler call already answered, too old, or without talk", () => {
  expect(
    ask({ events: [dialled(), event({ kind: "result", at: ago(2) })] }).ask,
  ).toBe(false);
  expect(
    ask({
      events: [dialled({ at: new Date(NOW - FRESH_MS - 1).toISOString() })],
    }).ask,
  ).toBe(false);
  expect(ask({ events: [dialled({ duration_seconds: 0 })] }).ask).toBe(false);
  // Only the newest call counts: a missed one after a talk asks nothing.
  expect(
    ask({
      events: [
        dialled({ at: ago(30) }),
        dialled({ at: ago(3), direction: "missed", duration_seconds: 0 }),
      ],
    }),
  ).toEqual({
    ask: false,
    heard: null,
    hint: "Asha called and nobody picked up.",
  });
  // The app's own logged call (not the phone's dialler) never asks by itself.
  expect(ask({ events: [dialled({ via: null })] }).ask).toBe(false);
});

it("offers the chip after the browser's dialler, a WhatsApp or nothing at all", () => {
  expect(ask({ back: true })).toEqual({
    ask: false,
    heard: null,
    hint: "Back from calling Asha.",
  });
  expect(
    ask({ events: [event({ kind: "message", channel: "whatsapp" })] }),
  ).toEqual({
    ask: false,
    heard: null,
    hint: "You messaged Asha on WhatsApp.",
  });
  expect(
    ask({
      events: [
        event({ kind: "message", channel: "whatsapp", at: ago(10) }),
        event({ kind: "result", at: ago(4) }),
      ],
    }),
  ).toEqual({ ask: false, heard: null, hint: null });
  expect(ask({})).toEqual({ ask: false, heard: null, hint: null });
});
