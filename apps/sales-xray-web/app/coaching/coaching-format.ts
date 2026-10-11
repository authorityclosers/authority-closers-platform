/** Pure display helpers shared by Coaching screens and players. */

export function timeLabel(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

// One fixed locale and zone, so server and browser render the same text.
const SHORT_DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Asia/Kolkata",
});

export function callDate(value: string): string {
  const time = Date.parse(value);
  return Number.isFinite(time) ? SHORT_DATE.format(time) : "";
}
