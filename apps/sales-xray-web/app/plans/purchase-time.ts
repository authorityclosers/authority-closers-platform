import { count } from "../billing/money";

/** Whole minutes at purchase displays; seconds still use billing/money.minutes. */
export function purchaseHours(value: number): string | null {
  if (value <= 60) return null;
  const hours = Math.floor(value / 60);
  const remainder = value % 60;
  return remainder > 0 ? `${hours} h ${remainder} min` : `${hours} h`;
}

export function formatPurchaseMinutes(value: number, unit = "min"): string {
  const hours = purchaseHours(value);
  return `${count(value)} ${unit}${hours ? ` (${hours})` : ""}`;
}
