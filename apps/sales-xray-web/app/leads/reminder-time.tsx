"use client";

/**
 * The reminder time picker (owner, 22 Nov 2026: "custom times: any date and
 * time, plus quick presets"). One picker for the lead page's Follow-up, Add
 * task, the after-call's Next call and Try again, and a lead's Book the next
 * call: In 1, 2, 5, 15 or 30 min, In 1 hour, Tomorrow morning (the team's
 * opening), or Pick date & time with the phone's own date and time pickers.
 * Under them, the exact time it reminds ("Today 8:42 pm"), kept fresh while
 * the sheet is open. The parent keeps the choice; the moment is counted when
 * it saves (``presetTime``).
 */

import { BellRing, CalendarClock } from "lucide-react";
import { useEffect, useId, useState } from "react";

import {
  REMINDER_PRESETS,
  isReminderPreset,
  presetTime,
  readLocal,
  reminderWords,
  splitLocal,
  type OpeningHours,
  type ReminderPreset,
} from "./reminder-times";
import styles from "./reminder-time.module.css";

export type ReminderPick = ReminderPreset | "custom";

/** What the picker shows as chosen: a preset, a picked date and time, or
 *  another time the parent set (an older chip such as "This evening"). */
export function reminderAt(
  pick: string | null,
  custom: string,
  now: Date = new Date(),
  hours: OpeningHours = null,
): Date | null {
  if (isReminderPreset(pick)) return presetTime(pick, now, hours);
  if (pick === "custom") return readLocal(custom);
  return null;
}

export function ReminderTime({
  label,
  pick,
  custom,
  onPick,
  onCustom,
  hours = null,
  other = null,
  now = () => new Date(),
}: {
  /** The picker's heading ("When", "Next call"); none when the sheet says it. */
  label?: string;
  /** The chosen preset, "custom" for a picked date and time, or anything
   *  else the parent set (then ``other`` says when). */
  pick: string | null;
  /** The picked date and time, "2026-11-22T20:42" on the phone's clock. */
  custom: string;
  onPick: (pick: ReminderPick) => void;
  onCustom: (value: string) => void;
  /** The team's hours: Tomorrow morning is their opening. */
  hours?: OpeningHours;
  /** When the parent's own choice reminds (a pick that is not a preset). */
  other?: Date | null;
  now?: () => Date;
}) {
  const id = useId();
  // The words follow the clock while the sheet is open ("In 5 min" is five
  // minutes from now, not from when the sheet opened).
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((tick) => tick + 1), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const current = now();
  const at = reminderAt(pick, custom, current, hours) ?? other;
  const past = !!at && at.getTime() < current.getTime() - 30_000;
  const picked = splitLocal(readLocal(custom) ?? presetTime("hour", current));
  const today = splitLocal(current).date;

  const choose = (date: string, time: string) => {
    onCustom(`${date}T${time}`);
    onPick("custom");
  };

  return (
    <div className={styles.picker}>
      {label ? (
        <span className={styles.label} id={`${id}-label`}>
          {label}
        </span>
      ) : null}
      <div
        className={styles.grid}
        role="group"
        aria-label={label ? undefined : "When"}
        aria-labelledby={label ? `${id}-label` : undefined}
      >
        {REMINDER_PRESETS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={styles.chip}
            data-wide={item.key === "morning" || undefined}
            aria-pressed={pick === item.key}
            onClick={() => onPick(item.key)}
          >
            {item.label}
          </button>
        ))}
        <button
          type="button"
          className={styles.chip}
          data-full=""
          aria-pressed={pick === "custom"}
          onClick={() => {
            // Opens on the time now shown, so a small change is one tap.
            const start = splitLocal(
              at && !past ? at : presetTime("hour", current),
            );
            choose(start.date, start.time);
          }}
        >
          <CalendarClock size={16} aria-hidden="true" />
          Pick date &amp; time
        </button>
      </div>
      {pick === "custom" ? (
        <div className={styles.inputs}>
          <label className={styles.field}>
            <span>Date</span>
            <input
              type="date"
              value={picked.date}
              min={today}
              onChange={(event) => {
                if (event.target.value) choose(event.target.value, picked.time);
              }}
            />
          </label>
          <label className={styles.field}>
            <span>Time</span>
            <input
              type="time"
              value={picked.time}
              onChange={(event) => {
                if (event.target.value) choose(picked.date, event.target.value);
              }}
            />
          </label>
        </div>
      ) : null}
      {at ? (
        <p
          className={styles.result}
          data-past={past || undefined}
          role="status"
          aria-live="polite"
        >
          <span className={styles.resultIcon} aria-hidden="true">
            <BellRing size={16} />
          </span>
          {past ? (
            <span>That time has passed. Pick a later one.</span>
          ) : (
            <span>
              Reminds you <strong>{reminderWords(at, current)}</strong>
            </span>
          )}
        </p>
      ) : null}
    </div>
  );
}
