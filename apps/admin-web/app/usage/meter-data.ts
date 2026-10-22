/**
 * The cost meter (owner, 22 Oct 2026: "is there any live meter single where we can see
 * internally the current cost per min?"): GET /v1/admin/conversation/meter, one
 * environment's cost per audio minute today, over 24 hours and over 7 days, full reports
 * against short calls, and by pipeline version. Pure.
 */
import { read } from "../lib/read";
import { normalizeMetrics, type Fx } from "./cost-data";

export type MeterGroup = {
  calls: number;
  audioMinutes: number;
  rupees: number;
  perMinute: number | null;
};

export type MeterWindow = {
  key: string;
  label: string;
  since: string;
  allIn: MeterGroup;
  fullReports: MeterGroup;
  short: MeterGroup;
  notAnalysed: { calls: number; audioMinutes: number };
};

export type MeterVersion = MeterGroup & {
  id: string;
  label: string;
  fullReports: number;
  firstAt: string;
  lastAt: string;
};

export type CostMeter = {
  environment: string;
  available: boolean;
  generatedAt: string | null;
  ageSeconds: number | null;
  targets: number[];
  windows: MeterWindow[];
  byVersion: MeterVersion[];
  fx: Fx;
  problems: string[];
};

const group = (raw: unknown): MeterGroup => {
  const row = read.object(raw);
  return {
    calls: read.number(row.calls),
    audioMinutes: read.number(row.audio_minutes),
    rupees: read.number(row.rupees),
    perMinute: read.optionalNumber(row.per_minute),
  };
};

export function normalizeMeter(raw: unknown): CostMeter {
  const body = read.object(raw);
  const targets = read
    .array(body.targets)
    .filter((item): item is number => typeof item === "number" && item > 0);
  return {
    environment: read.string(body.environment, "production"),
    available: read.boolean(body.available),
    generatedAt: read.optionalString(body.generated_at),
    ageSeconds: read.optionalNumber(body.age_seconds),
    targets: targets.length ? targets : [0.4, 0.1],
    windows: read.array(body.windows).map((item) => {
      const row = read.object(item);
      const skipped = read.object(row.not_analysed);
      return {
        key: read.string(row.key),
        label: read.string(row.label, read.string(row.key)),
        since: read.string(row.since),
        allIn: group(row.all_in),
        fullReports: group(row.full_reports),
        short: group(row.short),
        notAnalysed: {
          calls: read.number(skipped.calls),
          audioMinutes: read.number(skipped.audio_minutes),
        },
      };
    }),
    byVersion: read.array(body.by_version).map((item) => {
      const row = read.object(item);
      return {
        ...group(row),
        id: read.string(row.id),
        label: read.string(row.label, "Not recorded"),
        fullReports: read.number(row.full_reports),
        firstAt: read.string(row.first_at),
        lastAt: read.string(row.last_at),
      };
    }),
    // The same rate block Usage reads, so the words match.
    fx: normalizeMetrics({ fx: body.fx }).fx,
    problems: read
      .array(body.problems)
      .map((item) => read.string(read.object(item).problem))
      .filter(Boolean),
  };
}

export type MeterTone = "good" | "warn" | "bad" | "neutral";

/** Green at or under the lower target, amber up to the higher one, red above it. */
export function meterTone(
  perMinute: number | null,
  targets: readonly number[],
): MeterTone {
  if (perMinute === null) return "neutral";
  const [high, low] = [Math.max(...targets), Math.min(...targets)];
  if (perMinute <= low) return "good";
  if (perMinute <= high) return "warn";
  return "bad";
}

const RATE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "₹0.97/min", or "–". */
export const perMinuteWords = (value: number | null) =>
  value === null ? "–" : `${RATE.format(value)}/min`;

/** "updated just now", "updated 3 min ago", "updated 2 h ago", "no export yet". */
export function ageWords(seconds: number | null): string {
  if (seconds === null) return "no export yet";
  if (seconds < 90) return "updated just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `updated ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48
    ? `updated ${hours} h ago`
    : `updated ${Math.round(hours / 24)} days ago`;
}

/** The collector runs every 5 minutes: over 30 minutes old means it has stopped. */
export const isStale = (seconds: number | null) =>
  seconds === null || seconds > 30 * 60;

/** "3 calls · 12.4 min" */
export function groupWords(row: MeterGroup): string {
  return `${row.calls} ${row.calls === 1 ? "call" : "calls"} · ${row.audioMinutes} min`;
}

/** Where a value sits on a scale that always shows both targets (0 to the larger of 1.5×
 * the higher target and the value). */
export function scaleOf(value: number | null, targets: readonly number[]) {
  const top = Math.max(Math.max(...targets) * 1.5, (value ?? 0) * 1.1);
  const at = (amount: number) =>
    Math.min(100, Math.max(0, (amount / top) * 100));
  return {
    value: value === null ? null : at(value),
    targets: targets.map((target) => ({ target, at: at(target) })),
  };
}
