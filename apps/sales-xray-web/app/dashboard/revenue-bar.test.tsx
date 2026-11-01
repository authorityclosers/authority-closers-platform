// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  chainLine,
  daysLeft,
  goLine,
  paceLine,
  RevenueBar,
  toneOf,
} from "./revenue-bar";
import type { Revenue } from "./revenue-client";
import { inr, REVENUE_CHANGED } from "./revenue-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Revenue targets (owner meeting, 28 Oct 2026): Home's slim bar. Fictional people.
const MINE: Revenue = {
  scope: "mine",
  month: "2026-10-01",
  currency: "INR",
  month_gone: 0.6,
  target: 500000,
  target_source: "split",
  won: 200000,
  deals: 2,
  amount_not_set: 1,
  needs: {
    wins: 3,
    meetings: 9,
    interested: 30,
    connected: 120,
    calls: 300,
    calls_per_day: 18,
    working_days_left: 17,
    average_deal: 100000,
    estimate: true,
  },
  sellers: [],
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

function serve(body: Revenue) {
  const asked: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      asked.push(url);
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  return asked;
}

async function settle() {
  for (let i = 0; i < 6; i++)
    await act(async () => await new Promise((done) => setTimeout(done, 0)));
}

it("says the month in lakhs, where the month is, and the calls a day it takes", async () => {
  const asked = serve(MINE);
  await act(async () => root.render(<RevenueBar scope="mine" />));
  await settle();
  expect(asked[0]).toContain("/revenue?scope=mine");
  const text = container.textContent ?? "";
  // What is left and the days to do it (competitor teardown #8, 1 Nov 2026).
  expect(text).toContain("₹3 L to go · 17 days");
  expect(text).toContain("₹2 L of ₹5 L · October");
  expect(text).toContain("40%");
  expect(text).toContain("1 won without an amount");
  const tick = container.querySelector<HTMLElement>('[aria-hidden="true"]');
  expect(tick?.style.left).toBe("60%");
  // Behind the month: 40% won with 60% of it gone.
  expect(
    container.querySelector<HTMLElement>("[data-tone]")?.dataset.tone,
  ).toBe("behind");
  // A tap shows what it takes, at the team's own rates (typical ones here).
  await act(async () => container.querySelector("button")?.click());
  expect(document.body.textContent).toContain("At typical rates");
  expect(document.body.textContent).toContain(
    "≈ 3 wins → 9 meetings → 30 interested → 300 calls · 18 a day",
  );
});

it("shows nothing without a target, and never a box while it loads", async () => {
  serve({ ...MINE, target: null, needs: null });
  await act(async () => root.render(<RevenueBar scope="mine" />));
  expect(container.innerHTML).toBe("");
  await settle();
  expect(container.innerHTML).toBe("");
});

it("reads again when a target is saved, without a reload", async () => {
  // Phone personas (31 Oct 2026): the team's target was set in Team controls and
  // Team Home kept no bar until a reload.
  serve({ ...MINE, target: null, needs: null });
  await act(async () => root.render(<RevenueBar scope="mine" />));
  await settle();
  expect(container.innerHTML).toBe("");
  const asked = serve(MINE);
  await act(async () => {
    window.dispatchEvent(new Event(REVENUE_CHANGED));
  });
  await settle();
  expect(asked[0]).toContain("/revenue?scope=mine");
  expect(container.textContent).toContain("of ₹5 L · October");
});

it("opens each seller's month for the team, by name and never ranked", async () => {
  serve({
    ...MINE,
    scope: "team",
    target: 1000000,
    target_source: "organisation",
    sellers: [
      {
        person_id: "a",
        name: "Asha Fictional",
        target: 300000,
        target_source: "own",
        won: 50000,
        deals: 1,
        amount_not_set: 0,
      },
      {
        person_id: "b",
        name: "Ravi Fictional",
        target: 500000,
        target_source: "split",
        won: 150000,
        deals: 1,
        amount_not_set: 1,
      },
    ],
  });
  await act(async () => root.render(<RevenueBar scope="team" />));
  await settle();
  const bar = container.querySelector<HTMLButtonElement>("button");
  expect(bar?.textContent).toContain("What it takes");
  await act(async () => bar?.click());
  const names = Array.from(document.querySelectorAll("li span")).map(
    (node) => node.textContent,
  );
  expect(names.indexOf("Asha Fictional")).toBeLessThan(
    names.indexOf("Ravi Fictional"),
  );
  expect(document.body.textContent).toContain("Own target");
  expect(document.body.textContent).toContain("Even share");
});

it("reads the tone and the line under the bar", () => {
  expect(toneOf(500000, 500000, 0.4)).toBe("done");
  expect(toneOf(250000, 500000, 0.5)).toBe("on");
  expect(toneOf(100000, 500000, 0.5)).toBe("behind");
  expect(goLine({ ...MINE, won: 600000 })).toBe("Target reached");
  expect(goLine(MINE)).toBe("₹3 L to go · 17 days");
  expect(
    goLine({ ...MINE, needs: { ...MINE.needs!, working_days_left: 1 } }),
  ).toBe("₹3 L to go · 1 day");
  expect(chainLine({ ...MINE.needs!, wins: 1 })).toBe(
    "≈ 1 win → 9 meetings → 30 interested → 300 calls · 18 a day",
  );
  // Without the team's working days: the month's days left, today included.
  const october20 = new Date("2026-10-20T06:00:00Z");
  expect(daysLeft("2026-10-01", october20)).toBe(12);
  expect(daysLeft("2026-09-01", october20)).toBe(0);
  expect(daysLeft("2026-11-01", october20)).toBe(30);
  expect([inr(45000), inr(500000), inr(1250000), inr(12000000)]).toEqual([
    "₹45,000",
    "₹5 L",
    "₹12.5 L",
    "₹1.2 Cr",
  ]);
});

// Competitor teardown #27 (1 Nov 2026): a Monday line with the week's pace.
it("says the week's pace on a Monday, and nothing on other days", () => {
  const monday = new Date("2026-11-09T05:00:00Z"); // Monday 9 Nov, India time
  const month = { ...MINE, month: "2026-11-01", won: 110000, month_gone: 0.3 };
  expect(paceLine(month, monday)).toBe("Week 2: ₹1.1 L of ₹1.5 L pace");
  expect(paceLine(month, new Date("2026-11-10T05:00:00Z"))).toBeNull();
  expect(paceLine({ ...month, won: 500000 }, monday)).toBeNull();
  expect(paceLine({ ...month, target: null }, monday)).toBeNull();
});
