/**
 * Billing contract C1 (CTO, 30 Sep 2026, AUT-560) and the plans catalogue
 * read (AUT-418), parsed strictly: a field the contract does not name is
 * refused, so a server change needs a contract revision before it can reach
 * a screen. Nothing here grants access. Minutes and the plan in effect come
 * only from GET /v1/me/plan and GET /v1/me/usage; order and subscription
 * states are display only.
 */

export class ContractError extends Error {
  constructor(
    readonly path: string,
    reason: string,
  ) {
    super(`${path}: ${reason}`);
  }
}

type Raw = Record<string, unknown>;

function object(value: unknown, path: string, keys: readonly string[]): Raw {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ContractError(path, "expected an object");
  const raw = value as Raw;
  for (const key of Object.keys(raw))
    if (!keys.includes(key))
      throw new ContractError(`${path}.${key}`, "unknown field");
  return raw;
}
function text(raw: Raw, key: string, path: string): string {
  const value = raw[key];
  if (typeof value !== "string")
    throw new ContractError(`${path}.${key}`, "expected text");
  return value;
}
function textOrNull(raw: Raw, key: string, path: string): string | null {
  const value = raw[key];
  if (value === null || value === undefined) return null;
  if (typeof value !== "string")
    throw new ContractError(`${path}.${key}`, "expected text or null");
  return value;
}
function integer(raw: Raw, key: string, path: string): number {
  const value = raw[key];
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new ContractError(`${path}.${key}`, "expected a whole number");
  return value;
}
function integerOrNull(raw: Raw, key: string, path: string): number | null {
  const value = raw[key];
  if (value === null || value === undefined) return null;
  return integer(raw, key, path);
}
function bool(raw: Raw, key: string, path: string): boolean {
  const value = raw[key];
  if (typeof value !== "boolean")
    throw new ContractError(`${path}.${key}`, "expected true or false");
  return value;
}
function oneOf<T extends string>(
  raw: Raw,
  key: string,
  path: string,
  allowed: readonly T[],
): T {
  const value = raw[key];
  if (typeof value !== "string" || !allowed.includes(value as T))
    throw new ContractError(
      `${path}.${key}`,
      `expected one of ${allowed.join(", ")}`,
    );
  return value as T;
}
function list(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new ContractError(path, "expected a list");
  return value;
}

/* ---------- Plans catalogue: GET /v1/plans (AUT-418) ---------- */

export type PlanStatus = "coming_soon" | "active";
export type PlanPrices = {
  monthlyPaise: number | null;
  yearlyPaise: number | null;
  monthlyCents: number | null;
  yearlyCents: number | null;
};
export type TopUpPack = {
  key: string;
  minutes: number;
  validityRule: "billing_year_end";
  pricePaise: number | null;
  priceCents: number | null;
};
export type Plan = {
  key: string;
  name: string;
  audience: string;
  status: PlanStatus;
  /** Present only when the plan is on sale. */
  prices: PlanPrices | null;
  includedMinutes: number | null;
  seatMin: number | null;
  seatMax: number | null;
  perSeat?: boolean;
  longestCallMinutes: number | null;
  retentionDays: number | null;
  rolloverMonths: number | null;
  featureKeys: string[];
  topUpPacks: TopUpPack[];
  sortOrder: number;
  revision: number;
};

const PLAN_KEYS = [
  "id",
  "key",
  "name",
  "audience",
  "status",
  "prices",
  "included_minutes",
  "seat_min",
  "seat_max",
  "per_seat",
  "longest_call_minutes",
  "retention_days",
  "rollover_months",
  "feature_keys",
  "top_up_packs",
  "sort_order",
  "revision",
  "created_at",
  "updated_at",
] as const;

export function parsePlan(value: unknown, path = "plan"): Plan {
  const raw = object(value, path, PLAN_KEYS);
  const prices =
    raw.prices === null || raw.prices === undefined
      ? null
      : (() => {
          const p = object(raw.prices, `${path}.prices`, [
            "monthly_paise",
            "yearly_paise",
            "monthly_cents",
            "yearly_cents",
          ]);
          return {
            monthlyPaise: integerOrNull(p, "monthly_paise", `${path}.prices`),
            yearlyPaise: integerOrNull(p, "yearly_paise", `${path}.prices`),
            monthlyCents: integerOrNull(p, "monthly_cents", `${path}.prices`),
            yearlyCents: integerOrNull(p, "yearly_cents", `${path}.prices`),
          };
        })();
  return {
    key: text(raw, "key", path),
    name: text(raw, "name", path),
    audience: text(raw, "audience", path),
    status: oneOf(raw, "status", path, ["coming_soon", "active"]),
    prices,
    includedMinutes: integerOrNull(raw, "included_minutes", path),
    seatMin: integerOrNull(raw, "seat_min", path),
    seatMax: integerOrNull(raw, "seat_max", path),
    perSeat:
      raw.per_seat === undefined ? undefined : bool(raw, "per_seat", path),
    longestCallMinutes: integerOrNull(raw, "longest_call_minutes", path),
    retentionDays: integerOrNull(raw, "retention_days", path),
    rolloverMonths: integerOrNull(raw, "rollover_months", path),
    featureKeys: list(raw.feature_keys ?? [], `${path}.feature_keys`).map(
      (item, index) => {
        if (typeof item !== "string")
          throw new ContractError(
            `${path}.feature_keys[${index}]`,
            "expected text",
          );
        return item;
      },
    ),
    topUpPacks: list(raw.top_up_packs ?? [], `${path}.top_up_packs`).map(
      (item, index) => {
        const packPath = `${path}.top_up_packs[${index}]`;
        const pack = object(item, packPath, [
          "key",
          "minutes",
          "validity_rule",
          "price_paise",
          "price_cents",
        ]);
        return {
          key: text(pack, "key", packPath),
          minutes: integer(pack, "minutes", packPath),
          validityRule: oneOf(pack, "validity_rule", packPath, [
            "billing_year_end",
          ]),
          pricePaise: integerOrNull(pack, "price_paise", packPath),
          priceCents: integerOrNull(pack, "price_cents", packPath),
        };
      },
    ),
    sortOrder: integerOrNull(raw, "sort_order", path) ?? 0,
    revision: integerOrNull(raw, "revision", path) ?? 1,
  };
}

export function parsePlans(value: unknown): Plan[] {
  const raw = object(value, "plans", ["plans"]);
  return list(raw.plans, "plans.plans")
    .map((item, index) => parsePlan(item, `plans[${index}]`))
    .sort((a, b) => a.sortOrder - b.sortOrder || a.key.localeCompare(b.key));
}

/** A plan can be bought only when it is on sale and carries a price. */
export function onSale(plan: Plan): boolean {
  return plan.status === "active" && plan.prices !== null;
}

/* ---------- Plan in effect and usage: /v1/me/plan, /v1/me/usage (AUT-417) ---------- */

export type Allowance = {
  allowanceSeconds: number;
  committedSeconds: number;
  availableSeconds: number;
  unlimited: boolean;
};
export type MePlan = {
  plan: { key: string; name: string };
  allowance: Allowance;
  longestCallSeconds: number;
};
export type UsageCall = {
  submissionId: string;
  createdAt: string;
  displayName: string;
  seconds: number;
  state: "reserved" | "charged" | "not_charged";
};
export type Usage = {
  allowance: Allowance;
  calls: UsageCall[];
  earlierSeconds: number;
  truncated: boolean;
};

function parseAllowance(value: unknown, path: string): Allowance {
  const raw = object(value, path, [
    "allowance_seconds",
    "committed_seconds",
    "available_seconds",
    "unlimited",
  ]);
  return {
    allowanceSeconds: integer(raw, "allowance_seconds", path),
    committedSeconds: integer(raw, "committed_seconds", path),
    availableSeconds: integer(raw, "available_seconds", path),
    unlimited: raw.unlimited === true,
  };
}

export function parseMePlan(value: unknown): MePlan {
  const raw = object(value, "me.plan", [
    "plan",
    "allowance",
    "longest_call_seconds",
  ]);
  const plan = object(raw.plan, "me.plan.plan", ["key", "name"]);
  return {
    plan: {
      key: text(plan, "key", "me.plan.plan"),
      name: text(plan, "name", "me.plan.plan"),
    },
    allowance: parseAllowance(raw.allowance, "me.plan.allowance"),
    longestCallSeconds: integer(raw, "longest_call_seconds", "me.plan"),
  };
}

export function parseUsage(value: unknown): Usage {
  const raw = object(value, "me.usage", [
    "allowance",
    "calls",
    "earlier_seconds",
    "truncated",
  ]);
  return {
    allowance: parseAllowance(raw.allowance, "me.usage.allowance"),
    calls: list(raw.calls, "me.usage.calls").map((item, index) => {
      const path = `me.usage.calls[${index}]`;
      const call = object(item, path, [
        "submission_id",
        "created_at",
        "display_name",
        "seconds",
        "state",
      ]);
      return {
        submissionId: text(call, "submission_id", path),
        createdAt: text(call, "created_at", path),
        displayName: text(call, "display_name", path),
        seconds: integer(call, "seconds", path),
        state: oneOf(call, "state", path, [
          "reserved",
          "charged",
          "not_charged",
        ]),
      };
    }),
    earlierSeconds: integer(raw, "earlier_seconds", "me.usage"),
    truncated: bool(raw, "truncated", "me.usage"),
  };
}

/* ---------- Contract C1: checkout, orders, subscriptions, refunds ---------- */

export type Money = { minor: number; currency: string; gstInclusive: boolean };
export type Account = "personal" | "organisation";
export type Interval = "month" | "year";
export type Mode = "test" | "live";
export type OrderStatus =
  | "awaiting_payment"
  | "confirming"
  | "paid"
  | "failed"
  | "expired"
  | "needs_review";
export type RefundState =
  | "available"
  | "pending"
  | "refunded"
  | "refused"
  | "unavailable";
export type Refund = {
  paymentId: string;
  refundableUntil: string | null;
  state: RefundState;
  reasonCode: "used" | "window_closed" | null;
};
export type Order = {
  orderId: string;
  kind: "subscription" | "top_up";
  account: Account;
  status: OrderStatus;
  mode: Mode;
  amount: Money;
  tax?: Tax | null;
  planKey: string;
  planName: string;
  interval: Interval | null;
  seats: number;
  packKey: string | null;
  minutes: number;
  subscriptionId: string | null;
  createdAt: string;
  paidAt: string | null;
  refund: Refund | null;
};
export type Tax = {
  mode: "inclusive" | "exclusive";
  rateBasisPoints: number;
  taxableMinor: number;
  gstMinor: number;
  totalMinor: number;
};
export type HostedKind = "client_sdk" | "redirect" | "form_post";
export type Hosted = {
  provider: string;
  kind: HostedKind;
  url: string | null;
  /** Public values only, never a secret. */
  params: Record<string, string>;
  expiresAt: string | null;
};
export type Checkout = { order: Order; hosted: Hosted };
export type SubscriptionStatus =
  | "pending_authorisation"
  | "active"
  | "past_due"
  | "halted"
  | "cancelled"
  | "ended";
export type Subscription = {
  subscriptionId: string;
  account: Account;
  planKey: string;
  planName: string;
  interval: Interval;
  seats: number;
  amount: Money;
  mode: Mode;
  status: SubscriptionStatus;
  currentPeriod: { start: string; end: string } | null;
  renewsAt: string | null;
  cancelAtPeriodEnd: boolean;
  cancelState: "none" | "requested" | "confirmed";
  renewalNeedsCustomerApproval: boolean;
  createdAt: string;
};
export type Subscriptions = {
  current: Subscription | null;
  past: Subscription[];
};
export type OfflinePayment = {
  enabled: boolean;
  payeeName: string | null;
  upiId: string | null;
  bank: {
    accountName: string;
    accountNumber: string;
    ifsc: string;
    bankName: string;
  } | null;
  instructions: string | null;
  revision: number;
};
export type Problem = {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
};

function parseMoney(value: unknown, path: string): Money {
  const raw = object(value, path, ["minor", "currency", "gst_inclusive"]);
  return {
    minor: integer(raw, "minor", path),
    currency: text(raw, "currency", path),
    gstInclusive: bool(raw, "gst_inclusive", path),
  };
}

export function parseRefund(value: unknown, path = "refund"): Refund | null {
  if (value === null || value === undefined) return null;
  const raw = object(value, path, [
    "payment_id",
    "refundable_until",
    "state",
    "reason_code",
  ]);
  const reason = raw.reason_code;
  if (
    reason !== null &&
    reason !== undefined &&
    reason !== "used" &&
    reason !== "window_closed"
  )
    throw new ContractError(
      `${path}.reason_code`,
      "expected used, window_closed or null",
    );
  return {
    paymentId: text(raw, "payment_id", path),
    refundableUntil: textOrNull(raw, "refundable_until", path),
    state: oneOf(raw, "state", path, [
      "available",
      "pending",
      "refunded",
      "refused",
      "unavailable",
    ]),
    reasonCode: (reason ?? null) as Refund["reasonCode"],
  };
}

export function parseOrder(value: unknown, path = "order"): Order {
  const raw = object(value, path, [
    "order_id",
    "kind",
    "account",
    "status",
    "mode",
    "amount",
    "tax",
    "plan_key",
    "plan_name",
    "interval",
    "seats",
    "pack_key",
    "minutes",
    "subscription_id",
    "created_at",
    "paid_at",
    "refund",
  ]);
  const interval = raw.interval;
  if (
    interval !== null &&
    interval !== undefined &&
    interval !== "month" &&
    interval !== "year"
  )
    throw new ContractError(`${path}.interval`, "expected month, year or null");
  const amount = parseMoney(raw.amount, `${path}.amount`);
  const tax = raw.tax == null ? null : parseTax(raw.tax, `${path}.tax`);
  if (tax && tax.totalMinor !== amount.minor)
    throw new ContractError(
      `${path}.tax.total_minor`,
      "must equal the charged amount",
    );
  return {
    orderId: text(raw, "order_id", path),
    kind: oneOf(raw, "kind", path, ["subscription", "top_up"]),
    account: oneOf(raw, "account", path, ["personal", "organisation"]),
    status: oneOf(raw, "status", path, [
      "awaiting_payment",
      "confirming",
      "paid",
      "failed",
      "expired",
      "needs_review",
    ]),
    mode: oneOf(raw, "mode", path, ["test", "live"]),
    amount,
    tax,
    planKey: text(raw, "plan_key", path),
    planName: text(raw, "plan_name", path),
    interval: (interval ?? null) as Interval | null,
    seats: integer(raw, "seats", path),
    packKey: textOrNull(raw, "pack_key", path),
    minutes: integer(raw, "minutes", path),
    subscriptionId: textOrNull(raw, "subscription_id", path),
    createdAt: text(raw, "created_at", path),
    paidAt: textOrNull(raw, "paid_at", path),
    refund: parseRefund(raw.refund, `${path}.refund`),
  };
}

function parseTax(value: unknown, path: string): Tax {
  const raw = object(value, path, [
    "mode",
    "rate_basis_points",
    "taxable_minor",
    "gst_minor",
    "total_minor",
  ]);
  const read = (key: string) => {
    const value = integer(raw, key, path);
    if (!Number.isSafeInteger(value) || value < 0)
      throw new ContractError(
        `${path}.${key}`,
        "expected nonnegative safe integer",
      );
    return value;
  };
  const tax = {
    mode: oneOf(raw, "mode", path, ["inclusive", "exclusive"]),
    rateBasisPoints: read("rate_basis_points"),
    taxableMinor: read("taxable_minor"),
    gstMinor: read("gst_minor"),
    totalMinor: read("total_minor"),
  };
  if (tax.taxableMinor + tax.gstMinor !== tax.totalMinor)
    throw new ContractError(path, "taxable value plus GST must equal total");
  return tax;
}

export function parseCheckout(value: unknown): Checkout {
  const raw = object(value, "checkout", ["order", "hosted"]);
  const hosted = object(raw.hosted, "checkout.hosted", [
    "provider",
    "kind",
    "url",
    "params",
    "expires_at",
  ]);
  const params = object(
    hosted.params ?? {},
    "checkout.hosted.params",
    Object.keys((hosted.params as Raw) ?? {}),
  );
  const flat: Record<string, string> = {};
  for (const [key, item] of Object.entries(params)) {
    if (typeof item !== "string")
      throw new ContractError(`checkout.hosted.params.${key}`, "expected text");
    flat[key] = item;
  }
  return {
    order: parseOrder(raw.order, "checkout.order"),
    hosted: {
      provider: text(hosted, "provider", "checkout.hosted"),
      kind: oneOf(hosted, "kind", "checkout.hosted", [
        "client_sdk",
        "redirect",
        "form_post",
      ]),
      url: textOrNull(hosted, "url", "checkout.hosted"),
      params: flat,
      expiresAt: textOrNull(hosted, "expires_at", "checkout.hosted"),
    },
  };
}

export function parseSubscription(
  value: unknown,
  path = "subscription",
): Subscription {
  const raw = object(value, path, [
    "subscription_id",
    "account",
    "plan_key",
    "plan_name",
    "interval",
    "seats",
    "amount",
    "mode",
    "status",
    "current_period",
    "renews_at",
    "cancel_at_period_end",
    "cancel_state",
    "renewal_needs_customer_approval",
    "created_at",
  ]);
  const period =
    raw.current_period === null || raw.current_period === undefined
      ? null
      : (() => {
          const p = object(raw.current_period, `${path}.current_period`, [
            "start",
            "end",
          ]);
          return {
            start: text(p, "start", `${path}.current_period`),
            end: text(p, "end", `${path}.current_period`),
          };
        })();
  return {
    subscriptionId: text(raw, "subscription_id", path),
    account: oneOf(raw, "account", path, ["personal", "organisation"]),
    planKey: text(raw, "plan_key", path),
    planName: text(raw, "plan_name", path),
    interval: oneOf(raw, "interval", path, ["month", "year"]),
    seats: integer(raw, "seats", path),
    amount: parseMoney(raw.amount, `${path}.amount`),
    mode: oneOf(raw, "mode", path, ["test", "live"]),
    status: oneOf(raw, "status", path, [
      "pending_authorisation",
      "active",
      "past_due",
      "halted",
      "cancelled",
      "ended",
    ]),
    currentPeriod: period,
    renewsAt: textOrNull(raw, "renews_at", path),
    cancelAtPeriodEnd: bool(raw, "cancel_at_period_end", path),
    cancelState: oneOf(raw, "cancel_state", path, [
      "none",
      "requested",
      "confirmed",
    ]),
    renewalNeedsCustomerApproval: bool(
      raw,
      "renewal_needs_customer_approval",
      path,
    ),
    createdAt: text(raw, "created_at", path),
  };
}

export function parseSubscriptions(value: unknown): Subscriptions {
  const raw = object(value, "subscriptions", ["current", "past"]);
  return {
    current:
      raw.current === null || raw.current === undefined
        ? null
        : parseSubscription(raw.current, "subscriptions.current"),
    past: list(raw.past ?? [], "subscriptions.past").map((item, index) =>
      parseSubscription(item, `subscriptions.past[${index}]`),
    ),
  };
}

export function parseOfflinePayment(value: unknown): OfflinePayment {
  const raw = object(value, "offline_payment", [
    "enabled",
    "payee_name",
    "upi_id",
    "bank",
    "instructions",
    "revision",
  ]);
  const bank =
    raw.bank === null || raw.bank === undefined
      ? null
      : (() => {
          const b = object(raw.bank, "offline_payment.bank", [
            "account_name",
            "account_number",
            "ifsc",
            "bank_name",
          ]);
          return {
            accountName: text(b, "account_name", "offline_payment.bank"),
            accountNumber: text(b, "account_number", "offline_payment.bank"),
            ifsc: text(b, "ifsc", "offline_payment.bank"),
            bankName: text(b, "bank_name", "offline_payment.bank"),
          };
        })();
  return {
    enabled: bool(raw, "enabled", "offline_payment"),
    payeeName: textOrNull(raw, "payee_name", "offline_payment"),
    upiId: textOrNull(raw, "upi_id", "offline_payment"),
    bank,
    instructions: textOrNull(raw, "instructions", "offline_payment"),
    revision: integer(raw, "revision", "offline_payment"),
  };
}

/** An RFC 9457 problem body; anything else is "no problem body". */
export function parseProblem(value: unknown): Problem | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Raw;
  if (typeof raw.code !== "string" || typeof raw.status !== "number")
    return null;
  return {
    type: typeof raw.type === "string" ? raw.type : "about:blank",
    title: typeof raw.title === "string" ? raw.title : "",
    status: raw.status,
    detail: typeof raw.detail === "string" ? raw.detail : "",
    code: raw.code,
  };
}
