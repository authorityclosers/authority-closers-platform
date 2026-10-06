import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { BillingClient } from "../billing/billing-api";
import {
  parseOrder,
  parseUsage,
  type Order,
  type Usage,
} from "../billing/contract";
import { fixtureBilling } from "../review-fixture/plans/fixture-billing";
import { WorkspaceAccessContext } from "../workspace-access";
import { OrderReturn } from "./order-return";

vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
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
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

function order(topUp = false, status: Order["status"] = "paid") {
  return parseOrder({
    order_id: topUp ? "fictional-org-top-up" : "fictional-personal-order",
    kind: topUp ? "top_up" : "subscription",
    account: topUp ? "organisation" : "personal",
    status,
    mode: "test",
    amount: { minor: 249900, currency: "INR", gst_inclusive: true },
    plan_key: topUp ? "organisation" : "personal",
    plan_name: topUp ? "Organisation" : "Personal",
    interval: topUp ? null : "month",
    seats: topUp ? 3 : 1,
    pack_key: topUp ? "fictional-top-up" : null,
    minutes: topUp ? 10000 : 800,
    subscription_id: null,
    created_at: "2026-10-05T10:00:00Z",
    paid_at: status === "paid" ? "2026-10-05T10:01:00Z" : null,
    refund: null,
  });
}
function usage(availableMinutes: number) {
  return parseUsage({
    allowance: {
      allowance_seconds: (availableMinutes + 38) * 60 + 59,
      committed_seconds: 38 * 60,
      available_seconds: availableMinutes * 60 + 59,
      unlimited: false,
    },
    calls: [],
    earlier_seconds: 0,
    truncated: false,
  });
}
async function render(result: Order, client: BillingClient) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: {
            personId: "fictional-person",
            sessionId: "fictional-session",
            tenantId: "fictional-workspace",
          },
          retry: () => {},
        }}
      >
        <OrderReturn orderId={result.orderId} client={client} />
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
function field(label: string) {
  return [...host.querySelectorAll("dt")].find(
    (node) => node.textContent === label,
  )?.nextElementSibling?.textContent;
}

it.each([
  [false, 862, "800 min (13 h 20 min)", "862 analysis minutes (14 h 22 min)"],
  [
    true,
    10062,
    "10,000 min (166 h 40 min)",
    "10,062 analysis minutes (167 h 42 min)",
  ],
])(
  "keeps purchased and available minutes separate (top-up: %s)",
  async (topUp, available, purchased, balance) => {
    const result = order(topUp);
    const verifyOrder = vi.fn(async () => result);
    const readUsage = vi.fn(async () => usage(available));
    await render(result, { ...fixtureBilling, verifyOrder, readUsage });
    expect(host.textContent).toContain("Payment confirmed");
    expect(field("Order minutes")).toBe(purchased);
    expect(field("New balance")).toBe(balance);
    expect(field(topUp ? "Top-up" : "Plan")).toBe(
      topUp ? "10,000 top-up minutes (166 h 40 min)" : "Personal, monthly",
    );
    if (topUp) expect(field("Seats")).toBe("3");
    expect(host.querySelector('span[aria-live="polite"]')?.textContent).toBe(
      topUp
        ? "+10,000 analysis minutes (166 h 40 min)"
        : "+800 analysis minutes (13 h 20 min)",
    );
    expect(host.textContent).toContain("TEST");
    expect(host.querySelector('a[href="/account#billing"]')?.textContent).toBe(
      "Billing & receipts",
    );
    expect(host.textContent).not.toMatch(/credits/i);
    expect(verifyOrder).toHaveBeenCalledWith(
      result.orderId,
      expect.any(String),
    );
    expect(readUsage).toHaveBeenCalledOnce();
  },
);

it("keeps a missing balance confirming instead of displaying purchased minutes as available", async () => {
  const result = order();
  await render(result, {
    ...fixtureBilling,
    verifyOrder: async () => result,
    readUsage: async () => {
      throw new Error("Fictional unavailable usage");
    },
  });
  expect(field("Order minutes")).toBe("800 min (13 h 20 min)");
  expect(field("New balance")).toBe("Your updated minutes are being confirmed");
});

it("does not reuse a previous order's balance while the next balance is pending", async () => {
  const first = order();
  const second = order(true);
  let resolveUsage!: (value: Usage) => void;
  const nextUsage = new Promise<Usage>((resolve) => {
    resolveUsage = resolve;
  });
  const client = {
    ...fixtureBilling,
    verifyOrder: async (id: string) => (id === first.orderId ? first : second),
    readUsage: vi
      .fn()
      .mockResolvedValueOnce(usage(862))
      .mockReturnValueOnce(nextUsage),
  };
  await render(first, client);
  expect(field("New balance")).toBe("862 analysis minutes (14 h 22 min)");
  await render(second, client);
  expect(field("Order minutes")).toBe("10,000 min (166 h 40 min)");
  expect(field("New balance")).toBe("Your updated minutes are being confirmed");
  await act(async () => resolveUsage(usage(10062)));
  expect(field("New balance")).toBe("10,062 analysis minutes (167 h 42 min)");
});

it.each([
  ["awaiting_payment", "Confirming your payment"],
  ["confirming", "Confirming your payment"],
  ["failed", "Payment failed"],
  ["expired", "Order expired"],
  ["needs_review", "We are checking this payment"],
] as const)("keeps %s out of the success display", async (status, heading) => {
  const result = order(false, status);
  const readUsage = vi.fn();
  await render(result, {
    ...fixtureBilling,
    verifyOrder: async () => result,
    readUsage,
  });
  expect(host.querySelector("h2")?.textContent).toBe(heading);
  expect(field("New balance")).toBeUndefined();
  expect(host.querySelector('span[aria-live="polite"]')).toBeNull();
  expect(readUsage).not.toHaveBeenCalled();
});
