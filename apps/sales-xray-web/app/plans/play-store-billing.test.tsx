// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Inside the Google Play app: consumption only (purchase-policy.tsx).
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/plans",
}));
vi.mock("../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("../purchase-policy", async (original) => {
  const actual = await original<typeof import("../purchase-policy")>();
  return {
    ...actual,
    usePurchasesAllowed: () => false,
    PurchaseGate: ({ fallback }: { fallback: ReactNode }) => <>{fallback}</>,
  };
});

import { PlanAndBillingPane } from "../account-settings";
import { PLANS_ON_WEB } from "../purchase-policy";
import {
  fixtureBilling,
  fixtureProviderReports,
  resetFixtureBilling,
} from "../review-fixture/plans/fixture-billing";
import PlansPage from "./page";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  resetFixtureBilling();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404 })),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const BUYING = /₹|price|top up|upgrade|choose a plan|view all plans|buy/i;

it("Settings shows the plan, renewal date and minutes, never prices, top-ups or plan links", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "fictional-subscription",
  );
  fixtureProviderReports(checkout.order.orderId, "paid");
  const subs = await fixtureBilling.readSubscriptions("personal");
  expect(subs.current).not.toBeNull();
  await act(async () =>
    root.render(
      <PlanAndBillingPane
        subs={subs}
        status="ready"
        documents={[]}
        allowance={{
          state: "ready",
          value: {
            allowance_seconds: 48000,
            committed_seconds: 0,
            available_seconds: 48000,
          },
        }}
        onRetry={() => {}}
      />,
    ),
  );
  const text = host.textContent ?? "";
  expect(text).toContain("Personal");
  expect(text).toContain(PLANS_ON_WEB);
  expect(text).not.toMatch(BUYING);
  expect(text).not.toContain("Invoices");
  expect(host.querySelector('a[href="/plans"], a[href="/pricing"]')).toBeNull();
});

it("/plans explains that plans are managed on the web, with no checkout", async () => {
  await act(async () => root.render(<PlansPage />));
  const text = host.textContent ?? "";
  expect(text).toContain(PLANS_ON_WEB);
  expect(text).not.toMatch(BUYING);
  expect(host.querySelector('a[href="/settings/plan"]')).not.toBeNull();
  expect(
    [...host.querySelectorAll("button")].some((button) =>
      /^Get /.test(button.textContent ?? ""),
    ),
  ).toBe(false);
});
