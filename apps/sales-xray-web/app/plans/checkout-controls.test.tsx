// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountSettings, PlanAndBillingPane } from "../account-settings";
import { liveBilling } from "../billing/billing-api";
import { BillingView } from "../billing/billing-view";
import { useBillingAccount } from "../billing/use-billing-account";
import type { Checkout } from "../billing/contract";
import {
  fixtureBilling,
  fixtureProviderReports,
  resetFixtureBilling,
} from "../review-fixture/plans/fixture-billing";
import { WorkspaceAccessContext } from "../workspace-access";
import { openHostedCheckout } from "./hosted-checkout";
import { PlansPurchase } from "./plans-purchase";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("./hosted-checkout", () => ({
  openHostedCheckout: vi.fn(async () => "dismissed"),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const button = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) =>
      b.textContent?.trim() === label || b.getAttribute("aria-label") === label,
  )!;
const click = (label: string) => act(async () => button(label).click());
async function render(node: ReactNode, tenantId = "fictional-workspace") {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: {
            personId: "fictional-person",
            sessionId: "fictional-session",
            tenantId,
          },
          retry: () => {},
        }}
      >
        {node}
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
async function activeSubscription() {
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
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  resetFixtureBilling();
  vi.clearAllMocks();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404 })),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("shell Back and Close leave plans; drawer Close only dismisses checkout", async () => {
  await render(<PlansPurchase client={fixtureBilling} />);
  await click("Back to Sales Xray");
  await click("Close");
  expect(push.mock.calls).toEqual([["/"], ["/"]]);
  push.mockClear();
  await click("Get Personal");
  await click("Close checkout");
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(push).not.toHaveBeenCalled();
});

it("contains drawer focus, makes the background inert, and restores it on Escape", async () => {
  await render(<PlansPurchase client={fixtureBilling} />);
  const trigger = button("Get Personal");
  trigger.focus();
  await click("Get Personal");
  const panel = host.querySelector<HTMLElement>('[role="dialog"]')!;
  expect(document.activeElement).toBe(panel);
  expect(trigger.closest("[inert]")).not.toBeNull();
  const first = button("Close checkout");
  const last = button("Cancel");
  last.focus();
  await act(async () =>
    last.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(document.activeElement).toBe(first);
  await act(async () =>
    first.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(document.activeElement).toBe(last);
  await act(async () =>
    panel.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(trigger.closest("[inert]")).toBeNull();
});

it("Settings reviews the server total, retains uncertain retries, and prevents duplicate requests", async () => {
  await activeSubscription();
  let resolve!: (checkout: Checkout) => void;
  const checkout = vi
    .spyOn(liveBilling, "checkout")
    .mockRejectedValueOnce(new Error("uncertain"))
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
  await render(<AccountSettings billing={{ status: "ready" }} />);
  await click("Plan & billing");
  await click("Top up 100 min");
  await click("Review total with Razorpay");
  expect(openHostedCheckout).not.toHaveBeenCalled();
  await act(async () => {
    button("Review total with Razorpay").click();
    button("Review total with Razorpay").click();
  });
  expect(checkout).toHaveBeenCalledTimes(2);
  expect(checkout.mock.calls[0][1]).toBe(checkout.mock.calls[1][1]);
  const request = checkout.mock.calls[1][0];
  const prepared = await fixtureBilling.checkout(
    request,
    checkout.mock.calls[1][1],
  );
  await act(async () =>
    resolve({
      ...prepared,
      order: {
        ...prepared.order,
        amount: { ...prepared.order.amount, minor: 35000 },
      },
    }),
  );
  expect(host.textContent).toContain("Total confirmed");
  expect(openHostedCheckout).not.toHaveBeenCalled();
  vi.mocked(openHostedCheckout).mockRejectedValueOnce(
    new Error("provider unavailable"),
  );
  await click("Pay ₹350 with Razorpay");
  expect(push).not.toHaveBeenCalled();
  await click("Pay ₹350 with Razorpay");
  expect(checkout).toHaveBeenCalledTimes(2);
  expect(openHostedCheckout).toHaveBeenCalledTimes(2);
  expect(openHostedCheckout).toHaveBeenCalledWith(
    prepared.hosted,
    prepared.order.orderId,
  );
  expect(push).toHaveBeenCalledWith(
    expect.stringContaining(prepared.order.orderId),
  );
});

it("rejects a pending Settings top-up after workspace identity changes", async () => {
  await activeSubscription();
  let resolve!: (checkout: Checkout) => void;
  const checkout = vi.spyOn(liveBilling, "checkout").mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const screen = <AccountSettings billing={{ status: "ready" }} />;
  await render(screen);
  await click("Plan & billing");
  await click("Top up 100 min");
  await click("Review total with Razorpay");
  await render(screen, "other-fictional-workspace");
  const prepared = await fixtureBilling.checkout(
    checkout.mock.calls[0][0],
    checkout.mock.calls[0][1],
  );
  await act(async () => resolve(prepared));
  expect(host.textContent).not.toContain("Total confirmed");
  expect(openHostedCheckout).not.toHaveBeenCalled();
  expect(push).not.toHaveBeenCalled();
});

it("offers no Resume action on either cancelled-subscription screen", async () => {
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
  const subs = await fixtureBilling.readSubscriptions("personal");
  subs.current = { ...subs.current!, cancelAtPeriodEnd: true };
  await render(
    <>
      <BillingView subs={subs} status="ready" />
      <PlanAndBillingPane
        subs={subs}
        status="ready"
        allowance={{ state: "error" }}
        onRetry={() => {}}
      />
    </>,
  );
  expect(host.textContent).not.toContain("Resume renewal");
  expect(host.textContent).toContain("Cancels at period end");
});

function SettingsBilling({ client }: { client: typeof fixtureBilling }) {
  return <AccountSettings billing={useBillingAccount(true, client)} />;
}

it("Settings keeps a paid subscription usable when only invoice reads fail", async () => {
  await activeSubscription();
  await render(
    <SettingsBilling
      client={{
        ...fixtureBilling,
        readInvoices: async () => {
          throw new Error("invoice outage");
        },
      }}
    />,
  );
  await click("Plan & billing");
  for (
    let i = 0;
    i < 100 && (!button("Cancel renewal") || button("Cancel renewal").disabled);
    i++
  )
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
  expect(button("Cancel renewal").disabled).toBe(false);
  expect(host.textContent).toContain("Personal");
  expect(host.textContent).toContain(
    "Invoices and receipts are currently unavailable",
  );
  expect(host.textContent).not.toContain("No invoices or receipts yet");
});
