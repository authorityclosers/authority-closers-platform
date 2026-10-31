import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import {
  PerformanceView,
  flags,
  measures,
  missed,
  percent,
  sellerLine,
} from "./performance-view";
import type { Effort, SellerEffort, SideEffort } from "./performance-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const side = (extra: Partial<SideEffort> = {}): SideEffort => ({
  attempted: 0,
  connected: 0,
  talk_seconds: 0,
  leads_attempted: 0,
  reached: 0,
  interested: 0,
  meetings: 0,
  won: 0,
  worked_interested: 0,
  backlog: 0,
  eligible: 0,
  first_call_minutes: null,
  late: 0,
  missed_calls: 0,
  not_called_back: 0,
  ...extra,
});

// Fictional sellers and numbers.
const inbound = side({
  attempted: 40,
  connected: 16,
  talk_seconds: 4800,
  leads_attempted: 30,
  reached: 14,
  interested: 5,
  meetings: 2,
  won: 1,
  worked_interested: 6,
  backlog: 3,
  eligible: 40,
  first_call_minutes: 7,
  late: 2,
  missed_calls: 3,
  not_called_back: 1,
});
const cold = side({
  attempted: 60,
  connected: 12,
  talk_seconds: 1800,
  leads_attempted: 55,
  reached: 11,
  interested: 2,
  worked_interested: 2,
  backlog: 900,
  eligible: 1000,
  late: 1,
});

const seller = (extra: Partial<SellerEffort> = {}): SellerEffort => ({
  person_id: "00000000-0000-4000-8000-000000000001",
  name: "Asha Fictional",
  inbound,
  cold,
  breaks: [
    {
      start: "2026-10-30T05:10:00Z",
      end: "2026-10-30T06:30:00Z",
      minutes: 80,
      planned: false,
      approximate: true,
    },
  ],
  unplanned_break_minutes: 135,
  first_call_at: "2026-10-30T04:35:00Z",
  last_call_at: "2026-10-30T12:10:00Z",
  tasks_late: 1,
  missing_recordings: 2,
  ...extra,
});

const effort = (team: boolean): Effort => ({
  days: 1,
  start: "2026-10-29T18:30:00Z",
  end: "2026-10-30T12:00:00Z",
  team,
  sellers: [seller()],
  inbound,
  cold,
  missing_recordings: 2,
});

let root: Root;
let host: HTMLDivElement;
let asked: string[];

function answer(value: Effort) {
  asked = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      asked.push(String(input));
      return new Response(JSON.stringify(value));
    }),
  );
}

async function mount() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<PerformanceView />));
  await act(async () => Promise.resolve());
}

afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
});

const table = (rows: { label: string; inbound: string; cold: string }[]) =>
  Object.fromEntries(
    rows.map((item) => [item.label, [item.inbound, item.cold]]),
  );

it("measures Inbound and Cold apart, as Dipak's table does", () => {
  const work = table(measures(inbound, cold));
  expect(work["Calls attempted"]).toEqual(["40", "60"]);
  expect(work["Connection rate"]).toEqual(["40%", "20%"]);
  expect(work["Talk time"]).toEqual(["1 h 20 min", "30 min"]);
  expect(work["Contact coverage"]).toEqual(["75%", "6%"]);
  expect(work["Worked → Interested"]).toEqual(["20%", "4%"]);
  // First-call speed is Inbound's: a Cold list's import time says nothing.
  expect(work["First call in"]).toEqual(["7 min", "Not measured"]);
  const gone = table(missed(inbound, cold));
  expect(gone["Late now (over an hour)"]).toEqual(["2", "1"]);
  expect(gone["Missed calls"]).toEqual(["3", "0"]);
  expect(gone["Not called back"]).toEqual(["1", "0"]);
  expect(gone["Not called yet"]).toEqual(["3", "900"]);
  expect(percent(1, 0)).toBe("–");
  expect(sellerLine(seller())).toBe(
    "100 calls · 28% connected · 1 h 50 min talk",
  );
});

it("flags only what needs the owner's eye", () => {
  expect(flags(seller())).toEqual([
    "3 leads late",
    "1 not called back",
    "1 task late",
    "2 calls without a recording",
  ]);
  const calm = side();
  expect(
    flags(
      seller({
        inbound: calm,
        cold: calm,
        tasks_late: 0,
        missing_recordings: 0,
      }),
    ),
  ).toEqual([]);
});

it("shows an owner the team and each seller, flags first", async () => {
  answer(effort(true));
  await mount();
  expect(asked).toEqual(["/v1/lead-desk/performance/sellers?days=1"]);
  const team = host.querySelector('[aria-labelledby="team-title"]');
  expect(
    Array.from(team?.querySelectorAll("table") ?? [], (item) =>
      item.getAttribute("aria-label"),
    ),
  ).toEqual([
    "The team's work, Inbound and Cold",
    "The team's missed work, Inbound and Cold",
  ]);
  expect(team?.textContent).toContain("2 calls without a recording today");
  const card = host.querySelector("details");
  expect(card?.open).toBe(false);
  const summary = card?.querySelector("summary");
  expect(summary?.querySelector("strong")?.textContent).toBe("Asha Fictional");
  // The red flags show before the card opens.
  expect(
    Array.from(
      summary?.querySelectorAll("li") ?? [],
      (item) => item.textContent,
    ),
  ).toEqual([
    "3 leads late",
    "1 not called back",
    "1 task late",
    "2 calls without a recording",
  ]);
  // Breaks: red unless set; ≈ next to a call from the app's Call button.
  const gap = card?.querySelector('[aria-label="3 longest breaks"] li');
  expect(gap?.hasAttribute("data-red")).toBe(true);
  expect(gap?.textContent).toContain("≈ 1 h 20 min");
  expect(card?.textContent?.replace(/\s+/g, " ")).toContain(
    "Today: first call 10:05 AM, last call ends 5:40 PM",
  );
  expect(card?.textContent).toContain(
    "Between calls, outside set breaks: 2 h 15 min",
  );
  expect(host.textContent).toContain("≈ Next to a call from the app");
});

it("shows a seller only their own, and reads 7 days on request", async () => {
  answer(effort(false));
  await mount();
  expect(host.querySelector('[aria-labelledby="team-title"]')).toBeNull();
  const own = host.querySelector("details");
  expect(own?.open).toBe(true);
  expect(own?.querySelector("summary strong")?.textContent).toBe("You");
  const week = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "7 days",
  );
  await act(async () => week?.click());
  await act(async () => Promise.resolve());
  expect(asked.at(-1)).toBe("/v1/lead-desk/performance/sellers?days=7");
});
