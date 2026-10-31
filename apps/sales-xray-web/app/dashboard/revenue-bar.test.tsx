// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RevenueBar, takesLine, toneOf } from "./revenue-bar";
import type { Revenue } from "./revenue-client";
import { inr } from "./revenue-client";

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
  expect(text).toContain("₹2 L");
  expect(text).toContain("of ₹5 L · October");
  expect(text).toContain("40%");
  expect(text).toContain("About 18 calls a day to get there");
  expect(text).toContain("estimate");
  expect(text).toContain("1 won without an amount");
  const tick = container.querySelector<HTMLElement>('[aria-hidden="true"]');
  expect(tick?.style.left).toBe("60%");
  // Behind the month: 40% won with 60% of it gone.
  expect(container.querySelector("section")?.dataset.tone).toBe("behind");
});

it("shows nothing without a target, and never a box while it loads", async () => {
  serve({ ...MINE, target: null, needs: null });
  await act(async () => root.render(<RevenueBar scope="mine" />));
  expect(container.innerHTML).toBe("");
  await settle();
  expect(container.innerHTML).toBe("");
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
  expect(bar?.textContent).toContain("Each seller");
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
  expect(takesLine({ ...MINE, won: 600000 })).toBe("Target reached");
  expect(takesLine({ ...MINE, needs: null })).toBeNull();
  expect(
    takesLine({
      ...MINE,
      needs: { ...MINE.needs!, calls_per_day: 1 },
    }),
  ).toBe("About 1 call a day to get there");
  expect([inr(45000), inr(500000), inr(1250000), inr(12000000)]).toEqual([
    "₹45,000",
    "₹5 L",
    "₹12.5 L",
    "₹1.2 Cr",
  ]);
});
