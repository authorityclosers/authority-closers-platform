/**
 * Feedback from people using Sales X-Ray (owner, 23 Oct 2026): the page's
 * filters (in the address), labels and the normalizer for GET
 * /v1/admin/feedback. Pure.
 */
import { read } from "../lib/read";

export const MOMENTS = [
  "report_read",
  "call_outcome",
  "first_import",
  "plan_purchase",
  "chats_used",
  "app_update",
  "general",
] as const;
export type Moment = (typeof MOMENTS)[number];

export const MOMENT_LABEL: Record<string, string> = {
  report_read: "After reading a Report",
  call_outcome: "After logging a call",
  first_import: "After the first import",
  plan_purchase: "After buying a plan",
  chats_used: "After using Chats",
  app_update: "After an update",
  general: "In general",
};

export const DAYS = [7, 30, 90] as const;
export type Days = (typeof DAYS)[number];

export type FeedbackFilters = { days: Days; moment?: Moment };

type Params = Record<string, string | string[] | undefined>;
const one = (value: string | string[] | undefined) =>
  Array.isArray(value) ? value[0] : value;

export function feedbackFilters(params: Params): FeedbackFilters {
  const days = Number(one(params.days));
  const moment = one(params.moment);
  return {
    days: (DAYS as readonly number[]).includes(days) ? (days as Days) : 30,
    ...(MOMENTS.includes(moment as Moment) ? { moment: moment as Moment } : {}),
  };
}

export function feedbackQuery(
  filters: FeedbackFilters,
  omit: string[] = [],
): string {
  const query = new URLSearchParams();
  if (filters.days !== 30 && !omit.includes("days"))
    query.set("days", String(filters.days));
  if (filters.moment && !omit.includes("moment"))
    query.set("moment", filters.moment);
  return query.toString();
}

export function feedbackApiPath(filters: FeedbackFilters): string {
  const query = new URLSearchParams({ days: String(filters.days) });
  if (filters.moment) query.set("moment", filters.moment);
  return `/v1/admin/feedback?${query.toString()}`;
}

export type Counts = {
  good: number;
  okay: number;
  bad: number;
  dismissed: number;
  optedOut: number;
  comments: number;
};

export type FeedbackSummary = {
  days: number;
  moments: (Counts & { moment: string })[];
  releases: (Counts & { release: string; lastAt: string | null })[];
  byDay: (Counts & { day: string })[];
  recent: {
    id: string;
    createdAt: string | null;
    moment: string;
    rating: "good" | "okay" | "bad" | null;
    comment: string | null;
    route: string;
    release: string | null;
    organisation: string | null;
    person: string | null;
  }[];
  week: { rated: number; bad: number; ratedBefore: number; badBefore: number };
};

function counts(raw: unknown): Counts {
  const row = read.object(raw);
  return {
    good: read.number(row.good),
    okay: read.number(row.okay),
    bad: read.number(row.bad),
    dismissed: read.number(row.dismissed),
    optedOut: read.number(row.opted_out),
    comments: read.number(row.comments),
  };
}

export function normalizeFeedback(raw: unknown): FeedbackSummary {
  const body = read.object(raw);
  const week = read.object(body.week);
  return {
    days: read.number(body.days, 30),
    moments: read.array(body.moments).map((item) => ({
      moment: read.string(read.object(item).moment),
      ...counts(item),
    })),
    releases: read.array(body.releases).map((item) => ({
      release: read.string(read.object(item).release, "unknown"),
      lastAt: read.optionalString(read.object(item).last_at),
      ...counts(item),
    })),
    byDay: read.array(body.by_day).map((item) => ({
      day: read.string(read.object(item).day),
      ...counts(item),
    })),
    recent: read.array(body.recent).map((item) => {
      const row = read.object(item);
      const rating = row.rating;
      return {
        id: read.string(row.feedback_id),
        createdAt: read.optionalString(row.created_at),
        moment: read.string(row.moment),
        rating:
          rating === "good" || rating === "okay" || rating === "bad"
            ? rating
            : null,
        comment: read.optionalString(row.comment),
        route: read.string(row.route, "/"),
        release: read.optionalString(row.release),
        organisation: read.optionalString(row.organisation),
        person: read.optionalString(row.person),
      };
    }),
    week: {
      rated: read.number(week.rated),
      bad: read.number(week.bad),
      ratedBefore: read.number(week.rated_before),
      badBefore: read.number(week.bad_before),
    },
  };
}

/** Share of good answers among ratings, as a whole percent; null with none. */
export function goodShare(row: Counts): number | null {
  const rated = row.good + row.okay + row.bad;
  return rated ? Math.round((row.good / rated) * 100) : null;
}

/** True when this week's "Not good" share is up on last week's, with at least three. */
export function worse(week: FeedbackSummary["week"]): boolean {
  if (week.bad < 3 || week.rated === 0) return false;
  const now = week.bad / week.rated;
  const before = week.ratedBefore ? week.badBefore / week.ratedBefore : 0;
  return now > before;
}
