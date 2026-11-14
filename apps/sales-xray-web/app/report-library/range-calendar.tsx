"use client";

/**
 * The From–To calendar of the Reports filter (Dipak's Reports V4 spec,
 * section 10): the current month first, previous and next arrows, a monthly
 * grid; the chosen days and the days between them in teal. A tap sets From,
 * the next sets To (pickDay in report-filter.ts); the From and To fields say
 * which one the next tap sets and can be tapped to change either.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";

import { isoDay, longDayWords, monthWords } from "./report-filter";
import styles from "./report-library.module.css";

const WEEKDAYS = [
  ["Su", "Sunday"],
  ["Mo", "Monday"],
  ["Tu", "Tuesday"],
  ["We", "Wednesday"],
  ["Th", "Thursday"],
  ["Fr", "Friday"],
  ["Sa", "Saturday"],
] as const;

export type CalendarMonth = Readonly<{ year: number; month: number }>;

/** The month a day falls in (month 0-based). */
export function monthOf(day: string): CalendarMonth {
  const [year, month] = day.split("-").map(Number);
  return { year, month: month - 1 };
}

export function shiftMonth(at: CalendarMonth, by: number): CalendarMonth {
  const index = at.year * 12 + at.month + by;
  return { year: Math.floor(index / 12), month: ((index % 12) + 12) % 12 };
}

export function RangeCalendar({
  month,
  from,
  to,
  today,
  onMonth,
  onPick,
}: {
  month: CalendarMonth;
  from: string | null;
  to: string | null;
  /** Today in the reader's zone (YYYY-MM-DD), outlined. */
  today: string;
  onMonth: (month: CalendarMonth) => void;
  onPick: (day: string) => void;
}) {
  const first = new Date(Date.UTC(month.year, month.month, 1)).getUTCDay();
  const days = new Date(Date.UTC(month.year, month.month + 1, 0)).getUTCDate();
  const cells: (string | null)[] = [
    ...Array.from({ length: first }, () => null),
    ...Array.from({ length: days }, (_, index) =>
      isoDay(month.year, month.month, index + 1),
    ),
  ];
  const title = monthWords(month.year, month.month);
  return (
    <div className={styles.calendar} data-calendar="">
      <div className={styles.calendarHead}>
        <button
          type="button"
          className={styles.calendarMove}
          aria-label="Previous month"
          onClick={() => onMonth(shiftMonth(month, -1))}
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <strong aria-live="polite" data-calendar-month="">
          {title}
        </strong>
        <button
          type="button"
          className={styles.calendarMove}
          aria-label="Next month"
          onClick={() => onMonth(shiftMonth(month, 1))}
        >
          <ChevronRight size={20} aria-hidden="true" />
        </button>
      </div>
      <div className={styles.calendarGrid} role="grid" aria-label={title}>
        <div className={styles.calendarRow} role="row">
          {WEEKDAYS.map(([short, long]) => (
            <span
              key={short}
              className={styles.weekday}
              role="columnheader"
              aria-label={long}
            >
              {short}
            </span>
          ))}
        </div>
        {Array.from({ length: Math.ceil(cells.length / 7) }, (_, week) => (
          <div className={styles.calendarRow} role="row" key={week}>
            {cells.slice(week * 7, week * 7 + 7).map((day, index) =>
              day === null ? (
                <span key={`gap-${index}`} role="gridcell" />
              ) : (
                <span key={day} role="gridcell">
                  <button
                    type="button"
                    className={styles.day}
                    data-day={day}
                    data-edge={day === from || day === to ? "" : undefined}
                    data-between={
                      from && to && day > from && day < to ? "" : undefined
                    }
                    data-today={day === today ? "" : undefined}
                    aria-pressed={day === from || day === to}
                    aria-label={`${longDayWords(day)}${day === from ? ", start date" : ""}${day === to ? ", end date" : ""}`}
                    onClick={() => onPick(day)}
                  >
                    {Number(day.slice(8))}
                  </button>
                </span>
              ),
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
