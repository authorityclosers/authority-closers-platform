"use client";

/**
 * Pick a day for Home (owner, 15 Nov 2026). Today and Yesterday one tap away,
 * then a month calendar, Monday first, back to 90 days; days ahead and days
 * older than 90 can't be picked. Picking closes the sheet.
 */

import { ChevronLeft, ChevronRight, Info } from "lucide-react";
import { useState } from "react";

import { Sheet } from "../ui/sheet";
import { DAYS_BACK, indiaToday, shiftDay } from "./home-day";
import styles from "./day-sheet.module.css";

const MONTH = new Intl.DateTimeFormat("en-GB", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const FULL = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  timeZone: "UTC",
});

const pad = (value: number) => String(value).padStart(2, "0");
const keyOf = (year: number, month: number, date: number) =>
  `${year}-${pad(month)}-${pad(date)}`;
const partsOf = (day: string) =>
  day.split("-").map(Number) as [number, number, number];

function Calendar({
  chosen,
  onPick,
}: {
  chosen: string;
  onPick: (day: string) => void;
}) {
  const today = indiaToday();
  const oldest = shiftDay(today, -DAYS_BACK);
  const [startYear, startMonth] = partsOf(chosen);
  const [[year, month], setMonth] = useState<[number, number]>([
    startYear,
    startMonth,
  ]);
  const first = new Date(Date.UTC(year, month - 1, 1));
  const lead = (first.getUTCDay() + 6) % 7;
  const count = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const lastOfPrevious = keyOf(
    year,
    month - 1 || 12,
    new Date(Date.UTC(year, month - 1, 0)).getUTCDate(),
  );
  const canBack =
    (month === 1 ? keyOf(year - 1, 12, 31) : lastOfPrevious) >= oldest;
  const canOn =
    keyOf(month === 12 ? year + 1 : year, month === 12 ? 1 : month + 1, 1) <=
    today;
  const go = (by: number) =>
    setMonth(([y, m]) => {
      const next = m + by;
      return next < 1 ? [y - 1, 12] : next > 12 ? [y + 1, 1] : [y, next];
    });
  return (
    <div className={styles.calendar}>
      <div className={styles.monthRow}>
        <button
          type="button"
          className={styles.step}
          onClick={() => go(-1)}
          disabled={!canBack}
          aria-label="Previous month"
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <strong aria-live="polite">{MONTH.format(first)}</strong>
        <button
          type="button"
          className={styles.step}
          onClick={() => go(1)}
          disabled={!canOn}
          aria-label="Next month"
        >
          <ChevronRight size={20} aria-hidden="true" />
        </button>
      </div>
      <div className={styles.grid}>
        {WEEK.map((name) => (
          <span key={name} className={styles.weekday} aria-hidden="true">
            {name.slice(0, 1)}
          </span>
        ))}
        {Array.from({ length: lead }, (_, index) => (
          <span key={`lead-${index}`} aria-hidden="true" />
        ))}
        {Array.from({ length: count }, (_, index) => {
          const date = index + 1;
          const day = keyOf(year, month, date);
          const out = day > today || day < oldest;
          return (
            <button
              key={day}
              type="button"
              className={styles.day}
              disabled={out}
              aria-pressed={day === chosen}
              data-today={day === today || undefined}
              aria-label={FULL.format(
                new Date(Date.UTC(year, month - 1, date)),
              )}
              onClick={() => onPick(day)}
            >
              {date}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DaySheet({
  open,
  onClose,
  day,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  /** The chosen past day, or null for today. */
  day: string | null;
  onPick: (next: string | null) => void;
}) {
  const today = indiaToday();
  const yesterday = shiftDay(today, -1);
  const chosen = day ?? today;
  const pick = (next: string) => {
    // Closing pops the sheet's own history entry (Back closes a sheet), which
    // puts the previous address back: write the day once that step has landed.
    let done = false;
    const apply = () => {
      if (done) return;
      done = true;
      window.removeEventListener("popstate", apply);
      onPick(next === today ? null : next);
    };
    window.addEventListener("popstate", apply);
    window.setTimeout(apply, 400);
    onClose();
  };
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Pick a day"
      description="See calls from a past day."
    >
      <DayTip />
      <div className={styles.quick}>
        <button
          type="button"
          className={styles.quickDay}
          aria-pressed={chosen === today}
          onClick={() => pick(today)}
        >
          Today
        </button>
        <button
          type="button"
          className={styles.quickDay}
          aria-pressed={chosen === yesterday}
          onClick={() => pick(yesterday)}
        >
          Yesterday
        </button>
      </div>
      {/* Each opening starts on the chosen day's month. */}
      <Calendar key={`${open}-${chosen}`} chosen={chosen} onPick={pick} />
    </Sheet>
  );
}

/** The longer words behind a small i: a tap shows them, a second tap hides them. */
function DayTip() {
  const [open, setOpen] = useState(false);
  return (
    <div className={styles.tipRow}>
      <button
        type="button"
        className={styles.tipButton}
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
      >
        <Info size={16} aria-hidden="true" />
        <span>What changes?</span>
      </button>
      {open ? (
        <p className={styles.tip} role="note">
          Only calls change. Leads and tasks always show today.
        </p>
      ) : null}
    </div>
  );
}
