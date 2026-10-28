// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: unknown; href: string }) => (
    <a href={href}>{children as never}</a>
  ),
}));

import type { Performance, Period } from "../leads/leads-client";
import { changeWords, OutcomeTiles, TILE_SETS } from "./outcome-tiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner Home v3 (28 Oct 2026): B's tiles. Fictional numbers and names only.
const day = (iso: string, won: number, interested: number) => ({
  day: iso,
  calls: 6,
  connected: 2,
  interested,
  won,
  new_leads: 3,
});

const week: Performance = {
  days: 7,
  start: "2026-10-22",
  end: "2026-10-28",
  current: {
    calls: 41,
    connected: 13,
    leads_called: 30,
    interested: 12,
    won: 6,
    new_leads: 38,
    first_call_minutes: 18,
  },
  previous: {
    calls: 35,
    connected: 15,
    leads_called: 28,
    interested: 8,
    won: 4,
    new_leads: 38,
    first_call_minutes: 25,
  },
  sellers: [
    ["p1", "Asha Example", 18, 7, 5, 3],
    ["p2", "Rohan Sample", 15, 4, 4, 0],
    ["p3", "Vikram Fictional", 8, 2, 3, 3],
  ].map(([person_id, name, calls, connected, interested, won]) => ({
    person_id: person_id as string,
    name: name as string,
    calls: calls as number,
    connected: connected as number,
    interested: interested as number,
    won: won as number,
    open_leads: 10,
    late: 0,
  })),
  pipeline: {},
  daily: [
    day("2026-10-22", 0, 1),
    day("2026-10-23", 0, 2),
    day("2026-10-24", 1, 1),
    day("2026-10-25", 0, 2),
    day("2026-10-26", 1, 3),
    day("2026-10-27", 1, 1),
    day("2026-10-28", 3, 2),
  ],
};

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  // Reduced motion: the numbers are final at once.
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: query.includes("reduce"),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function draw(
  performance: Performance | null,
  period: Period = 7,
  onPeriod = vi.fn(),
  failed = false,
) {
  await act(async () =>
    root.render(
      <OutcomeTiles
        period={period}
        onPeriod={onPeriod}
        performance={performance}
        failed={failed}
      />,
    ),
  );
  // The count-up settles on the next frame.
  await act(
    async () =>
      new Promise<void>((done) => requestAnimationFrame(() => done())),
  );
  return onPeriod;
}

const tile = (key: string) =>
  host.querySelector<HTMLButtonElement>(`button[data-tile="${key}"]`)!;

it("shows the four outcomes, each with its change and its words", async () => {
  await draw(week);
  expect(tile("won").textContent).toContain("6");
  expect(tile("won").textContent).toContain("2 more");
  expect(tile("won").textContent).toContain("20% of 30 leads called");
  expect(tile("interested").textContent).toContain("4 more");
  expect(tile("new_leads").textContent).toContain("Same as before");
  expect(tile("new_leads").textContent).toContain("First call in 18 min");
  // Connected is the share; its change compares connected calls.
  expect(tile("connected").textContent).toContain("32%");
  expect(tile("connected").textContent).toContain("2 fewer");
  expect(tile("connected").textContent).toContain("13 of 41 calls");
  expect(host.textContent).toContain("Compared with the previous 7 days");
});

it("draws a week's days as seven bars, a true zero kept as a mark", async () => {
  await draw(week);
  const bars = tile("won").querySelector('[role="img"]');
  expect(bars?.getAttribute("aria-label")).toContain("Won by day:");
  expect(bars?.children).toHaveLength(7);
  expect(tile("won").querySelectorAll("[data-zero]").length).toBe(3);
  // Each day's number sits on its bar.
  expect(
    Array.from(
      bars?.querySelectorAll("small") ?? [],
      (label) => label.textContent,
    ),
  ).toEqual(["0", "0", "1", "0", "1", "1", "3"]);
});

it("opens a tile's detail: the days, who did it, and the leads behind it", async () => {
  await draw(week);
  await act(async () => tile("won").click());
  const sheet = document.querySelector("dialog[open]");
  expect(sheet?.textContent).toContain("2 more than the previous 7 days (4)");
  // Ranked by the tile's own count; nobody with none.
  const sellers = Array.from(
    sheet?.querySelectorAll('a[href^="/organisation/people/"]') ?? [],
    (link) => link.getAttribute("href"),
  );
  expect(sellers).toEqual([
    "/organisation/people/p1",
    "/organisation/people/p3",
  ]);
  expect(sheet?.textContent).toContain("Vikram Fictional3 won");
  expect(
    sheet?.querySelector('a[href="/leads?tab=all&stage=won"]')?.textContent,
  ).toBe("See won leads");
});

it("keeps the period in one segmented control", async () => {
  const onPeriod = await draw(week);
  const month = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "30 days",
  );
  await act(async () => month?.click());
  expect(onPeriod).toHaveBeenCalledWith(30);
  expect(host.querySelector("select")).toBeNull();
});

it("draws no days for today, and a dash when nobody called", async () => {
  const today: Performance = {
    ...week,
    days: 1,
    current: { ...week.current, calls: 0, connected: 0, leads_called: 0 },
    daily: [day("2026-10-28", 0, 0)],
  };
  await draw(today, 1);
  expect(tile("won").querySelector('[role="img"]')).toBeNull();
  expect(tile("won").textContent).toContain("No leads called yet");
  expect(tile("connected").textContent).toContain("–");
  expect(host.textContent).toContain("Compared with yesterday");
});

it("says when the numbers didn't load", async () => {
  await draw(null, 7, vi.fn(), true);
  expect(host.textContent).toContain("Sales numbers didn't load");
});

it("words a change in counts", () => {
  expect(changeWords(6, 4)).toBe("2 more");
  expect(changeWords(1, 3)).toBe("2 fewer");
  expect(changeWords(0, 0)).toBe("Same as before");
});

// Orchestrator, 28 Oct 2026: the set is configuration; operations first is one switch away.
it("draws whichever set it is given, in its order", async () => {
  await act(async () =>
    root.render(
      <OutcomeTiles
        period={7}
        onPeriod={vi.fn()}
        performance={{
          ...week,
          pipeline: { new: 162, follow_up: 3 },
          sellers: week.sellers.map((seller, index) => ({
            ...seller,
            late: index,
          })),
        }}
        failed={false}
        tiles={TILE_SETS.operations}
      />,
    ),
  );
  await act(
    async () =>
      new Promise<void>((done) => requestAnimationFrame(() => done())),
  );
  expect(
    Array.from(host.querySelectorAll("button[data-tile]"), (each) =>
      each.getAttribute("data-tile"),
    ),
  ).toEqual(["new_leads", "untouched", "first_call", "calls", "late"]);
  expect(tile("untouched").textContent).toContain("162");
  expect(tile("untouched").textContent).toContain("Right now");
  expect(tile("first_call").textContent).toContain("18 min");
  expect(tile("first_call").textContent).toContain("25 min the period before");
  expect(tile("calls").textContent).toContain("6 more");
  expect(tile("late").textContent).toContain("3");
  await act(async () => tile("late").click());
  expect(
    document
      .querySelector("dialog[open]")
      ?.querySelector('a[href="/leads?tab=all&due=late"]')?.textContent,
  ).toBe("See late leads");
});

it("shows the owner's outcomes unless told otherwise", async () => {
  await draw(week);
  expect(
    Array.from(host.querySelectorAll("button[data-tile]"), (each) =>
      each.getAttribute("data-tile"),
    ),
  ).toEqual([...TILE_SETS.outcomes]);
});
