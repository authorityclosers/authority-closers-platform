import { afterEach, expect, it, vi } from "vitest";
import { BillingError, liveBilling } from "./billing-api";

afterEach(() => vi.unstubAllGlobals());

it("sends only C1 checkout fields, verifies bodylessly and retains error codes", async () => {
  const fetch = vi.fn<(path: string, init: RequestInit) => Promise<Response>>(
    async () =>
      new Response(
        JSON.stringify({
          order: {
            order_id: "order-fictional",
            kind: "subscription",
            account: "personal",
            status: "awaiting_payment",
            mode: "test",
            amount: { minor: 249900, currency: "INR", gst_inclusive: true },
            plan_key: "personal",
            plan_name: "Personal",
            interval: "month",
            seats: 1,
            pack_key: null,
            minutes: 800,
            subscription_id: "sub",
            created_at: "2026-10-03T00:00:00Z",
            paid_at: null,
            refund: null,
          },
          hosted: {
            provider: "fake",
            kind: "redirect",
            url: "/return",
            params: {},
            expires_at: null,
          },
        }),
        { headers: { "content-type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetch);
  await liveBilling.checkout(
    {
      kind: "subscription",
      account: "organisation",
      planKey: "organisation",
      interval: "year",
      seats: 2,
    },
    "retry-key",
  );
  const [path, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(path).toBe("/v1/checkout");
  expect(init.credentials).toBe("same-origin");
  expect(init.headers).toMatchObject({ "Idempotency-Key": "retry-key" });
  expect(JSON.parse(String(init.body))).toEqual({
    kind: "subscription",
    account: "organisation",
    plan_key: "organisation",
    interval: "year",
    seats: 2,
  });
  fetch.mockImplementationOnce(
    async () =>
      new Response(
        JSON.stringify({
          type: "about:blank",
          title: "Unavailable",
          status: 409,
          code: "not_on_sale",
          detail: "Off",
        }),
        {
          status: 409,
          headers: { "content-type": "application/problem+json" },
        },
      ),
  );
  await expect(
    liveBilling.verifyOrder("order/one", "verify-key"),
  ).rejects.toMatchObject({
    status: 409,
    code: "not_on_sale",
  } satisfies Partial<BillingError>);
  expect(fetch.mock.calls[1]).toEqual([
    "/v1/orders/order%2Fone/verify",
    expect.objectContaining({ method: "POST", idempotencyKey: "verify-key" }),
  ]);
  expect(
    (fetch.mock.calls[1] as unknown as [string, RequestInit])[1].body,
  ).toBeUndefined();
});
