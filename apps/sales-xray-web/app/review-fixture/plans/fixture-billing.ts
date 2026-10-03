/**
 * A fictional billing server for local visual review of the plans screens.
 * It speaks contract C1 shapes exactly, keeps its orders in sessionStorage
 * so the pay and return pages share them, and sells the approved catalogue
 * (AUT-410, 30 Sep 2026) in TEST mode. No provider, account or money exists.
 */
import {
  BillingError,
  type BillingClient,
  type CheckoutRequest,
} from "../../billing/billing-api";
import {
  parseCheckout,
  parseMePlan,
  parseOfflinePayment,
  parseOrder,
  parsePlans,
  parseSubscriptions,
  parseUsage,
  type Order,
  type Subscription,
} from "../../billing/contract";

const STORE = "ac.xray.fixture-billing";
export const FIXTURE_PAY_PATH = "/review-fixture/plans/pay";
export const FIXTURE_RETURN_PATH = "/review-fixture/plans/return";

import {
  PLANS_CATALOGUE_FIXTURE,
  TOP_UP_PACKS,
} from "../../plans/plans-catalogue-fixture";

/** Fictional wire shapes for the current owner-approved display catalogue. */
export const FIXTURE_PLANS = {
  plans: PLANS_CATALOGUE_FIXTURE.map((plan) => ({
    key: plan.key,
    name: plan.name,
    audience: plan.audience,
    status: plan.status,
    prices: plan.prices
      ? {
          monthly_paise: plan.prices.monthlyPaise!,
          yearly_paise: plan.prices.yearlyPaise!,
          monthly_cents: null,
          yearly_cents: null,
        }
      : null,
    included_minutes: plan.includedMinutes,
    seat_min: plan.seatMin,
    seat_max: plan.seatMax,
    per_seat: plan.key !== "personal",
    longest_call_minutes: plan.longestCallMinutes,
    retention_days: plan.retentionDays,
    rollover_months: plan.rolloverMonths,
    feature_keys: plan.featureKeys,
    top_up_packs: TOP_UP_PACKS.filter(
      (pack) =>
        pack.planKey === plan.key ||
        (plan.key === "enterprise" && pack.planKey === "organisation"),
    ).map((pack) => ({
      key: pack.key,
      minutes: pack.minutes,
      validity_rule: "billing_year_end",
      price_paise: pack.pricePaise,
      price_cents: null,
    })),
    sort_order: plan.sortOrder,
    revision: plan.revision,
  })),
};

type Store = {
  orders: Record<string, Record<string, unknown>>;
  subscriptions: Record<string, unknown>[];
  minutesLeft: number;
  minutesTotal: number;
};

function read(): Store {
  try {
    const raw = sessionStorage.getItem(STORE);
    if (raw) return JSON.parse(raw) as Store;
  } catch {
    // Fresh store.
  }
  return { orders: {}, subscriptions: [], minutesLeft: 62, minutesTotal: 100 };
}
function write(store: Store) {
  try {
    sessionStorage.setItem(STORE, JSON.stringify(store));
  } catch {
    // Private windows may refuse storage; the fixture then forgets.
  }
}
const now = () => new Date().toISOString();
const later = (months: number) => {
  const date = new Date();
  date.setMonth(date.getMonth() + months);
  return date.toISOString();
};
const id = () => `fixture-${Math.random().toString(16).slice(2, 10)}`;
const wait = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms));

function liveSubscription(store: Store) {
  return (
    store.subscriptions.find((item) =>
      ["active", "past_due", "pending_authorisation"].includes(
        String(item.status),
      ),
    ) ?? null
  );
}

/** The pay page calls this: the fictional provider reports the outcome to "our server". */
export function fixtureProviderReports(
  orderId: string,
  outcome: "paid" | "failed",
) {
  const store = read();
  const order = store.orders[orderId];
  if (!order || order.status === "paid") return;
  order.status = outcome;
  order.paid_at = outcome === "paid" ? now() : null;
  if (outcome === "paid") {
    order.refund = {
      payment_id: `pay_${orderId}`,
      refundable_until: new Date(
        Date.now() + 7 * 24 * 60 * 60 * 1000,
      ).toISOString(),
      state: "available",
      reason_code: null,
    };
    const minutes = Number(order.minutes);
    store.minutesLeft += minutes;
    store.minutesTotal += minutes;
    if (order.kind === "subscription") {
      store.subscriptions = store.subscriptions.map((item) => ({
        ...item,
        status: "ended",
      }));
      store.subscriptions.unshift({
        subscription_id: String(order.subscription_id),
        account: order.account,
        plan_key: order.plan_key,
        plan_name: order.plan_name,
        interval: order.interval,
        seats: order.seats,
        amount: order.amount,
        mode: "test",
        status: "active",
        current_period: {
          start: now(),
          end: later(order.interval === "year" ? 12 : 1),
        },
        renews_at: later(order.interval === "year" ? 12 : 1),
        cancel_at_period_end: false,
        cancel_state: "none",
        renewal_needs_customer_approval:
          Number((order.amount as { minor: number }).minor) > 1_500_000,
        created_at: now(),
      });
    }
  }
  write(store);
}

export function resetFixtureBilling() {
  try {
    sessionStorage.removeItem(STORE);
  } catch {
    // Nothing to forget.
  }
}

export const fixtureBilling: BillingClient = {
  async readPlans() {
    await wait();
    return parsePlans(FIXTURE_PLANS);
  },
  async readMePlan() {
    await wait();
    const store = read();
    const current = liveSubscription(store);
    return parseMePlan({
      plan: current
        ? { key: current.plan_key, name: current.plan_name }
        : { key: "trial", name: "Trial" },
      allowance: {
        allowance_seconds: store.minutesTotal * 60,
        committed_seconds: (store.minutesTotal - store.minutesLeft) * 60,
        available_seconds: store.minutesLeft * 60,
      },
      longest_call_seconds: current
        ? current.plan_key === "organisation"
          ? 7200
          : 5400
        : 3600,
    });
  },
  async readUsage() {
    await wait();
    const store = read();
    return parseUsage({
      allowance: {
        allowance_seconds: store.minutesTotal * 60,
        committed_seconds: (store.minutesTotal - store.minutesLeft) * 60,
        available_seconds: store.minutesLeft * 60,
      },
      calls: [
        {
          submission_id: "00000000-0000-4000-8000-000000000101",
          created_at: now(),
          display_name: "Fictional discovery call",
          seconds: 1_380,
          state: "charged",
        },
        {
          submission_id: "00000000-0000-4000-8000-000000000102",
          created_at: now(),
          display_name: "Fictional follow-up",
          seconds: 900,
          state: "charged",
        },
      ],
      earlier_seconds: 0,
      truncated: false,
    });
  },
  async readSubscriptions(account) {
    await wait();
    const store = read();
    const mine = store.subscriptions.filter((item) => item.account === account);
    const current =
      mine.find((item) =>
        ["active", "past_due", "pending_authorisation"].includes(
          String(item.status),
        ),
      ) ?? null;
    return parseSubscriptions({
      current,
      past: mine.filter((item) => item !== current).slice(0, 10),
    });
  },
  async readOfflinePayment() {
    await wait();
    return parseOfflinePayment({
      enabled: true,
      payee_name: "Authority Closers (fixture)",
      upi_id: "fixture@upi",
      bank: {
        account_name: "Fictional Payee",
        account_number: "000000000000",
        ifsc: "FICT0000000",
        bank_name: "Fictional Bank",
      },
      instructions:
        "Fictional details for layout review. Nothing here can receive money.",
      revision: 1,
    });
  },
  async checkout(request: CheckoutRequest) {
    await wait();
    const store = read();
    const plan = FIXTURE_PLANS.plans.find(
      (item) => item.key === request.planKey,
    );
    if (!plan) throw new BillingError(404, "plan_not_found", "No such plan.");
    if (!plan.prices)
      throw new BillingError(
        409,
        "not_on_sale",
        "This plan is not on sale yet.",
      );
    const orderId = id();
    let order: Record<string, unknown>;
    if (request.kind === "subscription") {
      if (
        liveSubscription(store) &&
        liveSubscription(store)?.account === request.account
      )
        throw new BillingError(
          409,
          "subscription_exists",
          "You already have a plan. Cancel it first to change.",
        );
      const unit =
        request.interval === "month"
          ? plan.prices.monthly_paise
          : plan.prices.yearly_paise;
      order = {
        order_id: orderId,
        kind: "subscription",
        account: request.account,
        status: "awaiting_payment",
        mode: "test",
        amount: {
          minor: unit * request.seats,
          currency: "INR",
          gst_inclusive: true,
        },
        plan_key: plan.key,
        plan_name: plan.name,
        interval: request.interval,
        seats: request.seats,
        pack_key: null,
        minutes: (plan.included_minutes ?? 0) * request.seats,
        subscription_id: id(),
        created_at: now(),
        paid_at: null,
        refund: null,
      };
    } else {
      const pack = plan.top_up_packs.find(
        (item) => item.key === request.packKey,
      );
      if (!pack)
        throw new BillingError(404, "pack_not_found", "No such top-up pack.");
      if (!liveSubscription(store))
        throw new BillingError(
          409,
          "top_up_needs_period",
          "Top-ups need an active plan.",
        );
      order = {
        order_id: orderId,
        kind: "top_up",
        account: request.account,
        status: "awaiting_payment",
        mode: "test",
        amount: {
          minor: pack.price_paise,
          currency: "INR",
          gst_inclusive: true,
        },
        plan_key: plan.key,
        plan_name: plan.name,
        interval: null,
        seats: 1,
        pack_key: pack.key,
        minutes: pack.minutes,
        subscription_id: null,
        created_at: now(),
        paid_at: null,
        refund: null,
      };
    }
    const inclusive = request.planKey === "personal";
    const subtotal = (order.amount as { minor: number }).minor;
    const taxable = inclusive
      ? Math.floor((subtotal * 100 + 59) / 118)
      : subtotal;
    const gst = inclusive
      ? subtotal - taxable
      : Math.floor((taxable * 18 + 50) / 100);
    const total = taxable + gst;
    order.amount = { minor: total, currency: "INR", gst_inclusive: true };
    order.tax = {
      mode: inclusive ? "inclusive" : "exclusive",
      rate_basis_points: 1800,
      taxable_minor: taxable,
      gst_minor: gst,
      total_minor: total,
    };
    store.orders[orderId] = order;
    write(store);
    return parseCheckout({
      order,
      hosted: {
        provider: "fixture",
        kind: "redirect",
        url: `${FIXTURE_PAY_PATH}?order=${orderId}`,
        params: {},
        expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
      },
    });
  },
  async readOrder(orderId): Promise<Order> {
    await wait();
    const order = read().orders[orderId];
    if (!order)
      throw new BillingError(404, "order_not_found", "No such order.");
    return parseOrder(order);
  },
  async verifyOrder(orderId) {
    return fixtureBilling.readOrder(orderId);
  },
  async cancelSubscription(subscriptionId): Promise<Subscription> {
    await wait();
    const store = read();
    const item = store.subscriptions.find(
      (entry) => entry.subscription_id === subscriptionId,
    );
    if (!item)
      throw new BillingError(
        404,
        "subscription_not_found",
        "No such subscription.",
      );
    if (["ended", "cancelled"].includes(String(item.status)))
      throw new BillingError(
        409,
        "subscription_not_active",
        "This plan has already ended.",
      );
    item.cancel_at_period_end = true;
    item.cancel_state = "confirmed";
    write(store);
    return parseSubscriptions({ current: item, past: [] }).current!;
  },
};
