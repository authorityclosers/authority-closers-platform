// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadLine, stepLine } from "./desk-view";
import type { LeadRow } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Dipak's Home + Leads handoff (31 Oct 2026, items 74-79), drawn as Leads L1
// (owner, 8 Nov 2026: "Build L1"; docs/design/screens/leads/spec.md §3): in
// the work views a lead is its name; the stage's dot, "Stage · Source"; the
// next step; and Call and WhatsApp.
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const row = {
  lead_id: "11111111-1111-4111-8111-111111111111",
  revision: 1,
  name: "Fictional Neha",
  company: "Fictional Digital",
  city: "Pune",
  language: null,
  interest: "SEO",
  phone_last4: "3210",
  stage: "interested",
  stage_label: "Interested",
  source: "website",
  source_label: "Website",
  owner_person_id: null,
  owner_name: "Fictional Seller",
  why: "Follow-up today",
  why_kind: "due",
  next_action_at: null,
  created_at: "2026-10-30T04:00:00Z",
  attempts: 1,
  calls: 1,
  last_result: null,
  last_result_label: null,
  test_data: true,
  has_email: true,
} as unknown as LeadRow;

const channels = () =>
  [...host.querySelectorAll("button[data-channel]")].map((item) =>
    item.getAttribute("data-channel"),
  );

it("shows the name, stage and source, the next action, Call and WhatsApp", async () => {
  const onTap = vi.fn();
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={() => undefined}
          actions={{ onTap }}
          compact
          stageWord="Open Leads"
        />
      </ul>,
    ),
  );
  expect(host.textContent).toContain("Fictional Neha");
  expect(host.textContent).toContain("Open Leads · Website");
  expect(host.textContent).not.toContain("SEO");
  // WhatsApp beside Call (bug 156); a lead with no number has none.
  expect(channels()).toEqual(["call", "whatsapp"]);
  expect(
    host.querySelectorAll('[aria-label="Open Fictional Neha"]'),
  ).toHaveLength(1);
});

it("leads line 2 with the stage's dot and draws WhatsApp in one colour", async () => {
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={() => undefined}
          actions={{ onTap: () => undefined }}
          compact
          stageWord="Interested"
          stageTone="var(--lx-warning)"
        />
      </ul>,
    ),
  );
  const dot = host.querySelector<HTMLElement>('[class*="stageDot"]')!;
  expect(dot.style.getPropertyValue("--stage")).toBe("var(--lx-warning)");
  expect(dot.getAttribute("aria-hidden")).toBe("true");
  // The mark in the text's colour, not the green brand disc.
  const whatsapp = host.querySelector('button[data-channel="whatsapp"]')!;
  expect(
    whatsapp.querySelector('svg[fill="currentColor"] path'),
  ).not.toBeNull();
  expect(whatsapp.querySelector('[class*="channelMark"]')).toBeNull();
  // A stage the list doesn't know still has a dot, in the line colour.
  await act(async () =>
    root.render(
      <ul>
        <LeadLine row={row} onOpen={() => undefined} compact />
      </ul>,
    ),
  );
  expect(
    host
      .querySelector<HTMLElement>('[class*="stageDot"]')!
      .style.getPropertyValue("--stage"),
  ).toBe("var(--sx-line-strong)");
});

it("says a passed follow-up is late in words: Late · was due …", () => {
  const now = new Date("2026-11-08T06:30:00Z");
  const due = { ...row, why: "Call back", why_kind: "due" } as LeadRow;
  const today = stepLine(
    { ...due, next_action_at: "2026-11-08T03:30:00Z" } as LeadRow,
    now,
  );
  expect(today.late).toBe(true);
  expect(today.text).toMatch(/^was due \d/);
  const before = stepLine(
    { ...due, next_action_at: "2026-11-07T03:30:00Z" } as LeadRow,
    now,
  );
  expect(before).toEqual({
    late: true,
    text: expect.stringMatching(/^was due yesterday /),
  });
  // Before yesterday: the day alone, no time, so it stays on one line.
  const older = stepLine(
    { ...due, next_action_at: "2026-10-31T02:03:00Z" } as LeadRow,
    now,
  );
  expect(older.late).toBe(true);
  expect(older.text).toBe(
    `was due ${new Date("2026-10-31T02:03:00Z").toLocaleDateString(undefined, { day: "numeric", month: "short" })}`,
  );
  expect(older.text).not.toMatch(/\d:\d\d/);
  // Still to come, a missed call and a closed lead are never "Late".
  expect(
    stepLine({ ...due, next_action_at: "2026-11-09T03:30:00Z" } as LeadRow, now)
      .late,
  ).toBe(false);
  expect(
    stepLine(
      {
        ...due,
        next_action_at: "2026-11-07T03:30:00Z",
        missed_at: "2026-11-08T06:00:00Z",
      } as LeadRow,
      now,
    ).late,
  ).toBe(false);
  expect(
    stepLine(
      {
        ...due,
        why_kind: "closed",
        next_action_at: "2026-11-07T03:30:00Z",
      } as LeadRow,
      now,
    ),
  ).toEqual({ late: false, text: "" });
});

it("pulses a lead that just arrived, and its name keeps its own box", async () => {
  await act(async () =>
    root.render(
      <ul>
        <LeadLine row={row} onOpen={() => undefined} compact fresh />
      </ul>,
    ),
  );
  const line = host.querySelector("[data-lead-row]")!;
  expect(line.hasAttribute("data-fresh")).toBe(true);
  // The name in its own span (the test robot, 1 Nov 2026), which wraps (L1).
  expect(line.querySelector('[class*="leadNameText"]')?.textContent).toBe(
    "Fictional Neha",
  );
  await act(async () =>
    root.render(
      <ul>
        <LeadLine row={row} onOpen={() => undefined} compact />
      </ul>,
    ),
  );
  expect(
    host.querySelector("[data-lead-row]")!.hasAttribute("data-fresh"),
  ).toBe(false);
});

it("adds the owner for a team's list, and keeps the full card elsewhere", async () => {
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={() => undefined}
          actions={{ onTap: () => undefined }}
          compact
          showOwner
        />
      </ul>,
    ),
  );
  expect(host.textContent).toContain("Interested · Website · Fictional Seller");
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={() => undefined}
          actions={{ onTap: () => undefined }}
        />
      </ul>,
    ),
  );
  expect(channels()).toEqual(["call", "whatsapp", "email"]);
  expect(host.textContent).toContain("SEO · Fictional Digital · Pune");
});

it("turns the next action red only when truly late, and never on a seller's Cold lead", async () => {
  const tone = () =>
    host.querySelector('[class*="leadWhy"]')!.getAttribute("data-tone");
  const show = (lead: LeadRow, quietLate = false) =>
    act(async () =>
      root.render(
        <ul>
          <LeadLine
            row={lead}
            onOpen={() => undefined}
            actions={{ onTap: () => undefined }}
            compact
            quietLate={quietLate}
          />
        </ul>,
      ),
    );
  const late = {
    ...row,
    why: "Call back",
    why_kind: "due",
    next_action_at: "2026-10-30T04:00:00Z",
  } as LeadRow;
  await show(late);
  expect(tone()).toBe("bad");
  // The word says it too, in 500, before the time it was due.
  const why = host.querySelector('[class*="leadWhy"]')!;
  expect(why.textContent).toMatch(/^Late · was due /);
  expect(why.querySelector('[class*="lateWord"]')?.textContent).toBe("Late");
  await show(late, true);
  expect(tone()).toBeNull();
  expect(host.querySelector('[class*="leadWhy"]')!.textContent).toMatch(
    /^Late · was due /,
  );
  await show({ ...late, next_action_at: "2099-01-01T04:00:00Z" } as LeadRow);
  expect(tone()).toBeNull();
  expect(host.textContent).not.toContain("Late");
});

it("keeps a third line only for a row someone must act on", async () => {
  const show = (lead: LeadRow) =>
    act(async () =>
      root.render(
        <ul>
          <LeadLine
            row={lead}
            onOpen={() => undefined}
            actions={{ onTap: () => undefined }}
            compact
          />
        </ul>,
      ),
    );
  const third = () => host.querySelector('[class*="leadWhy"]')?.textContent;
  // A call booked for another day: two lines (bug 156; the L1 judge).
  await show({
    ...row,
    why: "Next call",
    why_kind: "later",
    next_action_at: "2099-01-01T04:00:00Z",
  } as LeadRow);
  expect(third()).toBeUndefined();
  // Due later today: the third line says when.
  const later = new Date(Date.now() + 60_000);
  if (later.toDateString() === new Date().toDateString()) {
    await show({
      ...row,
      why: "Next call",
      why_kind: "later",
      next_action_at: later.toISOString(),
    } as LeadRow);
    expect(third()).toMatch(/^Next call · today /);
  }
  // Nobody owns it yet: the third line says so.
  await show({
    ...row,
    why: "Waiting for an owner",
    why_kind: "waiting",
  } as LeadRow);
  expect(third()).toContain("Waiting for an owner");
  // A lead added days ago that nobody waits on: two lines, no "Added …".
  await show({ ...row, why: "New lead", why_kind: "new" } as LeadRow);
  expect(third()).toBeUndefined();
  expect(host.textContent).not.toMatch(/Added .+ ago/);
  // An older enquiry's day ends the middle line instead, said once.
  await show({
    ...row,
    why: "New lead",
    why_kind: "new",
    source: "meta",
    side: "cold",
    received_at: "2026-10-03T04:00:00Z",
  } as LeadRow);
  expect(third()).toBeUndefined();
  expect(host.querySelector('[class*="leadSub"]')!.textContent).toMatch(
    / · Older enquiry · /,
  );
  expect(host.textContent!.match(/Older enquiry/g)).toHaveLength(1);
  // Won or lost: no next step.
  await show({ ...row, why: "Won", why_kind: "closed" } as LeadRow);
  expect(third()).toBeUndefined();
});

it("puts a new Inbound enquiry's wait on its last line, amber then red", async () => {
  const show = (lead: LeadRow) =>
    act(async () =>
      root.render(
        <ul>
          <LeadLine
            row={lead}
            onOpen={() => undefined}
            actions={{ onTap: () => undefined }}
            compact
            stageWord="New Lead"
          />
        </ul>,
      ),
    );
  const fresh = {
    ...row,
    why: "New lead",
    why_kind: "new",
    side: "inbound",
    attempts: 0,
    last_contact_at: null,
    created_at: new Date(Date.now() - 12 * 60_000).toISOString(),
  } as LeadRow;
  const why = () => host.querySelector('[class*="leadWhy"]')!;
  await show(fresh);
  expect(host.querySelector('[class*="leadSub"]')!.textContent).toBe(
    "New Lead · Website",
  );
  expect(why().textContent).toBe("Waiting 12 min");
  expect(why().getAttribute("data-tone")).toBe("warn");
  await show({
    ...fresh,
    created_at: new Date(Date.now() - 20 * 60_000).toISOString(),
  } as LeadRow);
  expect(why().getAttribute("data-tone")).toBe("bad");
  await show({ ...fresh, side: "cold" } as LeadRow);
  expect(host.textContent).not.toContain("Waiting");
  // No number: no WhatsApp.
  await show({ ...fresh, phone_last4: null } as LeadRow);
  expect(channels()).toEqual(["call"]);
});

it("gives an owner a tick that starts picking, and a seller none", async () => {
  const onPick = vi.fn();
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={() => undefined}
          actions={{ onTap: () => undefined }}
          compact
          onPick={onPick}
        />
      </ul>,
    ),
  );
  const tick = host.querySelector<HTMLButtonElement>(
    '[aria-label="Select Fictional Neha"]',
  )!;
  await act(async () => tick.click());
  expect(onPick).toHaveBeenCalledWith(row);
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={() => undefined}
          actions={{ onTap: () => undefined }}
          compact
        />
      </ul>,
    ),
  );
  expect(host.querySelector('[aria-label="Select Fictional Neha"]')).toBeNull();
});
