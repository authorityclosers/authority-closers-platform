/** Compact analysis time; rounding down never overstates the available time. */
export function formatAnalysisTime(seconds: number): string {
  return seconds > 3600
    ? `${Math.floor(seconds / 3600)} h`
    : `${Math.floor(seconds / 60)} min`;
}
