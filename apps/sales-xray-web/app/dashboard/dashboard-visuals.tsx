"use client";

import { useState, type CSSProperties } from "react";

import type { Allowance } from "../acquisition-client";
import {
  otherSavedCalls,
  type ActivityDay,
  type CallSummary,
} from "./dashboard-data";
import styles from "./dashboard-visuals.module.css";

// Activity dates are India calendar days; read them as plain dates.
const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});
const dayLabel = (date: string) => DAY.format(new Date(`${date}T00:00:00Z`));

export function callTime(seconds: number): string {
  if (seconds <= 0) return "0 min";
  if (seconds < 60) return "<1 min";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

const plural = (count: number, word: string) =>
  `${count} ${word}${count === 1 ? "" : "s"}`;

/**
 * The last 30 days drawn as one audio waveform: each day is a bar as tall as
 * the call time analysed that day, mirrored around the centre line. Days with
 * no calls are a quiet dot. Hover a day to read it.
 */
export function MonthWave({ days }: { days: ActivityDay[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const calls = days.reduce((sum, day) => sum + day.analysed, 0);
  const seconds = days.reduce((sum, day) => sum + day.analysedSeconds, 0);
  const active = days.filter((day) => day.analysed > 0).length;
  const peak = Math.max(1, ...days.map((day) => day.analysedSeconds));
  const busiest = days.reduce<ActivityDay | null>(
    (best, day) =>
      day.analysed > 0 &&
      (!best ||
        day.analysedSeconds > best.analysedSeconds ||
        (day.analysedSeconds === best.analysedSeconds &&
          day.analysed > best.analysed))
        ? day
        : best,
    null,
  );
  const focus = hover === null ? null : days[hover];

  return (
    <div className={styles.month}>
      <dl className={styles.stats}>
        <div>
          <dt>Calls analysed</dt>
          <dd>{calls}</dd>
        </div>
        <div>
          <dt>Call time analysed</dt>
          <dd>{callTime(seconds)}</dd>
        </div>
        <div>
          <dt>Days with calls</dt>
          <dd>
            {active}
            <small> of {days.length}</small>
          </dd>
        </div>
        <div>
          <dt>Busiest day</dt>
          <dd>{busiest ? dayLabel(busiest.date) : "—"}</dd>
        </div>
      </dl>

      <div
        className={styles.wave}
        role="img"
        aria-label={`Last ${days.length} days: ${plural(calls, "call")} analysed, ${callTime(seconds)} of calls, on ${plural(active, "day")}.`}
        onMouseLeave={() => setHover(null)}
      >
        {days.map((day, index) => (
          <span
            key={day.date}
            className={styles.day}
            data-empty={day.analysed === 0 ? "" : undefined}
            data-today={index === days.length - 1 ? "" : undefined}
            data-hot={hover === index ? "" : undefined}
            style={
              {
                "--h":
                  day.analysedSeconds > 0
                    ? Math.max(0.16, Math.sqrt(day.analysedSeconds / peak))
                    : 0,
                "--i": index,
              } as CSSProperties
            }
            onMouseEnter={() => setHover(index)}
          >
            <i />
          </span>
        ))}
        {focus && hover !== null && (
          <p
            className={styles.tip}
            style={{ "--x": (hover + 0.5) / days.length } as CSSProperties}
          >
            <b>{hover === days.length - 1 ? "Today" : dayLabel(focus.date)}</b>
            {focus.analysed === 0
              ? "No calls"
              : `${plural(focus.analysed, "call")} · ${callTime(focus.analysedSeconds)}`}
          </p>
        )}
      </div>

      <div className={styles.axis} aria-hidden="true">
        {days.map((day, index) =>
          index % 7 === 0 || index === days.length - 1 ? (
            <span
              key={day.date}
              style={{ "--x": (index + 0.5) / days.length } as CSSProperties}
            >
              {index === days.length - 1 ? "Today" : dayLabel(day.date)}
            </span>
          ) : null,
        )}
      </div>
    </div>
  );
}

const PARTS = [
  { tone: "ready", label: "Report ready" },
  { tone: "active", label: "In progress" },
  { tone: "attention", label: "Needs attention" },
  { tone: "other", label: "Other saved" },
] as const;

/** Where each ring segment starts and how long it is, out of 100. */
function ringSegments(values: number[], total: number) {
  const shown = values.filter((value) => value > 0).length;
  const gap = shown > 1 ? 2.2 : 0;
  const shares = values.map((value) => (value / Math.max(1, total)) * 100);
  return PARTS.map((part, index) => ({
    ...part,
    value: values[index],
    share: shares[index],
    offset:
      shares.slice(0, index).reduce((sum, share) => sum + share, 0) + gap / 2,
    length: Math.max(0, shares[index] - gap),
  }));
}

/** Saved calls as one ring: each colour is a status, the centre is the total. */
export function StatusRing({ summary }: { summary: CallSummary }) {
  const [hover, setHover] = useState<string | null>(null);
  const values = [
    summary.completed,
    summary.processing,
    summary.needsAttention,
    otherSavedCalls(summary),
  ];
  const segments = ringSegments(values, summary.total);
  const focus = segments.find((segment) => segment.tone === hover) ?? null;

  return (
    <div className={styles.status} onMouseLeave={() => setHover(null)}>
      <div className={styles.ring}>
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle className={styles.track} cx="50" cy="50" r="40" />
          {segments.map((segment, index) =>
            segment.value > 0 ? (
              <circle
                key={segment.tone}
                className={styles.segment}
                data-tone={segment.tone}
                data-dim={hover && hover !== segment.tone ? "" : undefined}
                cx="50"
                cy="50"
                r="40"
                pathLength={100}
                strokeDasharray={`${segment.length} ${100 - segment.length}`}
                strokeDashoffset={-segment.offset}
                style={{ "--i": index } as CSSProperties}
                onMouseEnter={() => setHover(segment.tone)}
              />
            ) : null,
          )}
        </svg>
        <p className={styles.centre}>
          <b>{focus ? focus.value : summary.total}</b>
          <span>{focus ? focus.label : "saved calls"}</span>
        </p>
      </div>
      <ul className={styles.legend}>
        {segments.map((segment) => (
          <li
            key={segment.tone}
            data-tone={segment.tone}
            data-zero={segment.value === 0 ? "" : undefined}
            data-hot={hover === segment.tone ? "" : undefined}
            onMouseEnter={() => setHover(segment.tone)}
          >
            <i aria-hidden="true" />
            <span>{segment.label}</span>
            <b>{segment.value}</b>
            <small>{Math.round(segment.share)}%</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A small gauge for the Minutes left tile: the ring is the time still left. */
export function MinutesRing({ allowance }: { allowance: Allowance }) {
  if (allowance.unlimited || allowance.allowance_seconds <= 0) return null;
  const left = Math.min(
    1,
    Math.max(0, allowance.available_seconds / allowance.allowance_seconds),
  );
  return (
    <svg
      className={styles.gauge}
      data-low={left < 0.2 ? "" : undefined}
      viewBox="0 0 36 36"
      aria-hidden="true"
    >
      <circle className={styles.gaugeTrack} cx="18" cy="18" r="14" />
      <circle
        className={styles.gaugeFill}
        cx="18"
        cy="18"
        r="14"
        pathLength={100}
        strokeDasharray={`${left * 100} 100`}
      />
    </svg>
  );
}
