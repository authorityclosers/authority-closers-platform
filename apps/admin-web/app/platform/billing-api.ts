import { readPlatformJson } from "@ac/operations-web/platform-identity";
import { z } from "zod";

/** Admin → Billing (AUT-879): strict read of GET /v1/platform/billing. */
export const BILLING_PATH = "/v1/platform/billing";
const MAX_ROWS = 100;
const MAX_BYTES = 1048576;

const instant = z.iso.datetime({ offset: true });
const text = (max: number) => z.string().min(1).max(max);
const currency = z.string().regex(/^[A-Z]{3}$/);
const minor = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const customerSchema = z
  .object({
    account_id: z.uuid(),
    kind: z.enum(["personal", "organisation"]),
    name: text(200).nullable(),
    email: text(320).nullable(),
  })
  .strict();
const orderSchema = z
  .object({
    order_id: z.uuid(),
    order_ref: text(25),
    kind: z.enum(["subscription", "top_up"]),
    mode: z.enum(["test", "live"]),
    provider: text(32),
    provider_order_ref: text(64).nullable(),
    customer: customerSchema,
    plan_key: text(40),
    plan_name: text(80),
    interval: z.enum(["month", "year"]).nullable(),
    seats: z.number().int().min(1),
    minutes: z.number().int().min(0),
    amount_minor: minor,
    currency,
    gst_inclusive: z.boolean(),
    status: z.enum([
      "awaiting_payment",
      "confirming",
      "paid",
      "failed",
      "expired",
      "needs_review",
    ]),
    created_at: instant,
  })
  .strict();
const refundStateSchema = z.enum([
  "available",
  "pending",
  "refunded",
  "refused",
  "unavailable",
]);
const paymentSchema = z
  .object({
    payment_id: z.string().regex(/^[A-Za-z0-9_-]{1,64}$/),
    event: z.enum([
      "payment.captured",
      "payment.failed",
      "subscription.charged",
    ]),
    provider: text(32),
    order_id: z.uuid().nullable(),
    order_ref: text(25).nullable(),
    subscription_id: z.uuid().nullable(),
    customer: customerSchema.nullable(),
    plan_name: text(80).nullable(),
    seats: z.number().int().min(1).nullable(),
    amount_minor: minor.nullable(),
    currency: currency.nullable(),
    gst_inclusive: z.boolean().nullable(),
    verified_at: instant,
    refund_state: refundStateSchema.nullable(),
    refundable_until: instant.nullable(),
  })
  .strict();
const refundSchema = z
  .object({
    payment_id: z.string().regex(/^[A-Za-z0-9_-]{1,64}$/),
    order_id: z.uuid(),
    customer: customerSchema.nullable(),
    state: z.enum(["pending", "refunded", "refused"]),
    amount_minor: minor,
    currency,
    reason: text(500),
    provider_refund_ref: text(64).nullable(),
    requested_at: instant,
    updated_at: instant,
  })
  .strict();
const subscriptionSchema = z
  .object({
    subscription_id: z.uuid(),
    mode: z.enum(["test", "live"]),
    provider: text(32),
    provider_subscription_ref: text(64).nullable(),
    customer: customerSchema,
    plan_key: text(40),
    plan_name: text(80),
    interval: z.enum(["month", "year"]),
    seats: z.number().int().min(1),
    amount_minor: minor,
    currency,
    gst_inclusive: z.boolean(),
    status: z.enum([
      "pending_authorisation",
      "active",
      "past_due",
      "halted",
      "cancelled",
      "ended",
    ]),
    cancel_state: z.enum(["none", "requested", "confirmed"]),
    cancel_at_period_end: z.boolean(),
    current_period_end: instant.nullable(),
    renews_at: instant.nullable(),
    created_at: instant,
  })
  .strict()
  .refine(
    (row) =>
      row.cancel_at_period_end === (row.cancel_state !== "none") &&
      (row.renews_at === null || !row.cancel_at_period_end),
  );
const unique = <T>(rows: readonly T[], key: (row: T) => string) =>
  new Set(rows.map(key)).size === rows.length;

export const staffBillingSchema = z
  .object({
    generated_at: instant,
    page_limit: z.literal(MAX_ROWS),
    orders: z.array(orderSchema).max(MAX_ROWS),
    payments: z.array(paymentSchema).max(MAX_ROWS),
    refunds: z.array(refundSchema).max(MAX_ROWS),
    subscriptions: z.array(subscriptionSchema).max(MAX_ROWS),
  })
  .strict()
  .refine(
    (value) =>
      unique(value.orders, (row) => row.order_id) &&
      unique(value.payments, (row) => row.payment_id) &&
      unique(value.refunds, (row) => row.order_id + ":" + row.payment_id) &&
      unique(value.subscriptions, (row) => row.subscription_id),
  );
export type StaffBilling = z.infer<typeof staffBillingSchema>;
export type BillingPayment = StaffBilling["payments"][number];

export class BillingReadError extends Error {
  constructor(readonly kind: "denied" | "unavailable") {
    super(kind);
  }
}

export async function loadStaffBilling(
  signal: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<StaffBilling> {
  let response: Response;
  try {
    response = await fetcher(BILLING_PATH, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
      headers: { accept: "application/json" },
    });
  } catch {
    throw new BillingReadError("unavailable");
  }
  if (response.status === 401 || response.status === 403)
    throw new BillingReadError("denied");
  if (!response.ok) throw new BillingReadError("unavailable");
  const parsed = staffBillingSchema.safeParse(
    await readPlatformJson(response, MAX_BYTES).catch(() => null),
  );
  if (!parsed.success) throw new BillingReadError("unavailable");
  return parsed.data;
}

const refundResultSchema = z
  .object({
    refund: z
      .object({
        payment_id: z.string(),
        refundable_until: instant.nullable(),
        state: refundStateSchema,
        reason_code: z.enum(["used", "window_closed"]).nullable(),
      })
      .strict(),
  })
  .strict();
const problemSchema = z.object({ detail: z.string().min(1).max(1000) });

export type RefundOutcome =
  | { ok: true; state: z.infer<typeof refundStateSchema> }
  | { ok: false; reason: string };

/** The staff refund command; its rule, not this page, decides. */
export async function requestRefund(
  paymentId: string,
  reason: string,
  idempotencyKey: string,
  signal: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<RefundOutcome> {
  let response: Response;
  try {
    response = await fetcher(
      BILLING_PATH + "/payments/" + encodeURIComponent(paymentId) + "/refund",
      {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]),
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          "idempotency-key": idempotencyKey,
        },
        body: JSON.stringify({ reason }),
      },
    );
  } catch {
    return {
      ok: false,
      reason:
        "The refund request was not confirmed. Refresh before trying again.",
    };
  }
  if (response.status === 403)
    return {
      ok: false,
      reason:
        "Your billing assignment could not be confirmed. Reload to check your account.",
    };
  const body = await readPlatformJson(response).catch(() => null);
  if (response.ok) {
    const result = refundResultSchema.safeParse(body);
    if (result.success && result.data.refund.payment_id === paymentId)
      return { ok: true, state: result.data.refund.state };
    return {
      ok: false,
      reason: "The refund answer could not be read. Refresh to see its state.",
    };
  }
  const problem = problemSchema.safeParse(body);
  return {
    ok: false,
    reason: problem.success
      ? problem.data.detail
      : `The refund was refused (HTTP ${response.status}).`,
  };
}
