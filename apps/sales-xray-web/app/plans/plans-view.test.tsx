// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { BillingError, type BillingClient } from "../billing/billing-api";
import { parsePlans } from "../billing/contract";
import {
  FIXTURE_PLANS,
  fixtureBilling,
  fixtureProviderReports,
  resetFixtureBilling,
} from "../review-fixture/plans/fixture-billing";
import { WorkspaceAccessContext } from "../workspace-access";
import { OrderReturn } from "./order-return";
import { PlansView } from "./plans-view";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push,
    replace: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/plans",
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("../dashboard/dashboard-data", () => ({
  readAllowance: async () => ({
    allowance_seconds: 6000,
    committed_seconds: 2280,
    available_seconds: 3720,
  }),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  resetFixtureBilling();
  push.mockClear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const access = (authenticated: boolean) => ({
  status: "ready" as const,
  authenticated,
  context: authenticated
    ? { personId: "p-1", sessionId: "s-1", tenantId: "t-me" }
    : null,
  retry: () => {},
});

async function render(node: ReactNode, authenticated = true) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access(authenticated)}>
        {node}
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await settle();
}

const notDeployed = () => Promise.reject(new BillingError(404, null, null));
/** A server where no billing route exists yet, apart from the catalogue. */
const comingSoon: BillingClient = {
  readPlans: async () =>
    parsePlans({
      plans: FIXTURE_PLANS.plans.map((plan) => ({
        ...plan,
        status: "coming_soon",
        prices: null,
        top_up_packs: plan.top_up_packs.map(
          ({ key, minutes, validity_rule }) => ({
            key,
            minutes,
            validity_rule,
          }),
        ),
      })),
    }),
  readMePlan: notDeployed,
  readUsage: notDeployed,
  readSubscriptions: notDeployed,
  readOfflinePayment: notDeployed,
  checkout: () =>
    Promise.reject(new BillingError(409, "not_on_sale", "Not yet.")),
  readOrder: notDeployed,
  verifyOrder: notDeployed,
  cancelSubscription: notDeployed,
};

const text = () => host.textContent ?? "";
const button = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) =>
      b.textContent?.trim() === label ||
      b.textContent?.trim().startsWith(`${label}save`) ||
      b.getAttribute("aria-label") === label,
  )!;
/** Lets the fictional server (250 ms a call) answer, twice over. */
const settle = async () => {
  for (let i = 0; i < 8; i += 1)
    await act(async () => new Promise((resolve) => setTimeout(resolve, 80)));
};

it("shows honest not-on-sale states with no price, and the trial from the session, before the API exists", async () => {
  await render(<PlansView client={comingSoon} />);
  expect(text()).toContain("Personal");
  expect(text()).toContain("Not on sale yet");
  expect(text()).not.toMatch(/₹/);
  expect(host.querySelector("[data-pay]")).toBeNull();
  // The trial strip came from the acquisition session fallback.
  expect(text()).toContain("62 of 100 minutes left");
  // Enterprise asks by email; nothing is invented.
  await act(async () => button("Talk to us").click());
  expect(
    host.querySelector<HTMLAnchorElement>("[data-enterprise-send]")?.href,
  ).toMatch(/^mailto:admin@authorityclosers\.com/);
});

it("prices the approved catalogue once on sale, sums seats for a team, and starts checkout", async () => {
  await render(<PlansView client={fixtureBilling} />);
  expect(text()).toContain("₹2,499");
  expect(text()).toContain("800 analysis minutes every month");
  expect(host.querySelector("[data-pay]")?.textContent).toContain("Pay ₹2,499");

  await act(async () => button("My team").click());
  await act(async () => {});
  expect(host.querySelector("[data-plan]")?.getAttribute("data-plan")).toBe(
    "organisation",
  );
  expect(host.querySelector("output")?.textContent).toBe("3");
  expect(host.querySelector("[data-pay]")?.textContent).toContain("Pay ₹5,997");
  await act(async () => button("Add a seat").click());
  expect(host.querySelector("[data-pay]")?.textContent).toContain("Pay ₹7,996");
  expect(text()).toContain("4,000 pooled minutes a month");

  await act(async () => button("Yearly").click());
  await act(async () => {});
  // Four seats a year is above the e-mandate limit: the bank asks each time.
  expect(text()).toContain("your bank will ask you to approve each renewal");

  // Pay hands off to the hosted step (a redirect in the fixture).
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  await act(async () => button("Pay ₹79,960").click());
  await settle();
  expect(assign).toHaveBeenCalledWith(
    expect.stringMatching(/^\/review-fixture\/plans\/pay\?order=fixture-/),
  );
  vi.unstubAllGlobals();
});

it("shows the plan you are on, with cancel at period end, once the provider confirmed a payment", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "k1",
  );
  fixtureProviderReports(checkout.order.orderId, "paid");
  await render(<PlansView client={fixtureBilling} />);
  expect(text()).toContain("You are on Personal");
  expect(text()).toContain("862");
  expect(text()).toContain("Top up 100 minutes · ₹299");
  await act(async () => button("Cancel renewal").click());
  await act(async () => button("Yes, stop renewal").click());
  await settle();
  await settle();
  expect(text()).toContain("Renewal is off");
  expect(
    (await fixtureBilling.readSubscriptions("personal")).current
      ?.cancelAtPeriodEnd,
  ).toBe(true);
});

it("the return page only reads: awaiting → paid when the provider reports, failed says no money was taken", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "k2",
  );
  await render(
    <OrderReturn
      orderId={checkout.order.orderId}
      client={fixtureBilling}
      plansHref="/review-fixture/plans"
    />,
  );
  expect(text()).toContain("Confirming your payment");
  fixtureProviderReports(checkout.order.orderId, "paid");
  // The page polls every 3 s.
  for (let i = 0; i < 45; i += 1)
    await act(async () => new Promise((resolve) => setTimeout(resolve, 80)));
  expect(text()).toContain("Your minutes are ready");
  expect(text()).toContain("₹2,499");

  await act(async () => root.unmount());
  root = createRoot(host);
  const failed = await fixtureBilling.checkout(
    {
      kind: "top_up",
      account: "personal",
      planKey: "personal",
      packKey: "personal_100",
    },
    "k3",
  );
  fixtureProviderReports(failed.order.orderId, "failed");
  await render(
    <OrderReturn orderId={failed.order.orderId} client={fixtureBilling} />,
  );
  expect(text()).toContain("Payment did not go through");
  expect(text()).toContain("No money was taken");
}, 15_000);

it("asks a signed-out visitor to sign in instead of paying", async () => {
  await render(<PlansView client={fixtureBilling} />, false);
  expect(host.querySelector("[data-pay]")?.textContent).toContain(
    "Sign in to pay",
  );
  await act(async () => button("Sign in to pay").click());
  expect(push).toHaveBeenCalledWith("/login");
});
