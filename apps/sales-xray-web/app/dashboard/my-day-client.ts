/**
 * My day (Lead OS team engine, 25 Oct 2026): the seller's work ranked with why,
 * today's numbers and targets, and what to show when today is empty; and the
 * desk's numbers beside today's and the team's open leads, for Home's empty
 * states (owner: "show the next useful data, the last days or weeks").
 */

import { deskRequest, type Desk } from "../leads/leads-client";

export type Metric = "calls" | "connects" | "follow_ups" | "meetings";

export type MetricProgress = {
  metric: Metric;
  period: "day" | "week";
  target: number;
  done: number;
  pace: number;
  expected: number;
  behind: boolean;
  short: number;
};

export type MyDayItem = {
  lead_id: string;
  lead_name: string;
  task_id?: string | null;
  due_at?: string | null;
  score: number;
  /** Why, in words, biggest first: "promised a call back", "2 h overdue". */
  because: string[];
};

export type MyDay = {
  person_id: string;
  do_now: MyDayItem[];
  /** Today's numbers worth showing: no zeros, unless a target makes one count. */
  today: Partial<Record<Metric, number>>;
  progress: MetricProgress[];
  /** Only when nothing is due and nothing is done today. */
  fallback: {
    next_up: { lead_id: string; lead_name: string; at: string; what: string }[];
    week: Partial<Record<Metric, number>>;
    last_week: Partial<Record<Metric, number>>;
    recent: {
      lead_id: string;
      lead_name: string;
      at: string;
      outcome?: string | null;
    }[];
  } | null;
};

export type TeamPool = { open: number; unassigned: number; may_take: boolean };

/** The desk with Home's extras (absent from an older server). */
export type HomeDesk = Desk & {
  numbers_yesterday?: Desk["numbers"] | null;
  numbers_week?: Desk["numbers"] | null;
  team_pool?: TeamPool | null;
};

export const METRIC_WORDS: Record<Metric, string> = {
  calls: "Calls",
  connects: "Connected",
  follow_ups: "Follow-ups done",
  meetings: "Meetings booked",
};

/** The desk's own counts under the same names as My day's. */
export const fromDesk = (
  numbers: Desk["numbers"],
): Partial<Record<Metric, number>> => ({
  calls: numbers.calls,
  connects: numbers.connected,
  follow_ups: numbers.follow_ups_done,
});

const isList = (value: unknown): value is unknown[] => Array.isArray(value);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !isList(value);

function isMyDay(value: unknown): value is MyDay {
  return (
    isRecord(value) &&
    typeof value.person_id === "string" &&
    isList(value.do_now) &&
    value.do_now.every(
      (item) =>
        isRecord(item) &&
        typeof item.lead_id === "string" &&
        typeof item.lead_name === "string" &&
        isList(item.because),
    ) &&
    isRecord(value.today) &&
    isList(value.progress) &&
    (value.fallback === null ||
      value.fallback === undefined ||
      (isRecord(value.fallback) &&
        isList(value.fallback.next_up) &&
        isRecord(value.fallback.week) &&
        isRecord(value.fallback.last_week) &&
        isList(value.fallback.recent)))
  );
}

export async function readMyDay(signal?: AbortSignal): Promise<MyDay> {
  const value = await deskRequest<unknown>("/my-day", { signal });
  if (!isMyDay(value)) throw new Error("My day didn't load.");
  return { ...value, fallback: value.fallback ?? null };
}

/** "promised a call back", "2 h overdue" → "Promised a call back · 2 h overdue". */
export function becauseLine(because: readonly string[]): string {
  const line = because.filter(Boolean).join(" · ");
  return line ? line[0].toUpperCase() + line.slice(1) : "";
}
