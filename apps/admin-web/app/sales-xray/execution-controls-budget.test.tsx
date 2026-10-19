// @vitest-environment happy-dom
/**
 * One-click budget raises and the owner's budget settings: ceiling and period
 * (owner via the orchestrator, 19 Oct 2026).
 */
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ExecutionControlsPanel } from "./execution-controls";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const control = { revision: 0, paused: false, changed_at: null };
// Above the old ₹10,000 limit: a ₹15,000 cap under a ₹17,000 ceiling.
const account = (cap: number) => ({
  cap_paise: cap,
  available_paise: cap - 1_350_000,
  committed_paise: 1_350_000,
  settled_paise: 1_300_000,
  held_paise: 50_000,
  uncertain_paise: 50_000,
  reservation_count: 40,
  warning: "critical",
  warning_percent: 80,
  critical_percent: 90,
});
const PERIODS = [
  { value: "lifetime", help: "One running total that never resets." },
  {
    value: "monthly",
    help: "The cap is the allowance for each calendar month.",
  },
  { value: "daily", help: "The cap is the allowance for each day." },
];
const settings = (owner: boolean, cap: number) => ({
  revision: 0,
  ceiling_paise: 1_700_000,
  sealed_ceiling_paise: 1_700_000,
  from_release: true,
  period: "lifetime",
  cap_paise: cap,
  lifetime_committed_paise: 1_350_000,
  period_starts_at: null,
  period_ends_at: null,
  can_change_ceiling: owner,
  periods: PERIODS,
  history: [],
});
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const button = (label: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(label),
  )!;
async function type(label: string, value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>(
      `input[aria-label="${label}"]`,
    )!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function server(posts: { url: string; body: unknown }[], owner = false) {
  let cap = 1_500_000;
  const budget = () => ({
    scope_id: "11111111-1111-4111-8111-111111111111",
    revision: 0,
    approved_cap_paise: 1_700_000,
    budget: account(cap),
    settings: settings(owner, cap),
  });
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    if (init.method === "POST") {
      const body = JSON.parse(init.body as string) as Record<string, unknown>;
      posts.push({ url, body });
      if (url === "/v1/admin/conversation/budget")
        cap = body.new_cap_paise as number;
      return json({ ...budget(), revision: 1 }, 201);
    }
    if (url === "/v1/admin/conversation/budget") return json(budget());
    return json({
      environment: "development",
      control,
      budget: account(cap),
      waiting_calls: 2,
      history: [],
    });
  });
}

it("raises the cap in one click, up to the ceiling, and says calls are waiting", async () => {
  const posts: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", server(posts));
  await act(async () => root.render(createElement(ExecutionControlsPanel)));
  expect(host.textContent).toContain("90% used");
  expect(host.textContent).toContain("ceiling ₹17,000");
  expect(host.textContent).toContain("2 calls are waiting for AI budget");
  // +₹5,000 would pass the ₹17,000 ceiling, so only that button is off.
  expect(button("+₹1,000").disabled).toBe(false);
  expect(button("+₹5,000").disabled).toBe(true);
  expect(button("+₹5,000").title).toBe(
    "Above the ceiling: the owner can raise it in Budget settings",
  );
  await act(async () => button("+₹1,000").click());
  expect(posts[0]).toEqual({
    url: "/v1/admin/conversation/budget",
    body: {
      expected_revision: 0,
      new_cap_paise: 1_600_000,
      reason: "Raised by ₹1,000 from Execution & budget",
    },
  });
  expect(host.textContent).toContain("Raised the budget to ₹16,000");
  expect(host.textContent).not.toContain("Ask Root");
});

it("shows the ceiling and period read-only to an Admin who is not the owner", async () => {
  vi.stubGlobal("fetch", server([]));
  await act(async () => root.render(createElement(ExecutionControlsPanel)));
  expect(host.textContent).toContain("Budget settings");
  expect(host.textContent).toContain(
    "Ceiling ₹17,000 · Lifetime: cap ₹15,000 in total",
  );
  expect(host.textContent).toContain(
    "Only the owner changes the ceiling and the period.",
  );
  expect(button("Review change")).toBeUndefined();
});

it("lets the owner change the ceiling and the period after confirming old and new", async () => {
  const posts: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", server(posts, true));
  await act(async () => root.render(createElement(ExecutionControlsPanel)));
  expect(button("Review change").disabled).toBe(true); // nothing changed yet

  await type("Budget ceiling in INR", "20000");
  await act(async () => button("Monthly").click());
  expect(host.textContent).toContain(
    "The cap is the allowance for each calendar month.",
  );
  await type("Cap per month (INR)", "5000");
  expect(button("Review change").disabled).toBe(true); // no reason yet
  await type(
    "Reason for the budget settings change",
    "Owner: monthly allowance",
  );
  await act(async () => button("Review change").click());
  expect(host.textContent).toContain("Ceiling ₹17,000 → ₹20,000");
  expect(host.textContent).toContain("Period Lifetime → Monthly");
  expect(host.textContent).toContain("Cap ₹15,000 in total → ₹5,000 a month");
  expect(posts).toEqual([]); // nothing is saved before the confirm

  await act(async () => button("Confirm change").click());
  expect(posts[0]).toEqual({
    url: "/v1/admin/conversation/budget/settings",
    body: {
      expected_setting_revision: 0,
      ceiling_paise: 2_000_000,
      period: "monthly",
      cap_paise: 500_000,
      reason: "Owner: monthly allowance",
    },
  });
  expect(host.textContent).toContain("Saved. Ceiling ₹20,000");
});

it("refuses a lifetime cap below what is already spent or held", async () => {
  vi.stubGlobal("fetch", server([], true));
  await act(async () => root.render(createElement(ExecutionControlsPanel)));
  await type("Budget cap (INR)", "10000");
  await type("Reason for the budget settings change", "lower");
  expect(host.textContent).toContain(
    "₹13,500 is already spent or held in total.",
  );
  expect(button("Review change").disabled).toBe(true);
});
