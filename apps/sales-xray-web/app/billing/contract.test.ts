import { describe, expect, it } from "vitest";

import {
  ContractError,
  onSale,
  parseCheckout,
  parseMePlan,
  parseOfflinePayment,
  parseOrder,
  parsePlans,
  parseProblem,
  parseSubscriptions,
  parseUsage,
} from "./contract";
import { FIXTURE_PLANS } from "../review-fixture/plans/fixture-billing";

// Fictional shapes copied from contract C1 (AUT-560) and the AUT-418 read.
const ORDER = {
  order_id: "00000000-0000-4000-8000-0000000000aa",
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
  subscription_id: "00000000-0000-4000-8000-0000000000bb",
  created_at: "2026-09-30T18:00:00Z",
  paid_at: null,
  refund: null,
};

const SUBSCRIPTION = {
  subscription_id: "00000000-0000-4000-8000-0000000000bb",
  account: "personal",
  plan_key: "personal",
  plan_name: "Personal",
  interval: "month",
  seats: 1,
  amount: { minor: 249900, currency: "INR", gst_inclusive: true },
  mode: "test",
  status: "active",
  current_period: {
    start: "2026-09-30T18:00:00Z",
    end: "2026-10-30T18:00:00Z",
  },
  renews_at: "2026-10-30T18:00:00Z",
  cancel_at_period_end: false,
  cancel_state: "none",
  renewal_needs_customer_approval: false,
  created_at: "2026-09-30T18:00:00Z",
};

describe("plans catalogue (GET /v1/plans)", () => {
  it("parses the public coming-soon and active response from PR #206", () => {
    // Exact public shapes from test_public_catalogue.py at b7168f2 (PR #206).
    const response = {
      plans: [
        {
          key: "personal",
          name: "Personal",
          audience: "For one salesperson",
          status: "coming_soon",
          prices: null,
          included_minutes: 300,
          seat_min: 1,
          seat_max: 1,
          per_seat: true,
          longest_call_minutes: 90,
          retention_days: 365,
          rollover_months: 1,
          feature_keys: ["sales_xray_reports"],
          top_up_packs: [
            {
              key: "pack_small",
              minutes: 60,
              validity_rule: "billing_year_end",
            },
          ],
          sort_order: 10,
          revision: 3,
        },
        {
          key: "organisation",
          name: "Personal",
          audience: "For one salesperson",
          status: "active",
          prices: {
            monthly_paise: 99900,
            yearly_paise: 999900,
            monthly_cents: 1299,
            yearly_cents: 12999,
          },
          included_minutes: 300,
          seat_min: 1,
          seat_max: 1,
          per_seat: true,
          longest_call_minutes: 90,
          retention_days: 365,
          rollover_months: 1,
          feature_keys: ["sales_xray_reports"],
          top_up_packs: [
            {
              key: "pack_small",
              minutes: 60,
              validity_rule: "billing_year_end",
              price_paise: 49900,
              price_cents: 599,
            },
          ],
          sort_order: 20,
          revision: 3,
        },
      ],
    };
    const [soon, active] = parsePlans(response);
    expect(soon.perSeat).toBe(true);
    expect(soon.prices).toBeNull();
    expect(soon.topUpPacks[0]).toEqual({
      key: "pack_small",
      minutes: 60,
      validityRule: "billing_year_end",
      pricePaise: null,
      priceCents: null,
    });
    expect(onSale(soon)).toBe(false);
    expect(active.perSeat).toBe(true);
    expect(active.prices).toEqual({
      monthlyPaise: 99900,
      yearlyPaise: 999900,
      monthlyCents: 1299,
      yearlyCents: 12999,
    });
    expect(active.topUpPacks[0].pricePaise).toBe(49900);
    expect(active.topUpPacks[0].priceCents).toBe(599);
    expect(onSale(active)).toBe(true);
  });

  it("defaults per-seat to false for a response without per_seat", () => {
    const legacyPlan: Record<string, unknown> = { ...FIXTURE_PLANS.plans[0] };
    delete legacyPlan.per_seat;
    expect(parsePlans({ plans: [legacyPlan] })[0].perSeat).toBe(false);
  });

  it("parses the approved catalogue shape, sorted, and knows what is on sale", () => {
    const plans = parsePlans(FIXTURE_PLANS);
    expect(plans.map((plan) => plan.key)).toEqual([
      "personal",
      "organisation",
      "enterprise",
    ]);
    expect(plans[0].prices?.monthlyPaise).toBe(249900);
    expect(plans[0].topUpPacks[0]).toEqual({
      key: "personal_100",
      minutes: 100,
      validityRule: "billing_year_end",
      pricePaise: 29900,
      priceCents: null,
    });
    expect(onSale(plans[0])).toBe(true);
    expect(onSale(plans[2])).toBe(true);
    expect(plans[0].perSeat).toBe(false);
    expect(plans[1].perSeat).toBe(true);
    expect(() =>
      parsePlans({ plans: [{ ...FIXTURE_PLANS.plans[0], per_seat: "yes" }] }),
    ).toThrow(ContractError);
  });

  it("treats a coming-soon plan with no prices as not on sale, and refuses unknown fields", () => {
    const soon = parsePlans({
      plans: [
        {
          ...FIXTURE_PLANS.plans[0],
          status: "coming_soon",
          prices: null,
          top_up_packs: [
            { key: "p", minutes: 100, validity_rule: "billing_year_end" },
          ],
        },
      ],
    })[0];
    expect(onSale(soon)).toBe(false);
    expect(soon.topUpPacks[0].pricePaise).toBeNull();
    expect(() =>
      parsePlans({ plans: [{ ...FIXTURE_PLANS.plans[0], surprise: 1 }] }),
    ).toThrow(ContractError);
    expect(() =>
      parsePlans({
        plans: [
          {
            ...FIXTURE_PLANS.plans[0],
            top_up_packs: [{ key: "p", minutes: 100, validity_rule: "days" }],
          },
        ],
      }),
    ).toThrow(ContractError);
  });
});

describe("plan in effect and usage (AUT-417)", () => {
  it("parses /v1/me/plan and /v1/me/usage", () => {
    const me = parseMePlan({
      plan: { key: "trial", name: "Trial" },
      allowance: {
        allowance_seconds: 6000,
        committed_seconds: 2280,
        available_seconds: 3720,
      },
      longest_call_seconds: 6000,
    });
    expect(me.allowance).toEqual({
      allowanceSeconds: 6000,
      committedSeconds: 2280,
      availableSeconds: 3720,
      unlimited: false,
    });
    const usage = parseUsage({
      allowance: {
        allowance_seconds: 6000,
        committed_seconds: 2280,
        available_seconds: 3720,
        unlimited: true,
      },
      calls: [
        {
          submission_id: "s1",
          created_at: "2026-09-30T00:00:00Z",
          display_name: "A call",
          seconds: 1380,
          state: "charged",
        },
      ],
      earlier_seconds: 900,
      truncated: false,
    });
    expect(usage.allowance.unlimited).toBe(true);
    expect(usage.calls[0].state).toBe("charged");
    expect(() =>
      parseUsage({
        allowance: {},
        calls: [],
        earlier_seconds: 0,
        truncated: false,
      }),
    ).toThrow(ContractError);
  });
});

describe("contract C1", () => {
  it("parses a checkout response with its hosted step", () => {
    const checkout = parseCheckout({
      order: ORDER,
      hosted: {
        provider: "razorpay",
        kind: "client_sdk",
        url: null,
        params: { key_id: "rzp_test_x", order_ref: "order_x" },
        expires_at: "2026-09-30T18:15:00Z",
      },
    });
    expect(checkout.order.status).toBe("awaiting_payment");
    expect(checkout.hosted.params).toEqual({
      key_id: "rzp_test_x",
      order_ref: "order_x",
    });
    expect(() =>
      parseCheckout({
        order: ORDER,
        hosted: {
          provider: "x",
          kind: "popup",
          url: null,
          params: {},
          expires_at: "",
        },
      }),
    ).toThrow(ContractError);
  });

  it("parses orders through every status, with a refund block when paid", () => {
    for (const status of [
      "awaiting_payment",
      "confirming",
      "paid",
      "failed",
      "expired",
      "needs_review",
    ])
      expect(parseOrder({ ...ORDER, status }).status).toBe(status);
    const paid = parseOrder({
      ...ORDER,
      status: "paid",
      paid_at: "2026-09-30T18:05:00Z",
      refund: {
        payment_id: "pay_x",
        refundable_until: "2026-10-07T18:05:00Z",
        state: "available",
        reason_code: null,
      },
    });
    expect(paid.refund?.state).toBe("available");
    expect(() => parseOrder({ ...ORDER, status: "settled" })).toThrow(
      ContractError,
    );
    expect(() => parseOrder({ ...ORDER, price: 1 })).toThrow(ContractError);
  });

  it("accepts optional C1 tax, rejects invalid tax and accepts hosted steps without expiry", () => {
    const tax = {
      mode: "inclusive",
      rate_basis_points: 1800,
      taxable_minor: 211780,
      gst_minor: 38120,
      total_minor: 249900,
    };
    expect(parseOrder(ORDER).tax).toBeNull();
    expect(parseOrder({ ...ORDER, tax }).tax).toEqual({
      mode: "inclusive",
      rateBasisPoints: 1800,
      taxableMinor: 211780,
      gstMinor: 38120,
      totalMinor: 249900,
    });
    const exclusive = {
      mode: "exclusive",
      rate_basis_points: 1800,
      taxable_minor: 2000000,
      gst_minor: 360000,
      total_minor: 2360000,
    };
    expect(
      parseOrder({
        ...ORDER,
        amount: { ...ORDER.amount, minor: 2360000 },
        tax: exclusive,
      }).tax?.mode,
    ).toBe("exclusive");
    for (const invalid of [
      { ...tax, mode: "unknown" },
      { ...tax, extra: true },
      { ...tax, gst_minor: -1 },
      { ...tax, taxable_minor: 1.5 },
      { ...tax, total_minor: 1 },
      { ...tax, taxable_minor: 211781, total_minor: 249901 },
    ])
      expect(() => parseOrder({ ...ORDER, tax: invalid })).toThrow(
        ContractError,
      );
    expect(
      parseCheckout({
        order: ORDER,
        hosted: {
          provider: "fake",
          kind: "redirect",
          url: "/return",
          params: {},
          expires_at: null,
        },
      }).hosted.expiresAt,
    ).toBeNull();
  });

  it("parses subscriptions and the cancel-at-period-end state", () => {
    const subs = parseSubscriptions({
      current: {
        ...SUBSCRIPTION,
        cancel_at_period_end: true,
        cancel_state: "confirmed",
      },
      past: [{ ...SUBSCRIPTION, status: "ended" }],
    });
    expect(subs.current?.cancelAtPeriodEnd).toBe(true);
    expect(subs.past[0].status).toBe("ended");
    expect(parseSubscriptions({ current: null, past: [] }).current).toBeNull();
  });

  it("parses offline payment details and problem bodies", () => {
    const offline = parseOfflinePayment({
      enabled: true,
      payee_name: "Fictional Payee",
      upi_id: "fixture@upi",
      bank: null,
      instructions: null,
      revision: 2,
    });
    expect(offline.upiId).toBe("fixture@upi");
    expect(
      parseProblem({
        type: "about:blank",
        title: "Not on sale",
        status: 409,
        detail: "Not yet.",
        code: "not_on_sale",
      })?.code,
    ).toBe("not_on_sale");
    expect(parseProblem("<html>")).toBeNull();
    expect(parseProblem({ message: "nope" })).toBeNull();
  });
});
