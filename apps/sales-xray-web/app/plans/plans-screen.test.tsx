// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BillingError, type BillingClient } from "../billing/billing-api";
import { BillingView } from "../billing/billing-view";
import { useBillingAccount } from "../billing/use-billing-account";
import { notify } from "../notice-center";
import {
  fixtureBilling,
  fixtureProviderReports,
  FIXTURE_PLANS,
  resetFixtureBilling,
} from "../review-fixture/plans/fixture-billing";
import { parsePlans } from "../billing/contract";
import { WorkspaceAccessContext } from "../workspace-access";
import { openHostedCheckout } from "./hosted-checkout";
import { OrderReturn } from "./order-return";
import { PlansPurchase } from "./plans-purchase";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
vi.mock("./hosted-checkout", () => ({
  openHostedCheckout: vi.fn(async () => "dismissed"),
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
  vi.clearAllMocks();
  HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const text = () => host.textContent ?? "";
const button = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) =>
      b.textContent?.trim() === label || b.getAttribute("aria-label") === label,
  )!;
async function until(check: () => boolean) {
  for (let i = 0; i < 150 && !check(); i++)
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
  expect(check()).toBe(true);
}
async function render(
  node: ReactNode,
  authenticated = true,
  tenantId = "fixture-workspace",
) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated,
          context: authenticated
            ? {
                personId: "fixture-person",
                sessionId: "fixture-session",
                tenantId,
              }
            : null,
          retry: () => {},
        }}
      >
        {node}
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
const click = async (label: string) => act(async () => button(label).click());

it("uses live on-sale prices, retains the display fallback and signs in before checkout", async () => {
  const checkout = vi.fn(fixtureBilling.checkout);
  await render(
    <PlansPurchase
      client={{
        ...fixtureBilling,
        checkout,
        readPlans: async () =>
          parsePlans({
            plans: FIXTURE_PLANS.plans.map((p) => ({
              ...p,
              status: "coming_soon",
              prices: null,
            })),
          }),
      }}
    />,
    false,
  );
  expect(text()).toContain("₹2,499");
  expect(text()).not.toContain("Coming soon");
  await click("Get Personal");
  expect(text()).toContain("Subtotal (1 seat)");
  await click("Review total with Razorpay");
  expect(checkout).not.toHaveBeenCalled();
  expect(push).toHaveBeenCalledWith("/login?returnTo=%2Fplans");
  await render(
    <PlansPurchase
      client={{
        ...fixtureBilling,
        readPlans: async () =>
          parsePlans({
            plans: [
              {
                ...FIXTURE_PLANS.plans[0],
                prices: {
                  ...FIXTURE_PLANS.plans[0].prices,
                  monthly_paise: 250000,
                },
              },
            ],
          }),
      }}
    />,
  );
  await until(() => text().includes("₹2,500"));
});

it("reuses a failed checkout key, shows server tax before payment and handles SDK dismissal without granting minutes", async () => {
  const checkout = vi
    .fn(fixtureBilling.checkout)
    .mockRejectedValueOnce(new Error("network"));
  await render(<PlansPurchase client={{ ...fixtureBilling, checkout }} />);
  await click("Get Personal");
  await click("Review total with Razorpay");
  expect(notify).toHaveBeenCalled();
  await click("Review total with Razorpay");
  await until(() => text().includes("Total confirmed"));
  expect(checkout.mock.calls[0][1]).toBe(checkout.mock.calls[1][1]);
  expect(text()).toContain("Taxable value");
  expect(text()).toContain("₹2,117.80");
  expect(text()).toContain("₹381.20 included");
  expect(openHostedCheckout).not.toHaveBeenCalled();
  await click("Pay ₹2,499 with Razorpay");
  expect(openHostedCheckout).toHaveBeenCalledOnce();
  expect(checkout).toHaveBeenCalledTimes(2);
  expect(push).toHaveBeenCalledWith(
    expect.stringMatching(/^\/account\/billing\/return\?order=/),
  );
  expect((await fixtureBilling.readUsage()).allowance.availableSeconds).toBe(
    62 * 60,
  );
  expect(text()).not.toContain("Payment successful");
});

it("prices two team seats yearly, accepts the server total and warns about renewal approval", async () => {
  const checkout = vi.fn(fixtureBilling.checkout);
  await render(<PlansPurchase client={{ ...fixtureBilling, checkout }} />);
  await until(() => text().includes("Current: Trial"));
  await click("Get Organisation");
  expect(text()).toContain("Subtotal (2 seats)");
  const yearly = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.startsWith("Yearly"),
  )!;
  await act(async () => yearly.click());
  await click("Review total with Razorpay");
  await until(() => text().includes("Total confirmed"));
  expect(checkout.mock.calls[0][0]).toEqual({
    kind: "subscription",
    account: "organisation",
    planKey: "organisation",
    interval: "year",
    seats: 2,
  });
  expect(text()).toContain("₹2,16,000");
  expect(text()).toContain("₹38,880");
  expect(text()).toContain("₹2,54,880");
  expect(text()).toContain("approve each renewal above ₹15,000");
});

it("return verification shows minutes and the canonical new balance, with no duplicate grant on reload", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "fictional",
  );
  const verifyOrder = vi.fn(fixtureBilling.verifyOrder);
  const client = { ...fixtureBilling, verifyOrder };
  await render(
    <OrderReturn orderId={checkout.order.orderId} client={client} />,
  );
  await until(() => text().includes("Confirming your payment"));
  expect(text()).not.toContain("Payment confirmed");
  fixtureProviderReports(checkout.order.orderId, "paid");
  await render(
    <OrderReturn
      key="returned"
      orderId={checkout.order.orderId}
      client={client}
    />,
  );
  await until(() => text().includes("862 analysis minutes"));
  expect(text()).toContain("Order minutes800");
  expect(verifyOrder).toHaveBeenCalled();
  fixtureProviderReports(checkout.order.orderId, "paid");
  expect((await fixtureBilling.readUsage()).allowance.availableSeconds).toBe(
    862 * 60,
  );
});

function AccountBilling({ client }: { client: BillingClient }) {
  return <BillingView {...useBillingAccount(true, client)} />;
}
it("loads billing usage, hides undeployed invoices, and cancels renewal at period end", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "personal",
      planKey: "personal",
      interval: "month",
      seats: 1,
    },
    "fictional",
  );
  fixtureProviderReports(checkout.order.orderId, "paid");
  const cancelSubscription = vi
    .fn(fixtureBilling.cancelSubscription)
    .mockRejectedValueOnce(new BillingError(503, "unavailable", "Try again"));
  const client = { ...fixtureBilling, cancelSubscription };
  await render(<AccountBilling client={client} />);
  await until(() => text().includes("862 min left"));
  expect(text()).not.toContain("Invoices & Receipts");
  await click("Cancel renewal");
  await click("Yes, cancel renewal");
  expect(text()).toContain("Try again");
  await click("Yes, cancel renewal");
  await until(() => text().includes("Cancels at period end"));
  expect(cancelSubscription.mock.calls[0][2]).toBe(
    cancelSubscription.mock.calls[1][2],
  );
  expect((await fixtureBilling.readMePlan()).allowance.availableSeconds).toBe(
    862 * 60,
  );
  await render(
    <AccountBilling
      client={{ ...fixtureBilling, readMePlan: () => new Promise(() => {}) }}
    />,
    true,
    "different-workspace",
  );
  expect(text()).not.toContain("862 min left");
});
