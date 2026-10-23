// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { BillingError } from "./billing-api";
import type { Refund } from "./contract";
import { RefundRequest } from "./refund-request";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/settings/plan",
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const available: Refund = {
  paymentId: "pay_fictional",
  refundableUntil: "2026-10-30T09:00:00Z",
  state: "available",
  reasonCode: null,
};

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
  document.body.innerHTML = "";
});

const page = () => document.body.textContent ?? "";
function button(label: string) {
  return [...document.body.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );
}
async function show(refund: Refund | null, onRequest = vi.fn()) {
  await act(async () =>
    root.render(
      <RefundRequest refund={refund} amount="₹2,499" onRequest={onRequest} />,
    ),
  );
  return onRequest;
}

it.each([
  [null],
  [
    {
      ...available,
      state: "unavailable" as const,
      reasonCode: "used" as const,
    },
  ],
  [
    {
      ...available,
      state: "unavailable" as const,
      reasonCode: "window_closed" as const,
    },
  ],
])("offers nothing when the payment does not qualify (%#)", async (refund) => {
  await show(refund);
  expect(button("Request refund")).toBeUndefined();
});

it("says where a refund already stands", async () => {
  await show({ ...available, state: "pending" });
  expect(host.textContent).toBe("Refund requested");
  await show({ ...available, state: "refunded" });
  expect(host.textContent).toBe("Refunded");
});

it("asks once, then shows the refund as requested", async () => {
  const onRequest = vi.fn(async () => ({
    ...available,
    state: "pending" as const,
  }));
  await show(available, onRequest);
  await act(async () => button("Request refund")!.click());
  expect(page()).toContain("Request a refund");
  expect(page()).toContain("none of this payment");
  await act(async () => button("Refund ₹2,499")!.click());
  expect(onRequest).toHaveBeenCalledTimes(1);
  const [paymentId, reason, key] = onRequest.mock.calls[0];
  expect(paymentId).toBe("pay_fictional");
  expect(reason).toBe("Asked for a refund in the app");
  expect(typeof key).toBe("string");
  expect(host.textContent).toBe("Refund requested");
});

it("shows the server's reason when it refuses", async () => {
  const onRequest = vi.fn(async () => {
    throw new BillingError(
      409,
      "payment_used",
      "Minutes from this payment were already used, so it cannot be refunded.",
    );
  });
  await show(available, onRequest);
  await act(async () => button("Request refund")!.click());
  await act(async () => button("Refund ₹2,499")!.click());
  expect(page()).toContain("already used");
  expect(button("Refund ₹2,499")).toBeDefined();
});
