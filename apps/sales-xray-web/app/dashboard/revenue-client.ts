/**
 * Revenue targets (owner meeting, 28 Oct 2026; Dipak's idea): a Won deal says what
 * it was worth, each month has the organisation's and each seller's target, and
 * the server works out what it takes to reach the rest. It is the customer's own
 * revenue: our own plan prices never appear here.
 */

import { commandId, deskJson, deskRequest } from "../leads/leads-client";

export type RevenueNeeds = {
  wins: number;
  meetings: number;
  interested: number;
  connected: number;
  calls: number;
  calls_per_day: number;
  working_days_left: number;
  average_deal: number;
  /** Typical rates or the typical deal stood in: too few deals or calls yet. */
  estimate: boolean;
};

export type SellerRevenue = {
  person_id: string;
  name: string;
  target: number | null;
  target_source: "own" | "split" | null;
  won: number;
  deals: number;
  amount_not_set: number;
};

export type Revenue = {
  scope: "mine" | "team";
  month: string;
  currency: string;
  /** How much of the month has gone, 0 to 1. */
  month_gone: number;
  target: number | null;
  target_source: "own" | "split" | "organisation" | "sellers" | null;
  won: number;
  deals: number;
  amount_not_set: number;
  needs: RevenueNeeds | null;
  sellers: SellerRevenue[];
};

export type RevenueTargets = {
  month: string;
  currency: string;
  organisation: number | null;
  sellers: {
    person_id: string;
    name: string;
    own: number | null;
    split: number | null;
  }[];
  sellers_set_own: boolean;
  typical_deal: number | null;
  revision: number;
  can_manage: boolean;
};

export type RevenueBreakdown = {
  days: number;
  currency: string;
  won: number;
  deals: number;
  amount_not_set: number;
  by_seller: { key: string; label: string; won: number; deals: number }[];
  by_side: { key: string; label: string; won: number; deals: number }[];
};

export function readRevenue(scope: "mine" | "team", signal?: AbortSignal) {
  return deskRequest<Revenue>(`/revenue?scope=${scope}`, { signal });
}

export function readRevenueTargets(month?: string, signal?: AbortSignal) {
  return deskRequest<RevenueTargets>(
    month ? `/revenue/targets?month=${month}` : "/revenue/targets",
    { signal },
  );
}

export function saveRevenueTargets(
  month: string,
  change: {
    organisation?: number;
    sellers?: { person_id: string; amount: number }[];
  },
  command = commandId(),
) {
  return deskRequest<RevenueTargets>(
    "/revenue/targets",
    deskJson("PUT", { command_id: command, month, ...change }),
  );
}

export function saveRevenueSettings(
  expectedRevision: number,
  sellersSetOwn: boolean,
  typicalDeal: number | null,
) {
  return deskRequest<RevenueTargets>(
    "/revenue/settings",
    deskJson("PUT", {
      expected_revision: expectedRevision,
      sellers_set_own: sellersSetOwn,
      typical_deal: typicalDeal,
    }),
  );
}

export function readRevenueBreakdown(days: 7 | 30 | 90, signal?: AbortSignal) {
  return deskRequest<RevenueBreakdown>(`/revenue/breakdown?days=${days}`, {
    signal,
  });
}

const WHOLE = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** "₹45,000", "₹5 L", "₹1.2 Cr": short enough for a chip or a bar. */
export function inr(value: number): string {
  const short = (amount: number, unit: string) =>
    `₹${Number(amount.toFixed(amount >= 100 ? 0 : 1))} ${unit}`;
  if (value >= 10_000_000) return short(value / 10_000_000, "Cr");
  if (value >= 100_000) return short(value / 100_000, "L");
  return `₹${WHOLE.format(value)}`;
}

/** The month's name, India time: "October". */
export function monthName(month: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    month: "long",
    timeZone: "Asia/Kolkata",
  }).format(new Date(`${month}T12:00:00+05:30`));
}
