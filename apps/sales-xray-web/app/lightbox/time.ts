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

/** Only a finite, non-negative, forward interval may be sought or played. */
export function isPlayableRange(startMs: number, endMs: number): boolean {
  return (
    Number.isFinite(startMs) &&
    Number.isFinite(endMs) &&
    startMs >= 0 &&
    endMs > startMs
  );
}

/**
 * The one visible clip interval: "03:06–03:29", or "at 11:33 · under 1 second"
 * when the clip is shorter than a second (never an equal-endpoint range).
 * Canonical milliseconds stay with the caller for seeking.
 */
export function formatClipRange(startMs: number, endMs: number): string {
  const start = formatClock(startMs);
  const end = formatClock(endMs);
  if (!isPlayableRange(startMs, endMs)) return `at ${start}`;
  return isUnderOneSecond(startMs, endMs) || start === end
    ? `at ${start} · under 1 second`
    : `${start}–${end}`;
}

/** The same interval for accessible names: "03:06 to 03:29". */
export function spokenClipRange(startMs: number, endMs: number): string {
  const start = formatClock(startMs);
  const end = formatClock(endMs);
  if (!isPlayableRange(startMs, endMs)) return `at ${start}`;
  return isUnderOneSecond(startMs, endMs) || start === end
    ? `at ${start}, under 1 second`
    : `${start} to ${end}`;
}
