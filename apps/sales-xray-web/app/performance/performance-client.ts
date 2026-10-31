/**
 * The Performance engine's read (Leads redesign, section 6; Dipak's table and
 * the owner's "a great API", 30 Oct 2026): each seller's work done, what was
 * missed and the breaks taken, over today, 7 or 30 days, with Inbound and Cold
 * leads measured apart. Owners and admins get every seller; a seller their own.
 */

import type { HomeBreak } from "../dashboard/my-day-client";
import { deskRequest } from "../leads/leads-client";

/** Effort on Inbound or on Cold leads. */
export type SideEffort = {
  attempted: number;
  connected: number;
  talk_seconds: number;
  /** Call-button dials' time away from the app: an estimate, never talk time. */
  talk_estimated_seconds?: number;
  /** Different leads called, and different leads spoken to. */
  leads_attempted: number;
  reached: number;
  /** Different leads moved to Interested, given a meeting, won. */
  interested: number;
  meetings: number;
  won: number;
  /** Of the leads called, those moved to Interested or Won. */
  worked_interested: number;
  /** Open leads never called. */
  backlog: number;
  /** Leads open now or called in the period (coverage's whole). */
  eligible: number;
  /** Inbound only: median minutes from arriving to the first call. */
  first_call_minutes: number | null;
  /** Open leads more than an hour late, now. */
  late: number;
  /** Calls in nobody took, and those leads nobody reached afterwards. */
  missed_calls: number;
  not_called_back: number;
};

export type SellerEffort = {
  person_id: string;
  name: string;
  inbound: SideEffort;
  cold: SideEffort;
  /** The three longest gaps between calls, longest first. */
  breaks: HomeBreak[];
  /** All the time between calls outside set breaks. */
  unplanned_break_minutes: number;
  /** Today: the first call's start and the last call's end. */
  first_call_at: string | null;
  last_call_at: string | null;
  /** Open tasks more than an hour past their time. */
  tasks_late: number;
  /** Today's connected lead calls with no recording yet. */
  missing_recordings: number;
};

export type Effort = {
  days: number;
  start: string;
  end: string;
  /** Every seller (owners and admins), or the viewer's own. */
  team: boolean;
  sellers: SellerEffort[];
  inbound: SideEffort;
  cold: SideEffort;
  missing_recordings: number;
};

export type EffortDays = 1 | 7 | 30;

export function readEffort(days: EffortDays, signal?: AbortSignal) {
  return deskRequest<Effort>(`/performance/sellers?days=${days}`, { signal });
}
