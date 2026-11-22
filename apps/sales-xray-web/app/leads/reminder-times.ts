/**
 * One set of reminder times for every follow-up and task (owner, 22 Nov
 * 2026: "custom times: any date and time, plus quick presets of 1 min,
 * 2 min, 5 min, 15 min, 30 min, 1 h, tomorrow morning, not just 1 hour").
 * Pure: a clock in, a moment out. The lead page's Follow-up, Add task, the
 * after-call's Next call and a lead's quick Book the next call all use it
 * (reminder-time.tsx), so a time means the same everywhere.
 */

export type ReminderPreset =
  | "m1"
  | "m2"
  | "m5"
  | "m15"
  | "m30"
  | "hour"
  | "morning";

/** The team's hours as a lead carries them (``work_hours``); only the
 *  opening and its clock matter here. None: 10:00 am on the phone's clock. */
export type OpeningHours = {
  days?: number[];
  start: string;
  timezone?: string;
} | null;

export const REMINDER_PRESETS: readonly {
  key: ReminderPreset;
  label: string;
}[] = [
  { key: "m1", label: "In 1 min" },
  { key: "m2", label: "In 2 min" },
  { key: "m5", label: "In 5 min" },
  { key: "m15", label: "In 15 min" },
  { key: "m30", label: "In 30 min" },
  { key: "hour", label: "In 1 hour" },
  { key: "morning", label: "Tomorrow morning" },
];

const MINUTES: Record<Exclude<ReminderPreset, "morning">, number> = {
  m1: 1,
  m2: 2,
  m5: 5,
  m15: 15,
  m30: 30,
  hour: 60,
};

export function isReminderPreset(value: unknown): value is ReminderPreset {
  return REMINDER_PRESETS.some((item) => item.key === value);
}

/** A moment's date and minutes into its day, in a clock (the phone's when none). */
function wall(at: Date, timeZone?: string) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
    })
      .formatToParts(at)
      .map((part) => [part.type, part.value]),
  );
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  };
}

/** The moment a wall clock shows a date and minutes, in a clock. */
function fromWall(
  year: number,
  month: number,
  day: number,
  minutes: number,
  timeZone?: string,
): Date {
  const wanted = Date.UTC(year, month - 1, day, 0, minutes);
  let at = wanted;
  for (let round = 0; round < 2; round += 1) {
    const seen = wall(new Date(at), timeZone);
    at +=
      wanted - Date.UTC(seen.year, seen.month - 1, seen.day, 0, seen.minutes);
  }
  return new Date(at);
}

/** Tomorrow at the team's opening, in the team's clock; else 10:00 am here. */
export function tomorrowMorning(
  now: Date = new Date(),
  hours: OpeningHours = null,
): Date {
  const opening =
    hours &&
    (hours.days?.length ?? 1) > 0 &&
    /^\d{1,2}:\d{2}$/.test(hours.start)
      ? hours.start
      : null;
  const [hour, minute] = (opening ?? "10:00").split(":").map(Number);
  const zone = opening ? hours?.timezone : undefined;
  const today = wall(now, zone);
  return fromWall(
    today.year,
    today.month,
    today.day + 1,
    hour * 60 + minute,
    zone,
  );
}

/** When a preset reminds, counted from ``now`` (to the second: "In 1 min"
 *  is a minute, not "the next whole minute"). */
export function presetTime(
  key: ReminderPreset,
  now: Date = new Date(),
  hours: OpeningHours = null,
): Date {
  if (key === "morning") return tomorrowMorning(now, hours);
  const at = new Date(now.getTime() + MINUTES[key] * 60_000);
  at.setMilliseconds(0);
  return at;
}

const pad = (value: number) => String(value).padStart(2, "0");

/** A moment as the date and time inputs' values, on the phone's clock. */
export function splitLocal(at: Date): { date: string; time: string } {
  return {
    date: `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`,
    time: `${pad(at.getHours())}:${pad(at.getMinutes())}`,
  };
}

/** "2026-11-22T20:42" (the phone's clock) as a moment; null when unreadable. */
export function readLocal(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return null;
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? null : at;
}

const dayStart = (at: Date) =>
  new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();

/** The exact time a reminder goes, in words: "Today 8:42 pm", "Tomorrow
 *  10:00 am", "Mon 24 Nov, 10:00 am". */
export function reminderWords(at: Date, now: Date = new Date()): string {
  const clock = at
    .toLocaleTimeString("en-IN", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    })
    .toLowerCase()
    .replace(/\s(am|pm)$/, " $1");
  const days = Math.round((dayStart(at) - dayStart(now)) / 86_400_000);
  if (days === 0) return `Today ${clock}`;
  if (days === 1) return `Tomorrow ${clock}`;
  const date = at.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return `${date.replace(",", "")}, ${clock}`;
}
