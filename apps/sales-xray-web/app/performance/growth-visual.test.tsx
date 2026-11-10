import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  busiest,
  DayRhythm,
  daySlots,
  GROWTH_VIEWS,
  hourSlots,
  PulseTiles,
  SpeedTile,
} from "./growth-visual";
import type { Effort, SellerEffort, SideEffort } from "./performance-client";

vi.mock("../leads/leads-client", async (original) => ({
  ...(await original<typeof import("../leads/leads-client")>()),
  readDayCalls: vi.fn(),
}));
import { readDayCalls } from "../leads/leads-client";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

const side = (values: Partial<SideEffort> = {}): SideEffort => ({
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
  ...values,
});
const seller = (
  id: string,
  name: string,
  inbound: Partial<SideEffort>,
  cold: Partial<SideEffort> = {},
): SellerEffort => ({
  person_id: id,
  name,
  inbound: side(inbound),
  cold: side(cold),
  breaks: [],
  unplanned_break_minutes: 0,
  first_call_at: null,
  last_call_at: null,
  tasks_late: 0,
  missing_recordings: 0,
});
// Fictional team, real shapes.
const effort: Effort = {
  days: 1,
  start: "2026-11-10",
  end: "2026-11-10",
  team: true,
  sellers: [
    seller("p-2", "rohan deshmukh", {
      attempted: 20,
      connected: 5,
      talk_seconds: 1800,
    }),
    seller(
      "p-1",
      "Priya Kulkarni",
      { attempted: 30, connected: 12, talk_seconds: 3600 },
      { attempted: 22, connected: 6 },
    ),
  ],
  inbound: side({
    attempted: 86,
    connected: 41,
    talk_seconds: 11520,
    interested: 9,
    leads_attempted: 70,
    reached: 30,
    meetings: 1,
    late: 55,
    backlog: 127,
    first_call_minutes: 12,
  }),
  cold: side({
    attempted: 142,
    connected: 37,
    talk_seconds: 7500,
    interested: 6,
    leads_attempted: 120,
    reached: 25,
    backlog: 900,
    missed_calls: 3,
  }),
  missing_recordings: 0,
};

it("shows the tiles first and the day rhythm after, in one list a choice can reorder", () => {
  expect(GROWTH_VIEWS).toEqual(["tiles", "rhythm"]);
});

it("draws G1's four tiles from the real totals, with no table", () => {
  const opened = vi.fn();
  act(() => root.render(<PulseTiles effort={effort} onOpen={opened} />));
  expect(host.querySelector("table")).toBeNull();
  const tiles = [
    ...host.querySelectorAll(
      '[data-growth-view="tiles"] > div:first-of-type > div',
    ),
  ];
  // One total a tile, no Inbound | Cold split (owner, 10 Nov 2026).
  expect(tiles.map((tile) => tile.textContent)).toEqual([
    "Attempted228190 leads called",
    "Connected7834%55 leads reached",
    "Talk time5 h 17 min4 min a connected call",
    "Interested151 meeting booked",
  ]);
  expect(
    host.querySelector('[data-growth-view="tiles"]')?.textContent,
  ).not.toMatch(/Inbound|Cold/);
  // Only what is above zero needs attention.
  const needs = [...host.querySelectorAll("li[data-tone]")].map(
    (row) => row.textContent,
  );
  expect(needs).toEqual([
    "Late follow-ups55",
    "Not called yet1,027",
    "Missed calls3",
  ]);
  // Sellers by calls, names with capitals; a tap opens their day.
  const rows = [
    ...host.querySelectorAll('[aria-label="Each seller\'s calls"] button'),
  ];
  expect(
    rows.map((row) => row.querySelector("span span")?.textContent),
  ).toEqual(["Priya Kulkarni", "Rohan Deshmukh"]);
  expect(rows[0].textContent).toContain("52 attempted · 18 connected");
  act(() => (rows[1] as HTMLButtonElement).click());
  expect(opened).toHaveBeenCalledWith(effort.sellers[0]);
});

it("keeps speed to a new lead small, and a dash when there is none", () => {
  act(() => root.render(<SpeedTile effort={effort} />));
  expect(host.textContent).toBe(
    "Speed to new leadInbound, median to the first call12 min",
  );
  act(() =>
    root.render(
      <SpeedTile
        effort={{ ...effort, inbound: side({ first_call_minutes: null }) }}
      />,
    ),
  );
  expect(host.querySelector("strong")?.textContent).toBe("–");
});

it("counts today's calls by India hour, from 9 am to 7 pm at least", () => {
  const call = (at: string) => ({
    event_id: at,
    lead_id: "l",
    lead_name: "Fictional Lead",
    stage_label: null,
    event: { kind: "call", at },
  });
  const slots = hourSlots(
    [
      call("2026-11-10T05:40:00Z"), // 11:10 am in India
      call("2026-11-10T05:50:00Z"),
      call("2026-11-10T09:05:00Z"), // 2:35 pm
    ] as never,
    "Asia/Kolkata",
  );
  expect(slots[0].label).toBe("9 am");
  expect(slots.at(-1)?.label).toBe("7 pm");
  expect(slots.find((slot) => slot.label === "11 am")?.calls).toBe(2);
  expect(slots.find((slot) => slot.label === "2 pm")?.calls).toBe(1);
  expect(busiest(slots)?.label).toBe("11 am");
  expect(busiest(hourSlots([]))).toBeNull();
});

it("adds the team's calls by day over the period's own days only", () => {
  // The summary's daily rows also carry the period before (seen on dev, 10
  // Nov 2026: 7 days drew from 28 Oct); a day with no calls is drawn as 0.
  const slots = daySlots(
    [
      {
        daily: [
          { day: "2026-11-01", calls: 9 },
          { day: "2026-11-08", calls: 4 },
          { day: "2026-11-10", calls: 1 },
        ],
      },
      { daily: [{ day: "2026-11-10", calls: 2 }] },
    ],
    "2026-11-08T00:00:00Z",
    "2026-11-10",
  );
  expect(slots.map((slot) => [slot.label, slot.calls])).toEqual([
    ["8 Nov", 4],
    ["9 Nov", 0],
    ["10 Nov", 3],
  ]);
});

it("folds sellers with no calls into one line", () => {
  const quiet = {
    ...effort,
    sellers: [...effort.sellers, seller("p-3", "Fictional Third", {})],
  };
  act(() => root.render(<PulseTiles effort={quiet} />));
  expect(
    host.querySelectorAll('[aria-label="Each seller\'s calls"] li'),
  ).toHaveLength(2);
  expect(host.textContent).toContain("1 more seller with no calls yet.");
});

it("names today's busiest hour on G4's fourth card, from the team's calls", async () => {
  vi.mocked(readDayCalls).mockResolvedValue({
    items: [
      {
        event_id: "e1",
        lead_id: "l1",
        lead_name: "Fictional Lead",
        stage_label: null,
        event: { kind: "call", at: "2026-11-10T05:40:00Z" },
      },
    ],
    next_before: null,
    counts: {},
    timezone: "Asia/Kolkata",
  } as never);
  await act(async () => root.render(<DayRhythm effort={effort} period="1" />));
  expect(readDayCalls).toHaveBeenCalledWith(
    "today",
    { person: null, team: true },
    null,
    expect.anything(),
  );
  expect(host.textContent).toContain("Busiest at 11 am");
  expect(host.textContent).toContain("78of 228 attempted");
  // Talk time by seller, longest first.
  expect(
    [...host.querySelectorAll('[aria-label="Talk time by seller"] li')].map(
      (row) => row.textContent,
    ),
  ).toEqual(["Priya Kulkarni1 h", "Rohan Deshmukh30 min"]);
});

it("draws a seller's own Growth the same way, with no list of sellers", async () => {
  // Redmi QA on production (10 Nov 2026): a seller's Growth was still a table.
  const own = { ...effort, team: false, sellers: effort.sellers.slice(1) };
  act(() => root.render(<PulseTiles effort={own} />));
  expect(host.querySelector("h2")?.textContent).toBe("Your work");
  expect(host.textContent).not.toContain("Each seller");
  expect(host.querySelector("table")).toBeNull();
  vi.mocked(readDayCalls).mockResolvedValue({
    items: [],
    next_before: null,
    counts: {},
  } as never);
  await act(async () => root.render(<DayRhythm effort={own} period="1" />));
  expect(readDayCalls).toHaveBeenCalledWith(
    "today",
    { person: null, team: false },
    null,
    expect.anything(),
  );
  expect(host.querySelector('[aria-label="Talk time by seller"]')).toBeNull();
  expect(host.textContent).toContain("4 min a connected call");
});
