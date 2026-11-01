import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadCard, LogThis, latestReportOf } from "./lead-sheet";
import type { LeadDetail, LeadEvent } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

// The lead sheet's v0.99 pass (owner reports #31 and #34, 26 Oct 2026):
// "Log it" under Call, and Notes · Calls · Story under the actions.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal("requestAnimationFrame", (run: FrameRequestCallback) =>
    window.setTimeout(() => run(0), 0),
  );
  // Call facts and the recording terms read the API; nothing answers here.
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
    at: "2026-10-26T09:30:00Z",
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
    ...over,
  }) as LeadEvent;

const detail: LeadDetail = {
  lead: {
    lead_id: "11111111-1111-4111-8111-111111111111",
    revision: 3,
    name: "Ravi Kulkarni",
    company: null,
    city: null,
    language: null,
    interest: null,
    phone_last4: "3210",
    stage: "follow_up",
    stage_label: "Follow-up",
    source: "manual",
    source_label: "Added by hand",
    owner_person_id: null,
    owner_name: null,
    why: "",
    why_kind: "open",
    next_action_at: null,
    created_at: "2026-10-18T04:00:00Z",
    attempts: 1,
    calls: 1,
    last_result: null,
    last_result_label: null,
    test_data: true,
  },
  phone: "+919876543210",
  email: null,
  owner_reason: null,
  next_action_note: null,
  fields: [],
  source_fields: [],
  events: [
    event({ kind: "note", note: "Wants the brochure in Marathi." }),
    event({
      kind: "result",
      at: "2026-10-26T08:00:00Z",
      connected: true,
      stage_label: "Interested",
    }),
  ],
  can_edit: true,
  can_assign: false,
  reps: [],
  call_mode: "phone",
} as LeadDetail;

async function show(outcome: ReactNode = null) {
  await act(async () =>
    root.render(
      <LeadCard
        detail={detail}
        me={null}
        onChanged={() => undefined}
        outcome={outcome}
      />,
    ),
  );
}

const tab = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((item) =>
    item.textContent?.startsWith(name),
  )!;
const panel = (name: string) =>
  document.getElementById(tab(name).getAttribute("aria-controls")!)!;

it("shows Notes first, and each tab its own panel", async () => {
  await show();
  expect(
    [...host.querySelectorAll('[role="tab"]')].map((item) => item.textContent),
  ).toEqual(["Notes1", "Calls1", "Story"]);
  expect(tab("Notes").getAttribute("aria-selected")).toBe("true");
  expect(panel("Notes").hidden).toBe(false);
  expect(panel("Calls").hidden).toBe(true);
  expect(panel("Story").hidden).toBe(true);
  expect(panel("Notes").textContent).toContain(
    "Wants the brochure in Marathi.",
  );

  await act(async () => tab("Calls").click());
  expect(panel("Notes").hidden).toBe(true);
  expect(panel("Calls").hidden).toBe(false);
  const calls = panel("Calls").querySelector('[aria-label="Calls"]');
  expect(calls?.textContent).toContain("Interested");
  expect(calls?.textContent).not.toContain("brochure");

  // Arrow keys move along the tabs, as tabs do.
  await act(async () =>
    tab("Calls").dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
    ),
  );
  expect(tab("Story").getAttribute("aria-selected")).toBe("true");
  expect(document.activeElement).toBe(tab("Story"));
  // The Story: one line each, the time on the right, under its day.
  const story = panel("Story").querySelector('ol[aria-label="History"]');
  expect(story?.hasAttribute("data-compact")).toBe(true);
  const times = [...(story?.querySelectorAll("time") ?? [])].map(
    (time) => time.textContent,
  );
  expect(times).toHaveLength(2);
  for (const time of times) expect(time).toMatch(/^\d{1,2}:\d{2}\s?(am|pm)$/i);
});

it("opens the Notes tab and its field from the Note box", async () => {
  await show();
  await act(async () => tab("Story").click());
  const note = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Add a note"]',
  )!;
  await act(async () => {
    note.click();
    await new Promise((done) => setTimeout(done, 0));
  });
  expect(tab("Notes").getAttribute("aria-selected")).toBe("true");
  expect(document.activeElement?.id).toBe(`lead-note-${detail.lead.lead_id}`);
});

it("puts the call's question line under Call, above the action boxes", async () => {
  const opened = vi.fn();
  await show(<LogThis hint={null} onOpen={opened} />);
  const grid = host.querySelector('[data-sx-equal="lead actions"]');
  const line = grid?.previousElementSibling;
  expect(line?.textContent).toBe("Called from another phone?Log a call");
  const button = line?.querySelector("button");
  expect(
    document.getElementById(button?.getAttribute("aria-describedby") ?? "")
      ?.textContent,
  ).toBe("Called from another phone?");
  await act(async () => button?.click());
  expect(opened).toHaveBeenCalledOnce();
});

it("says Log this after something happened", async () => {
  await show(<LogThis hint="WhatsApp sent." onOpen={() => undefined} />);
  expect(host.textContent).toContain("WhatsApp sent.Log a call");
});

it("keeps an idle recording card in the Calls tab, and one to act on now on top", async () => {
  const me = {
    person_id: "22222222-2222-4222-8222-222222222222",
    name: "Seller",
    role: "member",
    can_manage: false,
  };
  await act(async () =>
    root.render(
      <LeadCard
        detail={detail}
        me={me}
        onChanged={() => undefined}
        outcome={null}
      />,
    ),
  );
  const idle = host.querySelector('[aria-label="Call recording"]');
  expect(idle?.closest('[role="tabpanel"]')).toBe(panel("Calls"));
  // Back from a call: the recording step comes before the tabs.
  await act(async () =>
    root.render(
      <LeadCard
        detail={detail}
        me={me}
        onChanged={() => undefined}
        outcome={null}
        afterCall={{ step: "recording" }}
      />,
    ),
  );
  const now = host.querySelector('[aria-label="Call recording"]');
  expect(now).not.toBeNull();
  expect(now?.closest('[role="tabpanel"]')).toBeNull();
});

// ph2-19 (phone QA, 1 Nov 2026): a note draft survives the app being closed.
it("keeps a note draft on the phone until it is saved", async () => {
  const { NoteBox } = await import("./lead-sheet");
  localStorage.setItem("sx-draft:note:lead-1", "wants EMI options");
  const box = document.createElement("div");
  document.body.append(box);
  const here = createRoot(box);
  await act(async () =>
    here.render(<NoteBox leadId="lead-1" onSaved={() => undefined} />),
  );
  expect(
    box.querySelector<HTMLTextAreaElement>('textarea[aria-label="Add a note"]')
      ?.value,
  ).toBe("wants EMI options");
  await act(async () => here.unmount());
  box.remove();
  localStorage.removeItem("sx-draft:note:lead-1");
});

// ph2-32 (phone QA, 1 Nov 2026): Cancel in Edit sat under the Call bar and dialled.
it("hides Call while the details are being edited", async () => {
  await show();
  const call = () =>
    [...host.querySelectorAll("a, button")].find((item) =>
      /^Call\+91/.test(item.textContent ?? ""),
    );
  const button = (text: string) =>
    [...host.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === text,
    )!;
  expect(call()).toBeTruthy();
  await act(async () => button("Edit").click());
  expect(call()).toBeUndefined();
  await act(async () => button("Cancel").click());
  expect(call()).toBeTruthy();
});

it("opens the newest report from View latest report (item 93)", () => {
  // The story comes newest first (QA robot, 1 Nov 2026: it opened the oldest).
  expect(
    latestReportOf([
      event({ kind: "note", note: "Fictional note." }),
      event({ kind: "call", submission_id: "newest-fictional" }),
      event({ kind: "call", submission_id: null }),
      event({ kind: "call", submission_id: "oldest-fictional" }),
    ]),
  ).toBe("newest-fictional");
  expect(latestReportOf([event({ kind: "note" })])).toBeNull();
});
