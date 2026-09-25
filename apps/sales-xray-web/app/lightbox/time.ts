/**
 * One readable clock for every visible time: mm:ss, or h:mm:ss from one hour.
 * Formatting only; seek bounds keep their original milliseconds.
 */
export function formatClock(milliseconds: number): string {
  const total = Number.isFinite(milliseconds)
    ? Math.max(0, Math.floor(milliseconds / 1000))
    : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`
    : `${String(minutes).padStart(2, "0")}:${seconds}`;
}

/** Sub-second clips would otherwise read as one identical start and end time. */
export function isUnderOneSecond(startMs: number, endMs: number): boolean {
  return endMs - startMs < 1000;
}
