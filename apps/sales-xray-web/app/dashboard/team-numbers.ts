/**
 * One way to count the team's day, for Home's Team today and for Growth
 * (round 2, board 6, 20 Nov 2026: Home said 75 calls and 25 without a
 * recording, Growth 185 and 62, because one counted Inbound only and neither
 * said so; Home's speed to lead was 7 days, Growth's today). Both read the
 * Performance engine (GET /performance/sellers) and count with these: all
 * leads unless Inbound is picked, and the words always say which.
 */

import type {
  Effort,
  SellerEffort,
  SideEffort,
} from "../performance/performance-client";

/** All leads (Inbound and Cold together), or Inbound alone. */
export type Scope = "all" | "inbound";

type Sides = { inbound: SideEffort; cold: SideEffort };
type Summed =
  | "attempted"
  | "connected"
  | "talk_seconds"
  | "talk_estimated_seconds"
  | "interested"
  | "leads_attempted"
  | "reached"
  | "meetings"
  | "late"
  | "backlog"
  | "missed_calls"
  | "not_called_back";

/** Inbound and Cold together. */
export const both = (sides: Sides, key: Summed): number =>
  (sides.inbound[key] ?? 0) + (sides.cold[key] ?? 0);

/** One figure on the scope picked. */
export const counted = (sides: Sides, key: Summed, scope: Scope): number =>
  scope === "inbound" ? (sides.inbound[key] ?? 0) : both(sides, key);

/** Today's connected calls with no recording yet, on the scope picked; an
 *  older server without the Inbound count gives its total. */
export function noRecording(
  from: Sides & { missing_recordings: number },
  scope: Scope,
): number {
  return scope === "inbound"
    ? (from.inbound.missing_recordings ?? from.missing_recordings)
    : from.missing_recordings;
}

/** Speed to lead: new Inbound leads' median minutes to the first call. Cold
 *  leads aren't enquiries, so it is Inbound's on every scope. */
export const speedToLead = (sides: Sides): number | null =>
  sides.inbound.first_call_minutes;

export type DayFigures = {
  calls: number;
  connected: number;
  talkSeconds: number;
  talkEstimatedSeconds: number;
  speed: number | null;
  noRecording: number;
  late: number;
  backlog: number;
  notCalledBack: number;
};

/** The team's day, or one seller's, counted one way. */
export function dayFigures(
  from: Sides & { missing_recordings: number },
  scope: Scope,
): DayFigures {
  return {
    calls: counted(from, "attempted", scope),
    connected: counted(from, "connected", scope),
    talkSeconds: counted(from, "talk_seconds", scope),
    talkEstimatedSeconds: counted(from, "talk_estimated_seconds", scope),
    speed: speedToLead(from),
    noRecording: noRecording(from, scope),
    late: counted(from, "late", scope),
    backlog: counted(from, "backlog", scope),
    // Missed calls are Inbound's: someone rang us.
    notCalledBack: from.inbound.not_called_back,
  };
}

export const teamFigures = (effort: Effort, scope: Scope) =>
  dayFigures(effort, scope);

export const sellerFigures = (seller: SellerEffort, scope: Scope) =>
  dayFigures(seller, scope);

/** What a number counts, said beside it: "All leads" or "Inbound leads". */
export const SCOPE_WORDS: Record<Scope, string> = {
  all: "All leads",
  inbound: "Inbound leads",
};
