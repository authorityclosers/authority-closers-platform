// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { NoticeCenter } from "../notice-center";
import { LEAD_ADDED_EVENT } from "./lead-handoff";
import type { LeadRow } from "./leads-client";
import {
  FRESH_MS,
  NewLeadCard,
  arrivals,
  useArrival,
  type Arrival,
} from "./new-lead-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.parse("2026-10-24T12:00:00Z");

const lead = (n: number, extra: Partial<LeadRow> = {}) =>
  ({
    lead_id: `lead-${n}`,
    revision: 1,
    name: `fictional lead ${n}`,
    company: null,
    city: "Pune",
    language: null,
    interest: "2 BHK",
    phone_last4: "3210",
    stage: "new",
    stage_label: "New",
    source: "meta",
    source_label: "Facebook ad",
    owner_person_id: "me",
    owner_name: null,
    why: "New",
    why_kind: "new",
    next_action_at: null,
    created_at: new Date(NOW - 60_000).toISOString(),
    attempts: 0,
    calls: 0,
    last_result: null,
    last_result_label: null,
    test_data: false,
    ...extra,
  }) as LeadRow;

it("learns the first read, then pops only the seller's own fresh new leads", () => {
  expect(arrivals(null, [lead(1)], "me", NOW)).toEqual([]);
  const seen = new Set(["lead-1"]);
  const rows = [
    lead(1),
    lead(2),
    lead(3, { owner_person_id: "someone else" }),
    lead(4, { why_kind: "due" }),
    lead(5, { created_at: new Date(NOW - FRESH_MS - 1).toISOString() }),
  ];
  expect(arrivals(seen, rows, "me", NOW).map((row) => row.lead_id)).toEqual([
    "lead-2",
  ]);
});

let container: HTMLDivElement;
let root: Root;
// What the hook returned at each render, last last.
const reports: Arrival[] = [];

function Probe({ rows }: { rows: LeadRow[] | null }) {
  const arrival = useArrival(rows, "me");
  useEffect(() => {
    reports.push(arrival);
  });
  return null;
}

const latest = () => reports[reports.length - 1];

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

it("waits with what arrived between reads, and never with a lead the seller added", () => {
  const first = [lead(1)];
  act(() => root.render(<Probe rows={first} />));
  expect(latest().lead).toBeNull();
  // The seller adds lead 3 themselves: it is theirs already.
  act(() => {
    window.dispatchEvent(
      new CustomEvent(LEAD_ADDED_EVENT, {
        detail: { leadId: "lead-3", call: false },
      }),
    );
  });
  // Both fresh: only the event keeps lead 3 off the card.
  const next = [
    lead(1),
    lead(2, { created_at: new Date().toISOString() }),
    lead(3, { created_at: new Date().toISOString() }),
  ];
  act(() => root.render(<Probe rows={next} />));
  expect(latest().lead?.lead_id).toBe("lead-2");
  expect(latest().count).toBe(1);
  // Every lead waiting, for the list's pulse and a running round's next card.
  expect(latest().leads.map((row) => row.lead_id)).toEqual(["lead-2"]);
  // The page opened it: gone.
  act(() => latest().know("lead-2"));
  expect(latest().lead).toBeNull();
});

// Competitor teardown 12 (1 Nov 2026): a one-line corner pill with Call now,
// its X for Later, never a sheet over the list.
it("arrives as a corner pill with Call now, and its X is Later", async () => {
  const calls: string[] = [];
  const card = (count: number, open = true) => (
    <>
      <NoticeCenter />
      <NewLeadCard
        lead={lead(2)}
        count={count}
        open={open}
        onCall={(row) => calls.push(`call ${row.lead_id}`)}
        onMessage={(row) => calls.push(`whatsapp ${row.lead_id}`)}
        onLater={() => calls.push("later")}
      />
    </>
  );
  await act(async () => root.render(card(1)));
  expect(container.querySelector("dialog")).toBeNull();
  const pill = container.querySelector('[aria-expanded="false"]');
  expect(pill?.textContent).toBe(
    "New enquiry · Fictional Lead 2 · Facebook ad",
  );
  await act(async () => root.render(card(3)));
  expect(container.textContent).toContain(
    "3 new enquiries · Fictional Lead 2 and 2 more",
  );
  const now = [...container.querySelectorAll("button")].find(
    (item) => item.textContent === "Call now",
  )!;
  await act(async () => now.click());
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-label="Dismiss"]')!
      .click(),
  );
  expect(calls).toEqual(["call lead-2", "later"]);
  // Closed by the page: gone.
  await act(async () => root.render(card(1, false)));
  expect(container.textContent).not.toContain("New enquiry");
});

it("never pops up a Cold lead (ph1-16, 1 Nov 2026: 900 imported)", () => {
  const seen = new Set<string>();
  const rows = [lead(1, { side: "cold" }), lead(2)];
  expect(arrivals(seen, rows, "me", NOW).map((row) => row.lead_id)).toEqual([
    rows[1].lead_id,
  ]);
});
