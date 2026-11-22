/**
 * The free trial in plain words (owner, 22 Nov 2026: "1 month + 3 hours", whichever
 * comes first). The server says the trial's size and, once trial v2 is on, its end
 * (GET /v1/me/plan "trial"); with no end (v1) no month is promised.
 */
import { formatAnalysisTime } from "../analysis-time";

export type Trial = { seconds: number; endsAt: string | null };

const DAY_MS = 86_400_000;

/** "3 hours", or the exact time when it is not whole hours. */
export function trialHours(seconds: number): string {
  const hours = seconds / 3600;
  if (Number.isInteger(hours) && hours > 0)
    return `${hours} ${hours === 1 ? "hour" : "hours"}`;
  return formatAnalysisTime(seconds);
}

/** "Free for 1 month · 3 hours of call analysis". */
export function trialHeadline(trial: Trial): string {
  const size = `${trialHours(trial.seconds)} of call analysis`;
  return trial.endsAt ? `Free for 1 month · ${size}` : `Free trial · ${size}`;
}

/** Whole days left, floored ("27 days"); the last day says so. */
function daysLeft(endsAt: string, now: number): string | null {
  const left = Date.parse(endsAt) - now;
  if (!Number.isFinite(left) || left <= 0) return null;
  const days = Math.floor(left / DAY_MS);
  return days >= 2 ? `${days} days` : days === 1 ? "1 day" : "Last day";
}

/**
 * What is left: "27 days · 2 h 10 min left", or why nothing is ("Your free month
 * has ended", "You've used your 3 free hours"). Without an end: "2 h 10 min left".
 */
export function trialLeft(
  trial: Trial,
  availableSeconds: number,
  now: number = Date.now(),
): string {
  const days = trial.endsAt ? daysLeft(trial.endsAt, now) : null;
  if (trial.endsAt && days === null) return "Your free month has ended";
  if (availableSeconds <= 0) {
    const hours = trial.seconds / 3600;
    return Number.isInteger(hours) && hours > 0
      ? `You've used your ${hours} free ${hours === 1 ? "hour" : "hours"}`
      : "You've used your free analysis time";
  }
  const time = `${formatAnalysisTime(availableSeconds)} left`;
  return days ? `${days} · ${time}` : time;
}
