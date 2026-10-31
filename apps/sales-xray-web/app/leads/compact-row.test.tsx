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

it("shows the name, stage and source, the next action and one call button", async () => {
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
  expect(channels()).toEqual(["call"]);
  expect(
    host.querySelectorAll('[aria-label="Open Fictional Neha"]'),
  ).toHaveLength(1);
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
  // A new lead says when it came, not its stage again, in plain colour.
  await show({ ...row, why: "New lead", why_kind: "new" } as LeadRow);
  expect(tone()).toBeNull();
  expect(host.textContent).toMatch(/Added .+ ago$/);
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
