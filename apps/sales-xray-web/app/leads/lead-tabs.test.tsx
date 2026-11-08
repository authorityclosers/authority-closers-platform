import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadCard, LogThis } from "./lead-sheet";
import type { LeadDetail, LeadEvent } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

// The lead page (P5, 8 Nov 2026; first the v0.99 pass, owner reports #31
// and #34): Log a call, the call history and the latest note, no tabs.
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

const historyCard = () =>
  [...host.querySelectorAll<HTMLElement>("section[aria-labelledby]")].find(
    (section) => section.querySelector("h3")?.textContent === "Call history",
  )!;
const noteCard = () =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
    button.textContent?.startsWith("Latest note"),
  );

it("puts the call history and the latest note on one page, no tabs (lead page P5)", async () => {
  await show();
  expect(host.querySelector('[role="tab"], [role="tablist"]')).toBeNull();
  const card = historyCard();
  // The honest count beside the title.
  expect(card.textContent).toContain("Tried 1 time, talked once");
  // Newest first, one row each, the day and time under the title.
  const rows = [
    ...card.querySelectorAll<HTMLElement>('ol[aria-label="History"] > li'),
  ];
  expect(rows.map((row) => row.dataset.kind)).toEqual(["note", "result"]);
  for (const row of rows)
    expect(row.querySelector("time")?.textContent).toMatch(
      /\d{1,2}:\d{2}\s?(am|pm)$/i,
    );
  // The newest note as written, its author under it.
  expect(noteCard()?.textContent).toContain("Wants the brochure in Marathi.");
  expect(noteCard()?.textContent).toContain("Asha Fictional");
});

it("pins the follow-up still to come first, with Upcoming", async () => {
  const later = {
    ...detail,
    next_action_note: "Send the fee details",
    lead: { ...detail.lead, next_action_at: "2099-01-05T05:30:00Z" },
  };
  await act(async () =>
    root.render(
      <LeadCard
        detail={later}
        me={null}
        onChanged={() => undefined}
        outcome={null}
      />,
    ),
  );
  const first = historyCard().querySelector("ol > li");
  expect(first?.getAttribute("data-kind")).toBe("upcoming");
  expect(first?.textContent).toContain("Upcoming");
  expect(first?.textContent).toContain("Send the fee details");
  // A follow-up already past is no "Upcoming" (the header says it is late).
  const past = {
    ...detail,
    lead: { ...detail.lead, next_action_at: "2026-10-20T05:30:00Z" },
  };
  await act(async () =>
    root.render(
      <LeadCard
        detail={past}
        me={null}
        onChanged={() => undefined}
        outcome={null}
      />,
    ),
  );
  expect(historyCard().querySelector('li[data-kind="upcoming"]')).toBeNull();
});

it("opens Notes in a sheet from Note, the field ready, and from the latest note", async () => {
  await show();
  const notes = () =>
    [...document.querySelectorAll("dialog")].find((dialog) =>
      dialog.textContent?.includes("Wants the brochure in Marathi."),
    );
  expect(notes()?.open ?? false).toBe(false);
  const note = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Add a note"]',
  )!;
  await act(async () => {
    note.click();
    await new Promise((done) => setTimeout(done, 0));
  });
  expect(notes()?.open).toBe(true);
  expect(document.activeElement?.id).toBe(`lead-note-${detail.lead.lead_id}`);
});

it("opens Notes from the latest note card", async () => {
  await show();
  await act(async () => noteCard()?.click());
  const open = [...document.querySelectorAll("dialog")].find(
    (dialog) => dialog.open,
  );
  expect(open?.textContent).toContain("Wants the brochure in Marathi.");
});

it("keeps Log a call under the brief, the first screen being the lead's (lead page P5)", async () => {
  const opened = vi.fn();
  await show(<LogThis hint={null} onOpen={opened} />);
  const grid = host.querySelector('[data-sx-equal="lead actions"]');
  // Nothing to answer: the row of four ends its block, the brief follows.
  expect(grid?.nextElementSibling).toBeNull();
  const brief = host.querySelector('section[aria-labelledby^="lead-brief-"]');
  expect(brief?.querySelector("h3")?.textContent).toBe("Before you call");
  const line = brief?.nextElementSibling;
  expect(line?.textContent).toBe("Called from another phone?Log a call");
  const button = line?.querySelector("button");
  expect(
    document.getElementById(button?.getAttribute("aria-describedby") ?? "")
      ?.textContent,
  ).toBe("Called from another phone?");
  await act(async () => button?.click());
  expect(opened).toHaveBeenCalledOnce();
});

it("keeps a call's open question right under the row of four", async () => {
  await show(<p>How did the call go?</p>);
  const grid = host.querySelector('[data-sx-equal="lead actions"]');
  expect(grid?.nextElementSibling?.textContent).toBe("How did the call go?");
});

it("says Log this after something happened", async () => {
  await show(<LogThis hint="WhatsApp sent." onOpen={() => undefined} />);
  expect(host.textContent).toContain("WhatsApp sent.Log a call");
});

it("keeps an idle recording card under the call history, and one to act on now on top", async () => {
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
  expect(idle).not.toBeNull();
  const after = (a: Node, b: Node) =>
    Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_PRECEDING);
  expect(after(idle!, historyCard())).toBe(true);
  // Back from a call: the recording step comes before the history.
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
  expect(after(now!, historyCard())).toBe(false);
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
  // The one Call reads "Call <first name>" (lead page P5).
  const call = () =>
    [...host.querySelectorAll("a, button")].find((item) =>
      /^Call \S/.test(item.textContent ?? ""),
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
