// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import type { Hosted } from "../billing/contract";
import { openHostedCheckout } from "./hosted-checkout";

afterEach(() => {
  document.head.innerHTML = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("passes the server subscription or order reference to the SDK and leaves payment verification to AC", async () => {
  const script = document.createElement("script");
  script.src = "https://checkout.razorpay.com/v1/checkout.js";
  script.dataset.loaded = "true";
  vi.spyOn(document, "querySelector").mockReturnValue(script);
  const options: Record<string, unknown>[] = [];
  class FakeRazorpay {
    constructor(readonly config: Record<string, unknown>) {
      options.push(config);
    }
    open() {
      (this.config.handler as () => void)();
    }
  }
  vi.stubGlobal("Razorpay", FakeRazorpay);
  const hosted: Hosted = {
    provider: "razorpay",
    kind: "client_sdk",
    url: null,
    params: { key_id: "public-fictional", subscription_ref: "sub-fictional" },
    expiresAt: null,
  };
  expect(await openHostedCheckout(hosted, "ac-order")).toBe("done");
  expect(options[0]).toMatchObject({
    subscription_id: "sub-fictional",
    notes: { order_id: "ac-order" },
  });
  expect(options[0]).not.toHaveProperty("order_id");
  expect(
    await openHostedCheckout(
      {
        ...hosted,
        params: { key_id: "public-fictional", order_ref: "order-fictional" },
      },
      "ac-top-up",
    ),
  ).toBe("done");
  expect(options[1]).toMatchObject({ order_id: "order-fictional" });
  expect(options[1]).not.toHaveProperty("subscription_id");
});
