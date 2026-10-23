import { readPlatformJson } from "@ac/operations-web/platform-identity";
import { z } from "zod";

/** Admin → Billing → Revenue: strict read of GET /v1/platform/billing/revenue. */
export const REVENUE_PATH = "/v1/platform/billing/revenue";
const MAX_BYTES = 262144;

export type RevenueMode = "live" | "test";

const instant = z.iso.datetime({ offset: true });
const text = (max: number) => z.string().min(1).max(max);
const minor = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const signedMinor = z
  .number()
  .int()
  .min(-Number.MAX_SAFE_INTEGER)
  .max(Number.MAX_SAFE_INTEGER);
const count = z.number().int().min(0);

const windowSchema = z
  .object({
    key: z.enum(["today", "last_7_days", "this_month", "all_time"]),
    starts_at: instant.nullable(),
    collected_minor: minor,
    taxable_minor: minor,
    gst_minor: minor,
    refunded_minor: minor,
    net_minor: signedMinor,
    payments: count,
    refunds: count,
  })
  .strict();

export const revenueSchema = z
  .object({
    generated_at: instant,
    mode: z.enum(["live", "test"]),
    currency: z.literal("INR"),
    windows: z.array(windowSchema).length(4),
    by_plan: z
      .array(
        z
          .object({
            plan_key: text(40),
            plan_name: text(80),
            kind: z.enum(["subscription", "top_up"]),
            collected_minor: minor,
            taxable_minor: minor,
            payments: count,
          })
          .strict(),
      )
      .max(100),
    recurring: z
      .array(
        z
          .object({
            plan_key: text(40),
            plan_name: text(80),
            interval: z.enum(["month", "year"]),
            subscriptions: count,
            seats: count,
            monthly_taxable_minor: minor,
          })
          .strict(),
      )
      .max(100),
    active_subscriptions: count,
    cancelling_subscriptions: count,
    monthly_recurring_taxable_minor: minor,
    paying_accounts: count,
    personal_accounts: count,
    organisation_accounts: count,
  })
  .strict();

export type Revenue = z.infer<typeof revenueSchema>;
export type RevenueWindow = Revenue["windows"][number];

export class RevenueReadError extends Error {
  constructor(readonly kind: "denied" | "unavailable") {
    super(kind);
  }
}

export async function loadRevenue(
  mode: RevenueMode,
  signal: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<Revenue> {
  let response: Response;
  try {
    response = await fetcher(`${REVENUE_PATH}?mode=${mode}`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
      headers: { accept: "application/json" },
    });
  } catch {
    throw new RevenueReadError("unavailable");
  }
  if (response.status === 401 || response.status === 403)
    throw new RevenueReadError("denied");
  if (!response.ok) throw new RevenueReadError("unavailable");
  const parsed = revenueSchema.safeParse(
    await readPlatformJson(response, MAX_BYTES).catch(() => null),
  );
  if (!parsed.success || parsed.data.mode !== mode)
    throw new RevenueReadError("unavailable");
  return parsed.data;
}
