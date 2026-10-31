// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { RevenueBreakdown } from "../dashboard/revenue-client";
import { RevenueSplit } from "./revenue-split";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SPLIT: RevenueBreakdown = {
  days: 30,
  currency: "INR",
  won: 650000,
  deals: 4,
  amount_not_set: 1,
  by_seller: [
    { key: "a", label: "Asha Fictional", won: 400000, deals: 3 },
    { key: "b", label: "Ravi Fictional", won: 250000, deals: 1 },
  ],
  by_side: [
    { key: "inbound", label: "Inbound", won: 500000, deals: 3 },
    { key: "cold", label: "Cold", won: 150000, deals: 1 },
  ],
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

async function show(body: RevenueBreakdown) {
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
  await act(async () => root.render(<RevenueSplit days={30} />));
  for (let i = 0; i < 6; i++)
    await act(async () => await new Promise((done) => setTimeout(done, 0)));
  return asked;
}

it("splits the period's revenue by Inbound or Cold and by seller", async () => {
  const asked = await show(SPLIT);
  expect(asked[0]).toContain("/revenue/breakdown?days=30");
  const text = container.textContent ?? "";
  expect(text).toContain("₹6.5 L won · 4 deals");
  expect(text).toContain("1 without an amount");
  expect(text).toContain("Inbound₹5 L");
  expect(text).toContain("Cold₹1.5 L");
  expect(text).toContain("Asha Fictional");
});

it("stays out of the way with nothing won", async () => {
  await show({ ...SPLIT, won: 0, deals: 0, amount_not_set: 0 });
  expect(container.innerHTML).toBe("");
});
