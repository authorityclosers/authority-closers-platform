/**
 * When the app may ask "how was it?" (owner, 23 Oct 2026: reviews on small
 * moments, never nagging). Pure rules, so they are tested on their own:
 * - at most one question a day and three a week, on this device and across
 *   the person's devices (the server's counts);
 * - each moment has its own rest period, and a moment about one thing (an
 *   update, a purchase, the first import) is asked about once;
 * - "Don't ask about this again" is final for that moment;
 * - an unanswered question counts as asked.
 */

import type { FeedbackState, Moment } from "./feedback-client";

const DAY = 86_400_000;
export const PER_DAY = 1;
export const PER_WEEK = 3;

export const REST_DAYS: Record<Moment, number> = {
  report_read: 14,
  call_outcome: 10,
  first_import: 3650,
  plan_purchase: 30,
  chats_used: 21,
  app_update: 2,
  general: 30,
};

export type LocalAsks = {
  /** When each question was shown on this device. */
  shown: number[];
  /** When each moment was last shown here. */
  moments: Record<string, number>;
  /** Things already asked about here (an update key, an order). */
  subjects: string[];
};

export const NO_ASKS: LocalAsks = { shown: [], moments: {}, subjects: [] };

export type Decision = { ask: true } | { ask: false; why: string };

export function mayAsk(
  moment: Moment,
  subject: string | undefined,
  now: number,
  local: LocalAsks,
  server: FeedbackState | null,
): Decision {
  if (server?.optedOut.includes(moment))
    return { ask: false, why: "opted_out" };
  if (
    subject &&
    (local.subjects.includes(subject) || server?.subjects.includes(subject))
  ) {
    return { ask: false, why: "asked_about_it" };
  }
  const rest = REST_DAYS[moment] * DAY;
  const lastHere = local.moments[moment] ?? 0;
  const lastAnywhere = Date.parse(server?.last[moment] ?? "") || 0;
  if (now - Math.max(lastHere, lastAnywhere) < rest) {
    return { ask: false, why: "resting" };
  }
  const today = local.shown.filter((at) => now - at < DAY).length;
  const week = local.shown.filter((at) => now - at < 7 * DAY).length;
  if (today >= PER_DAY || (server?.askedToday ?? 0) >= PER_DAY) {
    return { ask: false, why: "asked_today" };
  }
  if (week >= PER_WEEK || (server?.askedThisWeek ?? 0) >= PER_WEEK) {
    return { ask: false, why: "asked_this_week" };
  }
  return { ask: true };
}

export function shown(
  local: LocalAsks,
  moment: Moment,
  subject: string | undefined,
  now: number,
): LocalAsks {
  return {
    shown: [...local.shown.filter((at) => now - at < 7 * DAY), now],
    moments: { ...local.moments, [moment]: now },
    subjects: subject
      ? [...local.subjects, subject].slice(-50)
      : local.subjects,
  };
}
