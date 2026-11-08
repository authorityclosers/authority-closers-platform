// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { countsToAsk, dayCounts, dayGroups, dayOf } from "./day-groups";
import { readLeads, type LeadRow } from "./leads-client";
import { ListView } from "./list-view";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: () => undefined,
}));
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  readLeads: vi.fn(),
}));
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Follow-ups by day (Leads L1, owner 8 Nov 2026; spec.md §3): a card a group,
// Overdue, Due Today and Upcoming, the server's own split in India's day, and
// counts that add up to the tab's.

const lead = (n: number, at: string | null): LeadRow =>
  ({
    lead_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    revision: 1,
    name: `Fictional Lead ${n}`,
    company: null,
    city: null,
    language: null,
    interest: null,
    phone_last4: "1234",
    has_email: false,
    stage: "follow_up",
    stage_label: "Open Leads",
    source: "manual",
    source_label: "Added by hand",
    owner_person_id: null,
    owner_name: null,
    why: "Follow-up",
    why_kind: "later",
    next_action_at: at,
    created_at: "2026-10-28T00:00:00Z",
    attempts: 1,
    calls: 1,
    last_result: null,
    last_result_label: null,
    test_data: false,
  }) as LeadRow;

it("splits by India's day, not the clock's", () => {
  const now = new Date("2026-11-08T06:30:00Z"); // 12:00 in India
  // 00:30 on the 8th in India is still the 7th in UTC: today.
  expect(dayOf(lead(1, "2026-11-07T19:00:00Z"), now)).toBe("today");
  expect(dayOf(lead(2, "2026-11-07T18:00:00Z"), now)).toBe("overdue");
  // 00:10 on the 9th in India is the 8th in UTC: upcoming.
  expect(dayOf(lead(3, "2026-11-08T18:40:00Z"), now)).toBe("upcoming");
  expect(dayOf(lead(4, null), now)).toBe("upcoming");
});

it("counts each group honestly from what is read, and asks for the rest", () => {
  const now = new Date("2026-11-08T06:30:00Z");
  const overdue = lead(1, "2026-11-06T06:30:00Z");
  const today = lead(2, "2026-11-08T08:30:00Z");
  const upcoming = lead(3, "2026-11-10T06:30:00Z");
  // Everything read: each group's own rows.
  const all = dayGroups([overdue, today, today, upcoming], now);
  expect(dayCounts(all, true, 4)).toEqual({
    overdue: 1,
    today: 2,
    upcoming: 1,
  });
  // More to read, but the last row read is Upcoming: the groups before it are
  // whole, and Upcoming is the rest of the total.
  expect(dayCounts(all, false, 40)).toEqual({
    overdue: 1,
    today: 2,
    upcoming: 37,
  });
  // The last row read is Due Today: only the server knows how many.
  const partial = dayGroups([overdue, today], now);
  const first = dayCounts(partial, false, 40);
  expect(first).toEqual({ overdue: 1, today: null, upcoming: null });
  expect(countsToAsk(first)).toEqual(["today"]);
  expect(dayCounts(partial, false, 40, { today: 9 })).toEqual({
    overdue: 1,
    today: 9,
    upcoming: 30,
  });
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({})),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

const IST = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });
const days = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString();
const todayNoon = () => `${IST.format(new Date())}T12:00:00+05:30`;

const render = (view: "follow_ups" | "to_call") =>
  act(async () =>
    root.render(
      <ListView
        canManage={false}
        stage="all"
        stageLabel="Follow-ups"
        more={{ side: "inbound", view }}
        bare
        scope="mine"
        query=""
        version={0}
        onOpen={() => {}}
        actions={{ onTap: () => undefined }}
      />,
    ),
  );
const heads = () =>
  [...host.querySelectorAll("h3")].map((head) => head.textContent);

it("draws Follow-ups as a card a day group, with Show all past five rows", async () => {
  const rows = [
    ...[1, 2, 3].map((n) => lead(n, days(-3))),
    ...[4, 5, 6, 7, 8, 9].map((n) => lead(n, todayNoon())),
    ...[10, 11, 12].map((n) => lead(n, days(3))),
  ];
  vi.mocked(readLeads).mockResolvedValue({
    leads: rows,
    total: 12,
    next_offset: null,
  });
  await render("follow_ups");
  expect(heads()).toEqual(["Overdue3", "Due Today6", "Upcoming3"]);
  const panel = host.querySelector("section[aria-label='Follow-ups']")!;
  expect(panel.hasAttribute("data-card")).toBe(false);
  const today = host.querySelector("section[aria-label='Due Today']")!;
  expect(today.querySelectorAll("[data-lead-row]")).toHaveLength(5);
  const all = today.querySelector<HTMLButtonElement>(
    "button[class*='dayAll']",
  )!;
  expect(all.textContent).toBe("Show all 6");
  await act(async () => all.click());
  expect(today.querySelectorAll("[data-lead-row]")).toHaveLength(6);
  expect(today.querySelector("button[class*='dayAll']")).toBeNull();
  // Three rows: no Show all.
  expect(
    host.querySelector("section[aria-label='Overdue'] button[class*='dayAll']"),
  ).toBeNull();
});

it("asks the server for a group's count when its rows aren't all read", async () => {
  vi.mocked(readLeads).mockImplementation(async (ask) =>
    ask.more?.when === "today"
      ? { leads: [], total: 9, next_offset: null }
      : {
          leads: [lead(1, days(-3)), lead(2, todayNoon())],
          total: 20,
          next_offset: 2,
        },
  );
  await render("follow_ups");
  expect(
    vi.mocked(readLeads).mock.calls.map(([ask]) => ask.more?.when),
  ).toContain("today");
  // Overdue is whole, Due Today is the server's 9, Upcoming the rest of 20.
  expect(heads()).toEqual(["Overdue1", "Due Today9", "Upcoming10"]);
});

it("keeps To Call as one list in one card", async () => {
  vi.mocked(readLeads).mockResolvedValue({
    leads: [lead(1, days(-3)), lead(2, days(3))],
    total: 2,
    next_offset: null,
  });
  await render("to_call");
  expect(heads()).toEqual([]);
  expect(
    host
      .querySelector("section[aria-label='Follow-ups']")!
      .hasAttribute("data-card"),
  ).toBe(true);
  expect(
    host.querySelectorAll('ul[aria-label="Leads"] [data-lead-row]'),
  ).toHaveLength(2);
});

it("draws List | Table where the page gives it a place, not over the list", async () => {
  vi.mocked(readLeads).mockResolvedValue({
    leads: [lead(1, days(3))],
    total: 1,
    next_offset: null,
  });
  const slot = document.createElement("span");
  document.body.append(slot);
  await act(async () =>
    root.render(
      <ListView
        canManage={false}
        stage="all"
        stageLabel="Follow-ups"
        more={{ side: "inbound", view: "to_call" }}
        bare
        layoutSlot={slot}
        scope="mine"
        query=""
        version={0}
        onOpen={() => {}}
      />,
    ),
  );
  expect(slot.querySelector('[aria-label="Show leads as"]')).not.toBeNull();
  expect(
    host.querySelector('[class*="listHead"] [aria-label="Show leads as"]'),
  ).toBeNull();
  slot.remove();
});

it('puts "Syncing…" where the page gives it a place, so the list\'s head takes no room', async () => {
  let answer!: (page: Awaited<ReturnType<typeof readLeads>>) => void;
  vi.mocked(readLeads).mockImplementation(
    () =>
      new Promise((done) => {
        answer = done;
      }),
  );
  const slot = document.createElement("span");
  document.body.append(slot);
  await act(async () =>
    root.render(
      <ListView
        canManage={false}
        stage="all"
        stageLabel="To call"
        more={{ side: "inbound", view: "to_call" }}
        bare
        syncSlot={slot}
        scope="mine"
        query=""
        version={0}
        onOpen={() => {}}
      />,
    ),
  );
  expect(slot.textContent).toBe("Syncing…");
  expect(host.querySelector('[aria-label="Lead sync"]')).toBeNull();
  await act(async () =>
    answer({ leads: [lead(1, days(3))], total: 1, next_offset: null }),
  );
  const sign = slot.querySelector('[aria-label="Lead sync"]')!;
  expect(sign.textContent).toBe("");
  expect(sign.hasAttribute("data-quiet")).toBe(true);
  slot.remove();
});
