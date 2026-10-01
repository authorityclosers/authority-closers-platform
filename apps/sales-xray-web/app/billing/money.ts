/** Money and minutes as the plans screens show them. Amounts are minor units (paise). */
import type { Interval, Money, Plan, TopUpPack } from "./contract";

const WHOLE = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const FRACTION = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const SYMBOL: Record<string, string> = { INR: "₹", USD: "$" };

/** ₹2,499 from 249900 paise; ₹12.50 when there are paise. */
export function money(minor: number, currency = "INR"): string {
  const symbol = SYMBOL[currency] ?? `${currency} `;
  const units = minor / 100;
  return `${symbol}${Number.isInteger(units) ? WHOLE.format(units) : FRACTION.format(units)}`;
}

export const formatMoney = (amount: Money) =>
  money(amount.minor, amount.currency);

export const count = (value: number) => WHOLE.format(value);

/** The plan's price for one seat and one interval, in paise; null when not on sale. */
export function planPrice(plan: Plan, interval: Interval): number | null {
  if (!plan.prices) return null;
  return interval === "month"
    ? plan.prices.monthlyPaise
    : plan.prices.yearlyPaise;
}

/** How much a year saves against twelve months, in paise; 0 when either is missing. */
export function yearlySaving(plan: Plan): number {
  const monthly = planPrice(plan, "month");
  const yearly = planPrice(plan, "year");
  if (monthly === null || yearly === null) return 0;
  return Math.max(0, monthly * 12 - yearly);
}

export const packPrice = (pack: TopUpPack) => pack.pricePaise;

/** "62 of 100 min" style numbers from seconds. */
export const minutes = (seconds: number) =>
  Math.max(0, Math.floor(seconds / 60));

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});
export function day(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : DAY.format(date);
}
