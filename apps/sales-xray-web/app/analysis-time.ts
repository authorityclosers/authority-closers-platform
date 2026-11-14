/**
 * Compact analysis time. Rounding down never overstates the available time,
 * and above an hour the minutes stay: 7 h 59 min is not "7 h", so the top
 * bar and the Dashboard ("479 min") say the same amount.
 */
export function formatAnalysisTime(seconds: number): string {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (seconds <= 3600) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/**
 * How much analysis is left, in time, never a price (orchestrator, 13 Nov 2026:
 * the owner found "no good UI which makes it understandable"): "2 h 41 min of
 * analysis left", or before a personal account's first analysis "3 hours to
 * try". Null while nothing is left (the out-of-minutes reason says that), when
 * it is unlimited, or before the number is known.
 */
export function analysisTimeLeft(
  allowance: {
    allowance_seconds: number;
    committed_seconds: number;
    available_seconds: number;
    unlimited?: true;
  } | null,
  scope: "personal" | "payer" | "member",
): string | null {
  if (!allowance || allowance.unlimited || allowance.available_seconds <= 0)
    return null;
  const seconds = allowance.available_seconds;
  const untouched =
    allowance.committed_seconds === 0 &&
    seconds === allowance.allowance_seconds;
  if (scope === "personal" && untouched) {
    const hours = seconds / 3600;
    return Number.isInteger(hours)
      ? `${hours} ${hours === 1 ? "hour" : "hours"} to try`
      : `${formatAnalysisTime(seconds)} to try`;
  }
  return `${formatAnalysisTime(seconds)} of analysis left`;
}
