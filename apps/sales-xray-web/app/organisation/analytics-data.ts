import type { ActivityItem, ActivityPage } from "../leads/leads-client";
import { displayName } from "../display-name";
import { readMembers, type OrgMember } from "./organisation-api";

export const METRICS = [
  { key: "calls", label: "Calls" },
  { key: "conversations", label: "Conversations" },
  { key: "notes", label: "Notes" },
  { key: "moves", label: "Stage moves" },
] as const;
export type Metric = (typeof METRICS)[number]["key"];
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

/** Bounded reads of the existing permission-filtered feed. Never use all-time counts as a period total. */
export async function readAnalytics({
  team,
  personId,
  signal,
  previous,
  now = new Date(Date.now()).toISOString(),
  pages = 20,
}: {
  team: boolean;
  personId?: string;
  signal?: AbortSignal;
  previous?: AnalyticsHistory;
  now?: string;
  pages?: number;
}): Promise<AnalyticsHistory> {
  const directory = previous
    ? Promise.resolve(previous.members)
    : readMembers(signal).catch(() => null);
  let cursor = previous?.cursor ?? null;
  const items = new Map(
    (previous?.items ?? []).map((item) => [item.event_id, item]),
  );
  let timezone = previous?.timezone ?? "Asia/Kolkata";
  now = previous?.now ?? now;
  for (let round = 0; round < pages; round += 1) {
    const query = new URLSearchParams({ day: "recent" });
    if (team) query.set("team", "true");
    if (cursor) query.set("before", cursor);
    const response = await fetch(`/v1/lead-desk/activity?${query}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: { accept: "application/json" },
    });
    if (!response.ok) throw new Error("Activity could not load");
    const page = (await response.json()) as ActivityPage;
    if (!Array.isArray(page.items)) throw new Error("Activity is unavailable");
    timezone = page.timezone ?? timezone;
    for (const item of page.items) items.set(item.event_id, item);
    const next = page.next_before;
    if (!next) {
      cursor = null;
      break;
    }
    if (next === cursor || (cursor && Date.parse(next) >= Date.parse(cursor)))
      throw new Error("Activity history did not advance");
    cursor = next;
    if (dayNumber(cursor, timezone) < dayNumber(now, timezone) - 59) break;
  }
  const members = await directory;
  return {
    items: [...items.values()],
    members: team
      ? (members ?? [])
      : (members ?? []).filter((member) => member.personId === personId),
    directoryMissing: previous?.directoryMissing ?? members === null,
    cursor,
    timezone,
    now,
  };
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
      daily: (Counts | null)[];
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
        daily: Array.from({ length: 30 }, (_, index) =>
          start + index > covered ? zero() : null,
        ),
      });
    return people.get(key)!;
  };
  for (const member of history.members)
    if (member.status === "active")
      add(member.personId, member.name ?? "Team member");
  const current = zero(),
    previous = zero();
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
    if (!metrics.length) continue;
    const person = add(
      event.actor_person_id ?? null,
      event.actor_name ?? "Person unavailable",
    );
    const period = day >= start ? "current" : "previous";
    const totals = period === "current" ? current : previous;
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
    start,
    today,
    prior,
    timezone: history.timezone,
    directoryMissing: history.directoryMissing,
  };
}
export type AnalyticsSummary = ReturnType<typeof activitySummary>;
