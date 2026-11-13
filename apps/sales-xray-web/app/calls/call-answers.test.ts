import { expect, it } from "vitest";

import type { ActivityItem, LeadEvent } from "../leads/leads-client";
import { answersFor, callLine } from "./call-rows";

// Fictional leads and times.
const event = (extra: Partial<LeadEvent>): LeadEvent =>
  ({
    kind: "call",
    at: "2026-11-10T13:23:00Z",
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
    simulated: false,
    duration_seconds: null,
    outcome: "unknown",
    ...extra,
  }) as LeadEvent;
const item = (id: string, lead: string, extra: Partial<LeadEvent>) =>
  ({
    event_id: id,
    lead_id: lead,
    lead_name: "Meera Fictional",
    stage_label: null,
    event: event(extra),
  }) as ActivityItem;

// Redmi QA (10 Nov 2026): a call answered "We talked · Interested" on the lead
// still read "outcome unknown" on Calls.
it("reads a call the phone couldn't tell the end of as its seller answered it", () => {
  const items = [
    item("c1", "lead-1", { at: "2026-11-10T13:23:00Z" }),
    item("r1", "lead-1", {
      kind: "result",
      at: "2026-11-10T13:25:00Z",
      connected: true,
      stage_label: "Interested",
    }),
    item("c2", "lead-1", { at: "2026-11-10T14:00:00Z" }),
    item("c3", "lead-2", { at: "2026-11-10T13:30:00Z" }),
    item("r3", "lead-2", {
      kind: "result",
      at: "2026-11-10T13:31:00Z",
      connected: false,
      reason_label: "Did not pick",
    }),
  ];
  const answers = answersFor(items);
  expect(callLine(items[0].event, "You", answers.get("c1"))).toBe(
    "You called · talked to them: Interested",
  );
  // The lead's next call has no answer yet.
  expect(callLine(items[2].event, "You", answers.get("c2") ?? null)).toBe(
    "You called · outcome unknown",
  );
  expect(callLine(items[3].event, "Asha", answers.get("c3"))).toBe(
    "Asha called · not connected: did not pick",
  );
});

it("lets the phone's evidence win, and an undone answer count nowhere", () => {
  const items = [
    item("c1", "lead-1", { outcome: "connected", duration_seconds: 77 }),
    item("r1", "lead-1", {
      kind: "result",
      at: "2026-11-10T13:25:00Z",
      connected: true,
      stage_label: "Interested",
    }),
    item("c2", "lead-2", {}),
    item("r2", "lead-2", {
      kind: "result",
      at: "2026-11-10T13:25:00Z",
      connected: true,
      stage_label: "Interested",
      answer_undone: true,
    }),
  ];
  const answers = answersFor(items);
  expect(callLine(items[0].event, "You", answers.get("c1"))).toBe(
    "You called · 1:17",
  );
  expect(answers.has("c2")).toBe(false);
});
