"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import {
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { CALLS_PATH } from "../analysis-routes";

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

/** A zero-based axis with at most four steps of a round size. */
export function axisTicks(peak: number): number[] {
  const top = Math.max(1, peak);
  const step =
    [1, 2, 5, 10, 20, 50, 100].find((size) => top / size <= 4) ?? 200;
  const max = Math.ceil(top / step) * step;
  return Array.from({ length: max / step + 1 }, (_, index) => index * step);
}

/**
 * Calls analysed each day for the last 30 days: zero-based bars on a labelled
 * axis, today solid, other days lighter. Hover or focus a day to read it.
 */
export function DayBars({ days }: { days: ActivityDay[] }) {
  const [focus, setFocus] = useState<number | null>(null);
  const ticks = axisTicks(Math.max(0, ...days.map((day) => day.analysed)));
  const max = ticks[ticks.length - 1];
  const total = days.reduce((sum, day) => sum + day.analysed, 0);
  const seconds = days.reduce((sum, day) => sum + day.analysedSeconds, 0);
  const shown = focus === null ? null : days[focus];
  const last = days.length - 1;
  // A bar is a few pixels wide on a phone: a finger reads the day under it
  // anywhere across the plot, so the whole plot is the touch target.
  const scrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse") return;
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    const at = Math.floor(
      ((event.clientX - box.left) / box.width) * days.length,
    );
    setFocus(Math.min(last, Math.max(0, at)));
  };
  return (
    <figure className={styles.chart} onMouseLeave={() => setFocus(null)}>
      <figcaption className={styles.readout} aria-live="polite">
        {shown ? (
          <>
            <b>{last === focus ? "Today" : dayLabel(shown.date)}</b>
            <span>
              {plural(shown.analysed, "call")} ·{" "}
              {callTime(shown.analysedSeconds)}
            </span>
          </>
        ) : (
          <>
            <b>{plural(total, "call")}</b>
            <span>{callTime(seconds)} of calls analysed</span>
          </>
        )}
      </figcaption>
      <div className={styles.plot}>
        <ol className={styles.axis} aria-hidden="true">
          {[...ticks].reverse().map((tick) => (
            <li key={tick}>{tick}</li>
          ))}
        </ol>
        <div
          className={styles.bars}
          style={{ "--rows": ticks.length - 1 } as CSSProperties}
          data-scrub=""
          onPointerDown={scrub}
          onPointerMove={scrub}
        >
          {days.map((day, index) => (
            <button
              key={day.date}
              type="button"
              className={styles.day}
              data-today={index === last ? "" : undefined}
              data-focus={focus === index ? "" : undefined}
              aria-label={`${index === last ? "Today" : dayLabel(day.date)}: ${plural(day.analysed, "call")}, ${callTime(day.analysedSeconds)}`}
              onMouseEnter={() => setFocus(index)}
              onFocus={() => setFocus(index)}
              onBlur={() => setFocus(null)}
            >
              <i
                data-zero={day.analysed === 0 ? "" : undefined}
                style={{ height: `${(day.analysed / max) * 100}%` }}
              />
            </button>
          ))}
        </div>
        <ol className={styles.dates} aria-hidden="true">
          {days.map((day, index) => (
            <li key={day.date}>
              {index === last
                ? "Today"
                : (last - index) % 7 === 0
                  ? dayLabel(day.date)
                  : ""}
            </li>
          ))}
        </ol>
      </div>
    </figure>
  );
}

const PARTS = [
  { tone: "ready", label: "Report ready" },
  { tone: "active", label: "In progress" },
  { tone: "attention", label: "Needs attention" },
  { tone: "idle", label: "Other" },
] as const;

/** Every saved call once: one split bar and a full-text row per status. */
export function StatusSplit({ summary }: { summary: CallSummary }) {
  const values = [
    summary.completed,
    summary.processing,
    summary.needsAttention,
    otherSavedCalls(summary),
  ];
  const total = Math.max(1, summary.total);
  return (
    <div className={styles.status}>
      <p className={styles.statusTotal}>
        <b>{summary.total}</b> saved {summary.total === 1 ? "call" : "calls"}
      </p>
      <div className={styles.split} aria-hidden="true">
        {PARTS.map((part, index) =>
          values[index] > 0 ? (
            <i
              key={part.tone}
              data-tone={part.tone}
              style={{ flexGrow: values[index] }}
            />
          ) : null,
        )}
      </div>
      <ul className={styles.legend}>
        {PARTS.map((part, index) => (
          <li
            key={part.tone}
            data-tone={part.tone}
            data-zero={values[index] === 0 ? "" : undefined}
          >
            <i aria-hidden="true" />
            <span>{part.label}</span>
            <b>{values[index]}</b>
            <small>{Math.round((values[index] / total) * 100)}%</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A small gauge for the Minutes left figure: the ring is the time still left. */
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

export function MinutesUsed({ allowance }: { allowance: Allowance }) {
  if (allowance.unlimited || allowance.allowance_seconds <= 0) return null;
  const used = Math.max(
    0,
    Math.round(
      (allowance.allowance_seconds - allowance.available_seconds) / 60,
    ),
  );
  const total = Math.round(allowance.allowance_seconds / 60);
  return (
    <span className={styles.used} title={`${used} of ${total} min used`}>
      {used} min used
    </span>
  );
}

export function AttentionAction({ count }: { count: number }) {
  return count > 0 ? (
    <Link className={styles.review} href={`${CALLS_PATH}?status=attention`}>
      Review
      <ChevronRight size={14} aria-hidden="true" />
    </Link>
  ) : (
    <span className={styles.clear}>All clear</span>
  );
}

/** The chart while it loads: the same box, axis and baseline. */
export function DayBarsSkeleton() {
  return (
    <div className={styles.chart} aria-hidden="true">
      <p className={styles.readout}>
        <i className={styles.skeletonLine} data-w="readout" />
      </p>
      <div className={styles.plot}>
        <ol className={styles.axis}>
          <li />
          <li />
        </ol>
        <div className={`${styles.bars} ${styles.skeletonBars}`}>
          {Array.from({ length: 30 }, (_, index) => (
            <span key={index} className={styles.day}>
              <i style={{ height: `${18 + ((index * 37) % 50)}%` }} />
            </span>
          ))}
        </div>
        <ol className={styles.dates}>
          <li />
        </ol>
      </div>
    </div>
  );
}

export function StatusSplitSkeleton() {
  return (
    <div className={styles.status} aria-hidden="true">
      <p className={styles.statusTotal}>
        <i className={styles.skeletonLine} data-w="total" />
      </p>
      <div className={`${styles.split} ${styles.skeletonSplit}`} />
      <ul className={styles.legend}>
        {PARTS.map((part) => (
          <li key={part.tone} data-skeleton="">
            <i className={styles.skeletonLine} data-w="legend" />
          </li>
        ))}
      </ul>
    </div>
  );
}
