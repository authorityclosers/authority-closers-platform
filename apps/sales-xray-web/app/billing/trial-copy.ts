/**
 * The free trial in plain words (owner, 25 Nov 2026: "fifteen days or three hours,
 * no card, whichever ends"; a trial that started before keeps its month). The server
 * says the trial's size, its end once trial v2 is on, and its length through the
 * plan's name (GET /v1/me/plan); with no end (v1) no days are promised.
 */
import { formatAnalysisTime } from "../analysis-time";

export type Trial = {
  seconds: number;
  endsAt: string | null;
  /** 15 for a new trial, 30 for a month that started before; null when unknown. */
  days?: number | null;
};

/** The words for a new trial, wherever it is offered before it starts. */
export const TRIAL_TERMS = "15 days or 3 hours of call analysis";

const DAY_MS = 86_400_000;

/** "3 hours", or the exact time when it is not whole hours. */
export function trialHours(seconds: number): string {
  const hours = seconds / 3600;
  if (Number.isInteger(hours) && hours > 0)
    return `${hours} ${hours === 1 ? "hour" : "hours"}`;
  return formatAnalysisTime(seconds);
}

/** "Free for 15 days or 3 hours of call analysis" ("1 month" for a trial that
 *  started before 25 Nov); "Free trial · 3 hours of call analysis" without an end. */
export function trialHeadline(trial: Trial): string {
  const size = `${trialHours(trial.seconds)} of call analysis`;
  if (!trial.endsAt) return `Free trial · ${size}`;
  const days = trial.days ?? 30;
  const length =
    days === 30 ? "1 month" : `${days} ${days === 1 ? "day" : "days"}`;
  return `Free for ${length} or ${size}`;
}

/** Whole days left, floored ("27 days"); the last day says so. */
function daysLeft(endsAt: string, now: number): string | null {
  const left = Date.parse(endsAt) - now;
  if (!Number.isFinite(left) || left <= 0) return null;
  const days = Math.floor(left / DAY_MS);
  return days >= 2 ? `${days} days` : days === 1 ? "1 day" : "Last day";
}

/**
 * What is left: "12 days · 2 h 10 min left", or why nothing is ("Your free trial
 * has ended", "You've used your 3 free hours"). Without an end: "2 h 10 min left".
 */
export function trialLeft(
  trial: Trial,
  availableSeconds: number,
  now: number = Date.now(),
): string {
  const days = trial.endsAt ? daysLeft(trial.endsAt, now) : null;
  if (trial.endsAt && days === null) return "Your free trial has ended";
  if (availableSeconds <= 0) {
    const hours = trial.seconds / 3600;
    return Number.isInteger(hours) && hours > 0
      ? `You've used your ${hours} free ${hours === 1 ? "hour" : "hours"}`
      : "You've used your free analysis time";
  }
  const time = `${formatAnalysisTime(availableSeconds)} left`;
  return days ? `${days} · ${time}` : time;
}
