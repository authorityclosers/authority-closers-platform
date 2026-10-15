/**
 * Times in India time, the team's clock, formatted the same on the server and
 * in any browser, so a server-rendered time never changes on hydration.
 */
const STAMP = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Kolkata",
});

/** "11 Oct 2026, 9:05 am"; `empty` when the value is missing or not a date. */
export function istStamp(
  value: string | number | Date | null | undefined,
  empty = "—",
): string {
  if (value === null || value === undefined || value === "") return empty;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? empty : STAMP.format(date);
}
