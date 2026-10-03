// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BillingPanel } from "./billing-panel";
import { billingFixture } from "./billing-fixture";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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
async function mount(fetcher: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<BillingPanel />));
}
function button(text: string) {
  const found = [...container.querySelectorAll("button")].find(
    (element) => element.textContent?.trim() === text,
  );
  if (!found) throw new Error("missing button " + text);
  return found;
}

it("shows orders, payments, refunds and subscriptions from the fixture", async () => {
  await mount(vi.fn().mockResolvedValue(Response.json(billingFixture)));
  const text = container.textContent ?? "";
  for (const expected of [
    "Example Sales Team",
    "Organisation",
    "Sam Example",
    "Personal",
    "Team",
    "₹7,497.00",
    "incl. GST",
    "Paid",
    "sub_example_team",
    "Renewal charged",
    "Bought the wrong plan",
    "Succeeded",
    "Cancelled at period end",
    "The platform does not issue invoices yet",
  ])
    expect(text).toContain(expected);
  expect(
    container.querySelector('a[href="/sales-xray/settings"]'),
  ).not.toBeNull();
  // Only the payment the server marks available offers a refund.
  expect(
    [...container.querySelectorAll("button")].filter(
      (element) => element.textContent === "Refund",
    ),
  ).toHaveLength(1);
});

it("states empty lists honestly", async () => {
  await mount(
    vi.fn().mockResolvedValue(
      Response.json({
        ...billingFixture,
        orders: [],
        payments: [],
        refunds: [],
        subscriptions: [],
      }),
    ),
  );
  const text = container.textContent ?? "";
  for (const expected of [
    "No orders yet.",
    "No payments yet.",
    "No refunds requested.",
    "No subscriptions yet.",
  ])
    expect(text).toContain(expected);
  expect(container.querySelector("table")).toBeNull();
});

it.each([
  [403, "Your billing assignment could not be confirmed"],
  [500, "Billing could not be loaded"],
])("shows an error and no data on HTTP %i", async (status, message) => {
  await mount(
    vi.fn().mockResolvedValue(Response.json({ detail: "x" }, { status })),
  );
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    message,
  );
  expect(container.querySelector("table")).toBeNull();
});

it("rejects a malformed answer instead of showing it", async () => {
  await mount(
    vi
      .fn()
      .mockResolvedValue(
        Response.json({ ...billingFixture, orders: [{ order_id: "x" }] }),
      ),
  );
  expect(container.textContent).toContain("Billing could not be loaded");
  expect(container.textContent).not.toContain("Example Sales Team");
});

it("shows the server's refund refusal reason as returned", async () => {
  const detail =
    "Minutes from this payment were already used, so it cannot be refunded.";
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(Response.json(billingFixture))
    .mockResolvedValueOnce(
      Response.json({ code: "payment_used", detail }, { status: 409 }),
    );
  await mount(fetcher);
  await act(async () => button("Refund").click());
  const textarea = container.querySelector("textarea")!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!;
    setter.call(textarea, "Customer asked");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Request refund").click());
  expect(fetcher).toHaveBeenLastCalledWith(
    "/v1/payments/pay_example_pack/refund",
    expect.objectContaining({ method: "POST" }),
  );
  expect(container.querySelector('[role="alert"]')?.textContent).toBe(detail);
});
