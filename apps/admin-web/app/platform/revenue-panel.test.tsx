// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RevenuePanel } from "./revenue-panel";
import type { Revenue } from "./revenue-api";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const windows = (collected: number, refunded: number) =>
  (["today", "last_7_days", "this_month", "all_time"] as const).map(
    (key, index) => ({
      key,
      starts_at: key === "all_time" ? null : "2026-10-22T18:30:00Z",
      collected_minor: collected * (index + 1),
      taxable_minor: Math.round((collected * (index + 1)) / 1.18),
      gst_minor:
        collected * (index + 1) - Math.round((collected * (index + 1)) / 1.18),
      refunded_minor: refunded,
      net_minor: collected * (index + 1) - refunded,
      payments: index + 1,
      refunds: refunded ? 1 : 0,
    }),
  );

function fixture(mode: "live" | "test"): Revenue {
  return {
    generated_at: "2026-10-23T06:00:00Z",
    mode,
    currency: "INR",
    windows: windows(mode === "live" ? 249900 : 2360000, 29900),
    by_plan: [
      {
        plan_key: "organisation",
        plan_name: "Organisation",
        kind: "subscription",
        collected_minor: 2360000,
        taxable_minor: 2000000,
        payments: 1,
      },
      {
        plan_key: "personal",
        plan_name: "Personal",
        kind: "top_up",
        collected_minor: 29900,
        taxable_minor: 25339,
        payments: 1,
      },
    ],
    recurring: [
      {
        plan_key: "organisation",
        plan_name: "Organisation",
        interval: "year",
        subscriptions: 1,
        seats: 3,
        monthly_taxable_minor: 2700000,
      },
    ],
    active_subscriptions: 2,
    cancelling_subscriptions: 1,
    monthly_recurring_taxable_minor: 2700000,
    paying_accounts: 2,
    personal_accounts: 1,
    organisation_accounts: 1,
  };
}

let container: HTMLDivElement, root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const text = () => container.textContent ?? "";
function button(label: string) {
  const found = [...container.querySelectorAll("button")].find(
    (element) => element.textContent?.trim() === label,
  );
  if (!found) throw new Error("missing button " + label);
  return found;
}
async function settle() {
  for (let i = 0; i < 5; i++) await act(async () => {});
}

it("shows live revenue for this month, then switches period and mode", async () => {
  const fetcher = vi.fn(async (url: string) =>
    Response.json(fixture(url.endsWith("mode=test") ? "test" : "live")),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<RevenuePanel />));
  await settle();
  expect(fetcher.mock.calls[0][0]).toBe(
    "/v1/platform/billing/revenue?mode=live",
  );
  expect(text()).toContain("Revenue");
  expect(text()).toContain("₹7,497"); // this month: 3 × ₹2,499
  expect(text()).toContain("₹299 refunded");
  expect(text()).toContain("₹27,000"); // monthly recurring, before GST
  expect(text()).toContain("1 cancelling at period end");
  expect(text()).toContain("1 personal · 1 organisations");
  expect(text()).toContain("Personal top-ups");
  expect(text()).not.toContain("Never real money");

  await act(async () => button("All time").click());
  expect(text()).toContain("₹9,996"); // all time: 4 × ₹2,499

  await act(async () => button("Test").click());
  await settle();
  expect(fetcher.mock.calls.at(-1)?.[0]).toBe(
    "/v1/platform/billing/revenue?mode=test",
  );
  expect(text()).toContain("Never real money");
  expect(text()).toContain("₹94,400"); // all time in test: 4 × ₹23,600
});

it("explains a denied read without showing figures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 403 })),
  );
  await act(async () => root.render(<RevenuePanel />));
  await settle();
  expect(text()).toContain("billing assignment could not be confirmed");
  expect(text()).not.toContain("Collected");
});

it("refuses a response for the other mode", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(fixture("test"))),
  );
  await act(async () => root.render(<RevenuePanel />));
  await settle();
  expect(text()).toContain("Revenue could not be loaded");
});
