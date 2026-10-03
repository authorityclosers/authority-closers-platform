import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BILLING_PATH,
  BillingReadError,
  loadStaffBilling,
  requestRefund,
  staffBillingSchema,
} from "./billing-api";
import { billingFixture } from "./billing-fixture";

type Draft = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const clone = (): Draft => structuredClone(billingFixture);
const signal = () => new AbortController().signal;

afterEach(() => vi.restoreAllMocks());

describe("staffBillingSchema", () => {
  it("accepts the fictional fixture and an honest empty overview", () => {
    expect(staffBillingSchema.parse(clone())).toEqual(billingFixture);
    expect(
      staffBillingSchema.safeParse({
        ...clone(),
        orders: [],
        payments: [],
        refunds: [],
        subscriptions: [],
      }).success,
    ).toBe(true);
  });

  it.each([
    ["an extra top-level field", (v: Draft) => (v.invoices = [])],
    ["an extra row field", (v: Draft) => (v.orders[0].secret = "x")],
    [
      "an extra customer field",
      (v: Draft) => (v.orders[0].customer.phone = "1"),
    ],
    ["an unknown order status", (v: Draft) => (v.orders[0].status = "settled")],
    [
      "an unknown customer kind",
      (v: Draft) => (v.orders[0].customer.kind = "x"),
    ],
    ["a negative amount", (v: Draft) => (v.orders[0].amount_minor = -1)],
    ["a fractional amount", (v: Draft) => (v.payments[0].amount_minor = 1.5)],
    ["a lower-case currency", (v: Draft) => (v.orders[0].currency = "inr")],
    ["zero seats", (v: Draft) => (v.subscriptions[0].seats = 0)],
    ["a bad payment id", (v: Draft) => (v.payments[0].payment_id = "pay/../x")],
    ["an unknown refund state", (v: Draft) => (v.refunds[0].state = "partial")],
    ["a date without offset", (v: Draft) => (v.orders[0].created_at = "2026")],
    ["a different page limit", (v: Draft) => (v.page_limit = 1000)],
    ["a missing field", (v: Draft) => delete v.subscriptions[0].renews_at],
    [
      "duplicate orders",
      (v: Draft) => (v.orders[1].order_id = v.orders[0].order_id),
    ],
    [
      "duplicate payments",
      (v: Draft) => (v.payments[1].payment_id = v.payments[0].payment_id),
    ],
    [
      "a renewal on a cancelled-at-period-end subscription",
      (v: Draft) => (v.subscriptions[0].renews_at = "2026-11-01T09:00:00Z"),
    ],
    [
      "cancel flag disagreeing with cancel state",
      (v: Draft) => (v.subscriptions[0].cancel_state = "none"),
    ],
    [
      "more than 100 rows",
      (v: Draft) =>
        (v.refunds = Array.from({ length: 101 }, (_, i) => ({
          ...v.refunds[0],
          payment_id: "pay_" + i,
        }))),
    ],
  ])("rejects %s", (_name, change) => {
    const value = clone();
    change(value);
    expect(staffBillingSchema.safeParse(value).success).toBe(false);
  });
});

describe("loadStaffBilling", () => {
  it("reads the exact path without cookies leaving the origin", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(billingFixture));
    await expect(loadStaffBilling(signal(), fetcher)).resolves.toEqual(
      billingFixture,
    );
    expect(fetcher).toHaveBeenCalledWith(
      BILLING_PATH,
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      }),
    );
  });

  it.each([
    [401, "denied"],
    [403, "denied"],
    [500, "unavailable"],
  ])("maps HTTP %i to %s", async (status, kind) => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(Response.json({ detail: "no" }, { status }));
    await expect(loadStaffBilling(signal(), fetcher)).rejects.toEqual(
      new BillingReadError(kind as "denied" | "unavailable"),
    );
  });

  it("treats a malformed body or network failure as unavailable", async () => {
    const malformed = vi.fn().mockResolvedValue(Response.json({ orders: [] }));
    await expect(loadStaffBilling(signal(), malformed)).rejects.toMatchObject({
      kind: "unavailable",
    });
    const offline = vi.fn().mockRejectedValue(new TypeError("offline"));
    await expect(loadStaffBilling(signal(), offline)).rejects.toMatchObject({
      kind: "unavailable",
    });
  });
});

describe("requestRefund", () => {
  it("posts the reason with an idempotency key to the staff route", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json(
        {
          refund: {
            payment_id: "pay_example_pack",
            refundable_until: "2026-10-08T11:01:00Z",
            state: "pending",
            reason_code: null,
          },
        },
        { status: 202 },
      ),
    );
    await expect(
      requestRefund(
        "pay_example_pack",
        "Wrong plan",
        "key-1",
        signal(),
        fetcher,
      ),
    ).resolves.toEqual({ ok: true, state: "pending" });
    const [path, init] = fetcher.mock.calls[0];
    expect(path).toBe("/v1/platform/billing/payments/pay_example_pack/refund");
    expect(init).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      headers: expect.objectContaining({ "idempotency-key": "key-1" }),
    });
    expect(JSON.parse(init.body)).toEqual({ reason: "Wrong plan" });
  });

  it("returns the server's refusal reason as written", async () => {
    const detail =
      "Minutes from this payment were already used, so it cannot be refunded.";
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        Response.json({ code: "payment_used", detail }, { status: 409 }),
      );
    await expect(
      requestRefund(
        "pay_example_pack",
        "Wrong plan",
        "key-2",
        signal(),
        fetcher,
      ),
    ).resolves.toEqual({ ok: false, reason: detail });
  });

  it("does not trust a success body for another payment", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({
        refund: {
          payment_id: "pay_other",
          refundable_until: null,
          state: "refunded",
          reason_code: null,
        },
      }),
    );
    const outcome = await requestRefund(
      "pay_example_pack",
      "Wrong plan",
      "key-3",
      signal(),
      fetcher,
    );
    expect(outcome.ok).toBe(false);
  });
});
