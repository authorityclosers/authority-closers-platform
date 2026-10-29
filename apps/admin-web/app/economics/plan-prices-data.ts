/**
 * Plan prices (owner, 29 Oct 2026: "Admin price editor"): GET /v1/admin/plan-prices. The
 * screen's shape and its reader. Pure and server-safe: the console page normalizes on the
 * server, so this must not live in the "use client" panel (a server call into a client
 * module throws, and the panel showed "doesn't understand").
 */
import { z } from "zod";

const paise = z.number().int().nonnegative();
const plan = z
  .object({
    key: z.string(),
    name: z.string(),
    status: z.enum(["draft", "coming_soon", "active", "retired"]),
    revision: z.number().int().positive(),
    per_seat: z.boolean(),
    prices_include_gst: z.boolean(),
    monthly_price_paise: paise.nullable(),
    yearly_price_paise: paise.nullable(),
    editable: z.boolean(),
  })
  .strict();
const change = z
  .object({
    plan_key: z.string(),
    plan_revision: z.number().int().positive(),
    monthly_price_paise: paise.nullable(),
    yearly_price_paise: paise.nullable(),
    previous_monthly_price_paise: paise.nullable(),
    previous_yearly_price_paise: paise.nullable(),
    reason: z.string(),
    changed_by: z.string().nullable(),
    changed_at: z.string(),
  })
  .strict();
export const planPrices = z
  .object({
    environment: z.string(),
    can_change: z.boolean(),
    plans: z.array(plan).max(50),
    history: z.array(change).max(20),
  })
  .strict();
export type PlanPrices = z.infer<typeof planPrices>;
export type PlanRow = z.infer<typeof plan>;

const rows = <T>(value: unknown, row: z.ZodType<T>): T[] =>
  Array.isArray(value)
    ? value.flatMap((item) => {
        const parsed = row.safeParse(item);
        return parsed.success ? [parsed.data] : [];
      })
    : [];

/** The screen's shape; a missing or odd field never crashes the page (rows that fail drop). */
export function normalizePlanPrices(raw: unknown): PlanPrices {
  const parsed = planPrices.safeParse(raw);
  if (parsed.success) return parsed.data;
  const value: Record<string, unknown> =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    environment:
      typeof value.environment === "string"
        ? value.environment
        : "this environment",
    can_change: value.can_change === true,
    plans: rows(value.plans, plan),
    history: rows(value.history, change),
  };
}
