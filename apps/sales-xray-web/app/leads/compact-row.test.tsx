// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadLine } from "./desk-view";
import type { LeadRow } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Dipak's Home + Leads handoff (31 Oct 2026, items 74-79): in the work views a
// lead is its name, "Stage · Source", the next action and one call button.
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

it("pulses a lead that just arrived, and its name keeps its own box for the ellipsis", async () => {
  await act(async () =>
    root.render(
      <ul>
        <LeadLine row={row} onOpen={() => undefined} compact fresh />
      </ul>,
    ),
  );
  const line = host.querySelector("[data-lead-row]")!;
  expect(line.hasAttribute("data-fresh")).toBe(true);
  // A 300-letter name ends in "…" inside its own span (the test robot, 1 Nov 2026).
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
  await show(late, true);
  expect(tone()).toBeNull();
  await show({ ...late, next_action_at: "2099-01-01T04:00:00Z" } as LeadRow);
  expect(tone()).toBeNull();
  // A new lead has no last line now: no "Added N days ago" (bug 156, shorter rows).
  await show({ ...row, why: "New lead", why_kind: "new" } as LeadRow);
  expect(host.querySelector('[class*="leadWhy"]')).toBeNull();
  expect(host.textContent).not.toMatch(/Added .+ ago/);
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
  // A call booked for later: two lines.
  await show({
    ...row,
    why: "Next call",
    why_kind: "later",
    next_action_at: "2099-01-01T04:00:00Z",
  } as LeadRow);
  expect(third()).toBeUndefined();
  // Nobody owns it yet: the third line says so.
  await show({
    ...row,
    why: "Waiting for an owner",
    why_kind: "waiting",
  } as LeadRow);
  expect(third()).toContain("Waiting for an owner");
  // An older enquiry's day ends the middle line instead.
  await show({
    ...row,
    why: "New lead",
    why_kind: "new",
    source: "meta",
    side: "cold",
    received_at: "2026-10-03T04:00:00Z",
  } as LeadRow);
  expect(third()).toBeUndefined();
  expect(host.textContent).toContain("Older enquiry");
});

it("ends a new Inbound enquiry's middle line with its wait, and nobody else's", async () => {
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
  await show(fresh);
  expect(host.textContent).toContain("New Lead · Website · waited 12 min");
  expect(host.querySelector('[class*="leadWhy"]')).toBeNull();
  await show({ ...fresh, side: "cold" } as LeadRow);
  expect(host.textContent).not.toContain("waited");
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
