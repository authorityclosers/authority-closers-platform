import type {
  ActivityItem,
  ActivityPage,
  LeadEvent,
} from "../leads/leads-client";
import { displayName } from "../display-name";
import { type OrgMember } from "./organisation-api";

export const METRICS = [
  { key: "calls", label: "Calls" },
  { key: "conversations", label: "Conversations" },
  { key: "notes", label: "Notes" },
  { key: "moves", label: "Stage moves" },
] as const;
export type Metric = (typeof METRICS)[number]["key"];

/** The periods Analytics reads (competitor teardown 15, 1 Nov 2026). */
export const PERIODS = [
  { key: "1", label: "Today", days: 1 },
  { key: "7", label: "7 days", days: 7 },
  { key: "30", label: "30 days", days: 30 },
] as const;
export type PeriodKey = (typeof PERIODS)[number]["key"];
/** The period from the address (?days=); 30 days when it says none. */
export const periodFrom = (value: string | null | undefined): PeriodKey =>
  PERIODS.find((period) => period.key === value)?.key ?? "30";
export type Counts = Record<Metric, number>;
export type AnalyticsHistory = {
  items: ActivityItem[];
  members: OrgMember[];
  directoryMissing: boolean;
  cursor: string | null;
  timezone: string;
  now: string;
};
const DAY = 86400000;
const zero = (): Counts => ({ calls: 0, conversations: 0, notes: 0, moves: 0 });
export function dayNumber(at: string, timezone: string): number {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(at));
  const part = (key: string) =>
    Number(parts.find((p) => p.type === key)?.value);
  return Date.UTC(part("year"), part("month") - 1, part("day")) / DAY;
}
export const dayText = (day: number) =>
  new Date(day * DAY).toLocaleDateString("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
  });

type SummaryResponse = {
  schema: "lead-desk/1";
  days: number;
  timezone: string;
  now: string;
  start: string;
  prior: string;
  today: string;
  current: Counts & { work: number };
  previous: Counts & { work: number };
  people: {
    id: string | null;
    name: string;
    current: Counts & { work: number };
    previous: Counts & { work: number };
    daily: (Counts & { work: number; day: string })[];
  }[];
};

/** One bounded summary read; never fetch activity pages or the members directory. */
export async function readAnalytics({
  team,
  personId,
  days = 30,
  signal,
}: {
  team: boolean;
  personId?: string;
  /** Today (1), 7 or 30 days, ending today. */
  days?: number;
  signal?: AbortSignal;
}): Promise<AnalyticsSummary> {
  const query = new URLSearchParams({ days: String(days) });
  if (team) query.set("team", "true");
  else if (personId) query.set("person", personId);
  const response = await fetch(`/v1/lead-desk/activity/summary?${query}`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new Error("Activity could not load");
  const summary = (await response.json()) as SummaryResponse;
  if (
    summary.schema !== "lead-desk/1" ||
    summary.days !== days ||
    !Array.isArray(summary.people)
  )
    throw new Error("Activity is unavailable");
  const start = dayNumber(summary.start, "UTC");
  return {
    ...summary,
    start,
    today: dayNumber(summary.today, "UTC"),
    prior: dayNumber(summary.prior, "UTC"),
    currentComplete: true,
    previousComplete: true,
    currentWork: summary.current.work,
    directoryMissing: false,
    people: summary.people.map((person) => {
      const daily = new Map(
        person.daily.map((day) => [dayNumber(day.day, "UTC"), day]),
      );
      return {
        ...person,
        name: displayName(person.name),
        work: person.current.work,
        daily: Array.from(
          { length: days },
          (_, index) => daily.get(start + index) ?? { ...zero(), work: 0 },
        ),
      };
    }),
  };
}

/** Whether a feed item is one the summary counts for this number. */
export function countsToward(metric: Metric, event: LeadEvent): boolean {
  if (metric === "calls") return event.kind === "call";
  if (metric === "conversations")
    return (
      event.kind === "call" &&
      (event.connected === true || (event.duration_seconds ?? 0) > 0)
    );
  return event.kind === (metric === "notes" ? "note" : "stage");
}

/**
 * One page of the feed behind a number (competitor teardown 15: every number
 * opens its list), newest first: today's, the week's, or everything paged
 * back past the period's first day.
 */
export async function readActivityPage({
  days,
  team,
  personId,
  before,
  signal,
}: {
  days: number;
  team: boolean;
  personId?: string;
  before: string | null;
  signal?: AbortSignal;
}): Promise<ActivityPage> {
  const query = new URLSearchParams({
    day: days === 1 ? "today" : days === 7 ? "week" : "recent",
  });
  if (team) query.set("team", "true");
  else if (personId) query.set("person", personId);
  if (before) query.set("before", before);
  const response = await fetch(`/v1/lead-desk/activity?${query}`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new Error("Activity could not load");
  return (await response.json()) as ActivityPage;
}

/** A day number as 2026-11-01. */
export const dayIso = (day: number) =>
  new Date(day * DAY).toISOString().slice(0, 10);

/**
 * The period's numbers, one row per person, for a spreadsheet (teardown 15,
 * Export for owners). A name that starts like a formula stays text.
 */
export function activityCsv(data: AnalyticsSummary): string {
  const cell = (value: string | number) => {
    let text = String(value);
    if (/^[=+\-@]/.test(text)) text = `'${text}`;
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = [
    [
      "Person",
      ...METRICS.map((metric) => metric.label),
      "All updates",
      ...METRICS.map((metric) => `${metric.label}, period before`),
    ],
    ...data.people.map((person) => [
      person.name,
      ...METRICS.map((metric) => person.current[metric.key]),
      person.work,
      ...METRICS.map((metric) => person.previous[metric.key]),
    ]),
  ];
  return `${lines.map((line) => line.map(cell).join(",")).join("\n")}\n`;
}

export function activitySummary(history: AnalyticsHistory) {
  const today = dayNumber(history.now, history.timezone);
  const start = today - 29,
    prior = start - 30;
  const covered = history.cursor
    ? dayNumber(history.cursor, history.timezone)
    : -Infinity;
  const currentComplete = covered < start,
    previousComplete = covered < prior;
  const people = new Map<
    string,
    {
      id: string | null;
      name: string;
      current: Counts;
      previous: Counts;
      work: number;
      daily: ((Counts & { work: number }) | null)[];
    }
  >();
  const add = (id: string | null, name: string) => {
    const key = id ?? "unattributed";
    if (!people.has(key))
      people.set(key, {
        id,
        name: displayName(name),
        current: zero(),
        previous: zero(),
        work: 0,
        daily: Array.from({ length: 30 }, (_, index) =>
          start + index > covered ? { ...zero(), work: 0 } : null,
        ),
      });
    return people.get(key)!;
  };
  for (const member of history.members)
    if (member.status === "active")
      add(member.personId, member.name ?? "Team member");
  const current = zero(),
    previous = zero();
  let currentWork = 0;
  const seen = new Set<string>();
  for (const item of history.items) {
    if (seen.has(item.event_id)) continue;
    seen.add(item.event_id);
    const event = item.event;
    if (
      !Number.isFinite(Date.parse(event.at)) ||
      Date.parse(event.at) > Date.parse(history.now)
    )
      continue;
    const day = dayNumber(event.at, history.timezone);
    if (day < prior || day > today) continue;
    const metrics: Metric[] =
      event.kind === "call"
        ? [
            "calls",
            ...(event.connected === true || (event.duration_seconds ?? 0) > 0
              ? ["conversations" as const]
              : []),
          ]
        : event.kind === "note"
          ? ["notes"]
          : event.kind === "stage"
            ? ["moves"]
            : [];
    // The shared feed defines recorded work (WORK_KINDS in Lead Desk).
    // Team mode also returns incoming leads; those aren't a person's work.
    if (event.kind === "captured") continue;
    // Work with no person behind it (rules, imports) or by someone who has
    // left: named so, never a mystery row (Dipak's walk, ph1-21, 1 Nov 2026).
    const person = add(
      event.actor_person_id ?? null,
      event.actor_name ??
        (event.actor_person_id ? "Former member" : "Automatic updates"),
    );
    const period = day >= start ? "current" : "previous";
    const totals = period === "current" ? current : previous;
    if (period === "current") {
      person.work += 1;
      currentWork += 1;
      const daily = person.daily[day - start];
      if (daily) daily.work += 1;
    }
    for (const metric of metrics) {
      totals[metric] += 1;
      person[period][metric] += 1;
      const daily = person.daily[day - start];
      if (period === "current" && daily) daily[metric] += 1;
    }
  }
  return {
    people: [...people.values()],
    current,
    previous,
    currentComplete,
    previousComplete,
    currentWork,
    start,
    today,
    prior,
    timezone: history.timezone,
    directoryMissing: history.directoryMissing,
  };
}
export type AnalyticsSummary = ReturnType<typeof activitySummary>;
