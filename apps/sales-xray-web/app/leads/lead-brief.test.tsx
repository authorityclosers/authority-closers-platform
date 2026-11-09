import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadBrief, lastTalkOf, sellerWords, talkNote } from "./lead-brief";
import type { LeadDetail, LeadEvent } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// "Before you call" on the lead page (P5, spec §3): problem, goal, last talk,
// next step, "Not known yet" for what nobody knows, See more for the rest.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  // The newest Report is read from the API; nothing answers here.
  vi.stubGlobal("fetch", () => new Promise(() => undefined));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const event = (over: Partial<LeadEvent>): LeadEvent =>
  ({
    kind: "note",
    at: "2026-11-03T09:30:00Z",
    actor_name: "Asha Fictional",
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
    ...over,
  }) as LeadEvent;

const detailWith = (over: Partial<LeadDetail>, lead = {}): LeadDetail =>
  ({
    lead: {
      lead_id: "11111111-1111-4111-8111-111111111111",
      revision: 3,
      name: "Ravi Kulkarni",
      interest: null,
      stage: "follow_up",
      stage_label: "Follow-up",
      owner_person_id: null,
      calls: 1,
      attempts: 1,
      ...lead,
    },
    phone: "+919876543210",
    email: null,
    owner_reason: null,
    next_action_note: null,
    fields: [],
    source_fields: [],
    events: [],
    can_edit: true,
    can_assign: false,
    reps: [],
    call_mode: "phone",
    ...over,
  }) as LeadDetail;

async function show(detail: LeadDetail) {
  await act(async () => root.render(<LeadBrief detail={detail} />));
}

const rows = () =>
  [...host.querySelectorAll<HTMLElement>("section > dl > div")]
    .filter((row) => row.querySelector("dt"))
    .map((row) => ({
      label: row.querySelector("dt")?.firstChild?.textContent ?? "",
      note: row.querySelector("dt span")?.textContent ?? null,
      value: row.querySelector("dd")?.textContent ?? "",
      unknown: row.querySelector("dd")?.hasAttribute("data-unknown") ?? false,
    }));

it("says why a new lead enquired, and that nobody has talked to them yet", async () => {
  await show(
    detailWith(
      { events: [event({ kind: "captured" })] },
      { calls: 0, attempts: 0, interest: "Free masterclass" },
    ),
  );
  expect(host.querySelector("h3")?.textContent).toBe("Before you call");
  expect(rows().map(({ label, value }) => [label, value])).toEqual([
    ["Why they enquired", "Free masterclass"],
    ["Last talk", "No previous conversation"],
  ]);
});

it("reads Not known yet where nothing is known, never a guess", async () => {
  await show(
    detailWith(
      {
        next_action_note: "Send the brochure in Marathi",
        events: [
          event({
            kind: "result",
            at: "2026-11-03T10:10:00Z",
            connected: true,
            note: "Wants a demo for his team of six.",
          }),
          event({
            kind: "call",
            at: "2026-11-03T10:00:00Z",
            connected: true,
            via: "phone",
            seconds_from: "call_log",
            duration_seconds: 720,
          }),
        ],
      },
      { interest: "Masterclass" },
    ),
  );
  const shown = rows();
  expect(shown.map((row) => row.label)).toEqual([
    "Problem",
    "Goal",
    "Last talk",
    "Next step",
  ]);
  expect(shown[0]).toMatchObject({ value: "Not known yet", unknown: true });
  expect(shown[1]).toMatchObject({ value: "Not known yet", unknown: true });
  // The seller's own words after that call, its day and measured length.
  expect(shown[2]).toMatchObject({
    note: "3 Nov · 12 min",
    value: "Wants a demo for his team of six.",
    unknown: false,
  });
  expect(shown[3]).toMatchObject({ value: "Send the brochure in Marathi" });
});

it("opens the other five areas in place with See more", async () => {
  await show(
    detailWith({
      events: [event({ kind: "call", connected: true, duration_seconds: 60 })],
    }),
  );
  const more = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "See more",
  );
  expect(more?.getAttribute("aria-expanded")).toBe("false");
  expect(host.querySelectorAll("h4")).toHaveLength(0);
  await act(async () => more?.click());
  expect(more?.textContent).toBe("See less");
  expect(more?.getAttribute("aria-expanded")).toBe("true");
  const areas = [...host.querySelectorAll("h4")].map((h) => h.textContent);
  expect(areas).toHaveLength(5);
  expect(areas[0]).toBe("What They Want — & Why");
  // What nobody knows yet is named once per area, never filled in.
  expect(host.textContent).toContain("Not known yet: Industry");
});

it("takes the newest real talk, not a dial nobody answered", () => {
  const dial = event({ kind: "call", at: "2026-11-05T09:00:00Z" });
  const talk = event({
    kind: "call",
    at: "2026-11-04T09:00:00Z",
    connected: true,
  });
  expect(lastTalkOf([dial, talk])).toBe(talk);
  expect(lastTalkOf([dial])).toBeNull();
  // A dial the phone measured talk on counts (its call log said so).
  const logged = event({ kind: "call", via: "phone", duration_seconds: 30 });
  expect(lastTalkOf([logged])).toBe(logged);
});

it("shows a call's length only where it was measured", () => {
  const at = "2026-11-03T10:00:00Z";
  expect(talkNote(event({ kind: "call", at, duration_seconds: 300 }))).toBe(
    "3 Nov",
  );
  expect(
    talkNote(
      event({
        kind: "call",
        at,
        duration_seconds: 45,
        seconds_from: "call_log",
      }),
    ),
  ).toBe("3 Nov · 45 s");
  expect(
    talkNote(event({ kind: "call", at, duration_seconds: 0, via: "phone" })),
  ).toBe("3 Nov");
});

it("reads the answer saved after that talk, not an older one", () => {
  const older = event({
    kind: "result",
    at: "2026-11-01T10:00:00Z",
    connected: true,
    note: "Old words",
  });
  const talk = event({ kind: "call", at: "2026-11-03T10:00:00Z" });
  const after = event({
    kind: "result",
    at: "2026-11-03T10:05:00Z",
    connected: true,
    note: "New words",
  });
  const undone = event({
    kind: "result",
    at: "2026-11-03T10:06:00Z",
    connected: true,
    note: "Undone words",
    answer_undone: true,
  });
  expect(sellerWords([undone, after, talk, older], talk)).toBe("New words");
  expect(sellerWords([talk, older], talk)).toBeNull();
});
