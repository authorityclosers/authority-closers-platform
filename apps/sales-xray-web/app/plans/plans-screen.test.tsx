// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  BillingError,
  liveBilling,
  type BillingClient,
} from "../billing/billing-api";
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
import { AnimatedCountUp } from "./animated-count-up";
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
  account: "personal" | "organisation" = "personal",
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
          workspaces: [
            {
              tenant_id: tenantId,
              kind: account,
              name: "Fictional workspace",
              role: "owner",
              sales_xray_enabled: true,
            },
          ],
        }}
      >
        {node}
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
const click = async (label: string) => act(async () => button(label).click());
async function fill(label: string, value: string) {
  const input = [...host.querySelectorAll("label")]
    .find((node) => node.textContent?.includes(label))!
    .querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

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
  await click("Review total");
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
  await click("Review total");
  expect(notify).toHaveBeenCalled();
  await click("Review total");
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
  await fill("Organisation name", "Fictional Closers");
  await fill("GSTIN", "27abcde1234f1z5");
  await click("Review total");
  await until(() => text().includes("Total confirmed"));
  expect(checkout.mock.calls[0][0]).toEqual({
    kind: "subscription",
    account: "organisation",
    planKey: "organisation",
    interval: "year",
    seats: 2,
    buyer: { name: "Fictional Closers", gstin: "27ABCDE1234F1Z5" },
  });
  expect(text()).toContain("₹2,16,000");
  expect(text()).toContain("₹38,880");
  expect(text()).toContain("₹2,54,880");
  expect(text()).toContain("approve each renewal above ₹15,000");
  await fill("Organisation name", "Renamed Fictional Closers");
  expect(text()).not.toContain("Total confirmed");
  await click("Review total");
  await until(
    () =>
      checkout.mock.calls.length === 2 && text().includes("Total confirmed"),
  );
  expect(
    checkout.mock.calls[1][0].kind === "subscription" &&
      checkout.mock.calls[1][0].buyer?.name,
  ).toBe("Renamed Fictional Closers");
  expect(checkout.mock.calls[1][1]).not.toBe(checkout.mock.calls[0][1]);
  expect(openHostedCheckout).not.toHaveBeenCalled();
});

it("requires an enterprise name and allows an omitted GSTIN", async () => {
  const checkout = vi.fn(fixtureBilling.checkout);
  await render(<PlansPurchase client={{ ...fixtureBilling, checkout }} />);
  await click("Get Enterprise");
  await click("Review total");
  expect(checkout).not.toHaveBeenCalled();
  await fill("Organisation name", "Fictional Enterprise");
  await click("Review total");
  await until(() => text().includes("Total confirmed"));
  expect(checkout.mock.calls[0][0]).toMatchObject({
    planKey: "enterprise",
    seats: 50,
    buyer: { name: "Fictional Enterprise", gstin: null },
  });
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
  expect(text()).not.toMatch(/credits/i);
  expect(host.querySelector('span[aria-live="polite"]')?.textContent).toBe(
    "+800 analysis minutes",
  );
  expect(verifyOrder).toHaveBeenCalled();
  fixtureProviderReports(checkout.order.orderId, "paid");
  expect((await fixtureBilling.readUsage()).allowance.availableSeconds).toBe(
    862 * 60,
  );
});

it("keeps the final announcement stable while the visible minutes animate", async () => {
  let frame!: FrameRequestCallback;
  const animation = vi
    .spyOn(globalThis, "requestAnimationFrame")
    .mockImplementation((callback) => {
      frame = callback;
      return 1;
    });
  const cancel = vi.spyOn(globalThis, "cancelAnimationFrame");
  try {
    await render(<AnimatedCountUp targetMinutes={800} />);
    const announcement = host.querySelector('[aria-live="polite"]')!;
    const animated = host.querySelector('[aria-hidden="true"]')!;
    expect(announcement.textContent).toBe("+800 analysis minutes");
    await act(async () => frame(100));
    expect(animated.textContent).toContain("+0");
    await act(async () => frame(700));
    expect(animated.textContent).toContain("+700");
    expect(announcement.textContent).toBe("+800 analysis minutes");
  } finally {
    await act(async () => root.render(null));
    animation.mockRestore();
    cancel.mockRestore();
  }
});

function AccountBilling({ client }: { client: BillingClient }) {
  return <BillingView {...useBillingAccount(true, client)} />;
}
it("loads billing usage and invoices, and cancels renewal at period end", async () => {
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
  expect(text()).toContain("Invoices & Receipts");
  expect(text()).toContain("FIXTURE-1");
  expect(host.querySelector("a[download]")?.getAttribute("href")).toMatch(
    /^data:application\/octet-stream/,
  );
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
  expect(text()).not.toContain("FIXTURE-1");
});

it("keeps invoices scoped to the workspace account and reports failed reads", async () => {
  const checkout = await fixtureBilling.checkout(
    {
      kind: "subscription",
      account: "organisation",
      planKey: "organisation",
      interval: "month",
      seats: 2,
      buyer: { name: "Fictional Closers", gstin: null },
    },
    "fictional",
  );
  fixtureProviderReports(checkout.order.orderId, "paid");
  const readInvoices = vi.fn(fixtureBilling.readInvoices);
  const client = { ...fixtureBilling, readInvoices };
  await render(<AccountBilling client={client} />);
  await until(() => text().includes("No invoices or receipts yet"));
  expect(readInvoices).toHaveBeenLastCalledWith(
    "personal",
    expect.any(AbortSignal),
  );
  await render(
    <AccountBilling client={client} />,
    true,
    "org-workspace",
    "organisation",
  );
  expect(text()).not.toContain("FIXTURE-1");
  await until(() => text().includes("FIXTURE-1"));
  expect(readInvoices).toHaveBeenLastCalledWith(
    "organisation",
    expect.any(AbortSignal),
  );
  await render(
    <AccountBilling
      client={{
        ...fixtureBilling,
        readInvoices: async () => {
          throw new Error("unavailable");
        },
      }}
    />,
    true,
    "other-workspace",
  );
  await until(() =>
    text().includes("Invoices and receipts are currently unavailable"),
  );
  expect(text()).not.toContain("No invoices or receipts yet");
});

it("keeps plan, usage, subscription facts and checkout usable while invoices load or fail", async () => {
  const rejectInvoices: Array<(error: Error) => void> = [];
  const checkout = vi.fn(fixtureBilling.checkout);
  const client = {
    ...fixtureBilling,
    checkout,
    readInvoices: () =>
      new Promise<never>((_resolve, reject) => rejectInvoices.push(reject)),
  };
  await render(
    <>
      <PlansPurchase client={client} />
      <AccountBilling client={client} />
    </>,
  );
  await until(
    () => text().includes("Current: Trial") && text().includes("62 min left"),
  );
  expect(text()).toContain("No renewal scheduled");
  expect(text()).toContain("Loading invoices");
  expect(text()).not.toContain("No invoices or receipts yet");
  await click("Get Personal");
  await click("Review total");
  await until(() => text().includes("Total confirmed"));
  await act(async () =>
    rejectInvoices.forEach((reject) => reject(new Error("invoice outage"))),
  );
  await until(() =>
    text().includes("Invoices and receipts are currently unavailable"),
  );
  expect(text()).toContain("Current: Trial");
  expect(text()).toContain("62 min left");
  expect(text()).toContain("No renewal scheduled");
  expect(text()).not.toContain("Billing details could not be loaded");
  await click("Pay ₹2,499 with Razorpay");
  expect(checkout).toHaveBeenCalledOnce();
  expect(openHostedCheckout).toHaveBeenCalledOnce();
});

it("shows an empty invoice section on the first organisation visit when the API returns 404", async () => {
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response("", { status: 404 }));
  try {
    await render(
      <AccountBilling
        client={{ ...fixtureBilling, readInvoices: liveBilling.readInvoices }}
      />,
      true,
      "new-org",
      "organisation",
    );
    await until(
      () =>
        text().includes("No invoices or receipts yet") &&
        text().includes("62 min left"),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/v1/invoices?account=organisation",
      expect.any(Object),
    );
    expect(text()).not.toContain(
      "Invoices and receipts are currently unavailable",
    );
    expect(text()).not.toContain("Billing details could not be loaded");
  } finally {
    fetch.mockRestore();
  }
});
