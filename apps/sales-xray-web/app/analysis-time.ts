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
