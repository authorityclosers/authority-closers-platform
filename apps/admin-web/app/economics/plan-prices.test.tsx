// @vitest-environment happy-dom
/**
 * Plan prices in Admin (owner, 29 Oct 2026: "Admin price editor"): only the owner changes a
 * price, after a confirm step that shows old and new; nothing is saved before the confirm.
 */
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { PlanPricesPanel, normalizePlanPrices } from "./plan-prices";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;

const plan = (key: string, name: string, extra: Record<string, unknown>) => ({
  key,
  name,
  status: "active",
  revision: 3,
  per_seat: false,
  prices_include_gst: false,
  monthly_price_paise: 249_900,
  yearly_price_paise: 2_699_000,
  editable: true,
  ...extra,
});
const prices = (owner: boolean) => ({
  environment: "development",
  can_change: owner,
  plans: [
    plan("personal", "Personal", { prices_include_gst: true }),
    plan("organisation", "Organisation", {
      per_seat: true,
      monthly_price_paise: 1_000_000,
      yearly_price_paise: 10_800_000,
    }),
    plan("enterprise", "Enterprise", {
      status: "coming_soon",
      revision: 2,
      per_seat: true,
      monthly_price_paise: 1_000_000,
      yearly_price_paise: 10_800_000,
    }),
  ],
  history: [
    {
      plan_key: "personal",
      plan_revision: 3,
      monthly_price_paise: 249_900,
      yearly_price_paise: 2_699_000,
      previous_monthly_price_paise: 299_900,
      previous_yearly_price_paise: 2_999_000,
      reason: "Fictional earlier change",
      changed_by: "owner@example.test",
      changed_at: "2026-10-29T06:00:00+00:00",
    },
  ],
});

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  refresh.mockClear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const button = (label: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(label),
  );
const changeButtons = () =>
  [...host.querySelectorAll("button")].filter(
    (item) => item.textContent === "Change price",
  );
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
const render = async (owner: boolean) => {
  await act(async () =>
    root.render(
      createElement(PlanPricesPanel, {
        prices: normalizePlanPrices(prices(owner)),
      }),
    ),
  );
};

it("lets the owner set the Organisation seat price after confirming old and new", async () => {
  const sent: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      sent.push({ url, init });
      return new Response(JSON.stringify(prices(true)), { status: 200 });
    }),
  );
  await render(true);
  expect(host.textContent).toContain("What Dev sells at now");
  expect(host.textContent).toContain("Organisation per seat + GST");
  expect(host.textContent).toContain("₹10,000");
  expect(changeButtons()).toHaveLength(3);

  await act(async () => changeButtons()[1]!.click());
  expect(button("Review change")!.disabled).toBe(true); // nothing changed yet
  await type("Organisation price a month in INR", "1999");
  await type("Organisation price a year in INR", "19990");
  expect(button("Review change")!.disabled).toBe(true); // no reason yet
  await type(
    "Reason for the Organisation price change",
    "Owner approved ₹1,999 per seat",
  );
  await act(async () => button("Review change")!.click());
  expect(host.textContent).toContain("A month ₹10,000 → ₹1,999 per seat + GST");
  expect(host.textContent).toContain(
    "A year ₹1,08,000 → ₹19,990 per seat + GST",
  );
  expect(host.textContent).toContain("Orders already placed keep theirs.");
  expect(sent).toEqual([]); // nothing is saved before the confirm

  await act(async () => button("Confirm change")!.click());
  expect(sent).toHaveLength(1);
  expect(sent[0]!.url).toBe("/v1/admin/plan-prices/organisation");
  expect(sent[0]!.init.method).toBe("PUT");
  expect(JSON.parse(sent[0]!.init.body as string)).toEqual({
    expected_revision: 3,
    monthly_price_paise: 199_900,
    yearly_price_paise: 1_999_000,
    reason: "Owner approved ₹1,999 per seat",
  });
  expect(refresh).toHaveBeenCalledOnce();
});

it("refuses paise, zero and blanks, and says when the plan changed meanwhile", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "changed" }), { status: 409 }),
    ),
  );
  await render(true);
  await act(async () => changeButtons()[1]!.click());
  await type("Reason for the Organisation price change", "Fictional");
  for (const bad of ["1999.50", "0", ""]) {
    await type("Organisation price a month in INR", bad);
    expect(button("Review change")!.disabled).toBe(true);
  }
  await type("Organisation price a month in INR", "1999");
  await act(async () => button("Review change")!.click());
  await act(async () => button("Confirm change")!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "This plan changed. Refresh before trying again.",
  );
  expect(refresh).not.toHaveBeenCalled();
});

it("shows Admins the prices and history read-only; only the owner changes them", async () => {
  await render(false);
  expect(changeButtons()).toHaveLength(0);
  expect(host.textContent).toContain("Owner only");
  expect(host.textContent).toContain("Only the owner changes plan prices.");
  expect(host.textContent).toContain(
    "Personal revision 3: a month ₹2,999 → ₹2,499, a year ₹29,990 → ₹26,990",
  );
});

it("never crashes on a partial answer", () => {
  expect(normalizePlanPrices({})).toEqual({
    environment: "this environment",
    can_change: false,
    plans: [],
    history: [],
  });
  const odd = normalizePlanPrices({
    ...prices(true),
    plans: [{ key: "broken" }, ...prices(true).plans],
  });
  expect(odd.plans.map((row) => row.key)).toEqual([
    "personal",
    "organisation",
    "enterprise",
  ]);
});
