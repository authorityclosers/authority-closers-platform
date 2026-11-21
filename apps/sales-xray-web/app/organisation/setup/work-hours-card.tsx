"use client";

/**
 * Work hours on the lead rules page, in the settings family (v1.93, round-2
 * board 3, 22 Nov 2026): one card like the others (24 px inside, no header
 * strip), white time fields, the chosen days solid deep-green pills, the two
 * choices as the family's own check boxes. It edits a draft; the page's one
 * Save sends it with the same payload as before (`saveWorkHours`).
 */
import { Check } from "lucide-react";
import type { WorkHours } from "../../leads/leads-client";
import card from "./lead-split.module.css";
import styles from "./rules.module.css";

export const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export type HoursDraft = {
  /** False: no work hours (the payload's empty days). */
  set: boolean;
  days: number[];
  start: string;
  end: string;
  pause: boolean;
  lunch: { start: string; end: string } | null;
};

const DEFAULT_DAYS = [0, 1, 2, 3, 4, 5];

export function hoursDraft(current: WorkHours | null | undefined): HoursDraft {
  const set = !!current?.days?.length;
  return {
    set,
    days: set ? [...current!.days] : DEFAULT_DAYS,
    start: current?.start ?? "09:30",
    end: current?.end ?? "19:00",
    pause: current?.pause_leads ?? true,
    lunch: current?.breaks?.[0] ? { ...current.breaks[0] } : null,
  };
}

export function hoursChanged(
  draft: HoursDraft,
  current: WorkHours | null | undefined,
): boolean {
  const saved = hoursDraft(current);
  if (draft.set !== saved.set) return true;
  if (!draft.set) return false;
  return (
    draft.days.join() !== saved.days.join() ||
    draft.start !== saved.start ||
    draft.end !== saved.end ||
    draft.pause !== saved.pause ||
    JSON.stringify(draft.lunch) !== JSON.stringify(saved.lunch)
  );
}

/** Why these hours can't be saved, in plain words; null when they can. */
export function hoursProblem(draft: HoursDraft): string | null {
  if (!draft.set) return null;
  if (!draft.days.length) return "Pick at least one work day.";
  if (draft.start >= draft.end)
    return "Work ends after it starts. Pick the hours again.";
  const { lunch } = draft;
  if (
    lunch &&
    !(
      draft.start <= lunch.start &&
      lunch.start < lunch.end &&
      lunch.end <= draft.end
    )
  )
    return "The break sits inside work hours. Pick its time again.";
  return null;
}

/** The payload `saveWorkHours` takes; no days clears them. */
export function hoursPayload(draft: HoursDraft) {
  return {
    days: draft.set ? draft.days : [],
    start: draft.start,
    end: draft.end,
    pause_leads: draft.pause,
    breaks: draft.lunch ? [draft.lunch] : [],
  };
}

/** "9:30 am" from "09:30". */
export function clock(value: string): string {
  const [h = 0, m = 0] = value.split(":").map(Number);
  const hour = h % 12 || 12;
  return `${hour}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

/** "Mon–Sat", "Mon, Wed, Fri", "Every day". */
export function dayWords(days: readonly number[]): string {
  const sorted = [...days].sort((a, b) => a - b);
  if (sorted.length === 7) return "Every day";
  const run = sorted.every((day, at) => at === 0 || day === sorted[at - 1] + 1);
  if (run && sorted.length > 2)
    return `${DAYS[sorted[0]]}–${DAYS[sorted[sorted.length - 1]]}`;
  return sorted.map((day) => DAYS[day]).join(", ");
}

function Box({
  checked,
  onChange,
  disabled,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  children: string;
}) {
  return (
    <label className={styles.check}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className={styles.box} aria-hidden="true">
        <Check size={14} strokeWidth={3} />
      </span>
      <span>{children}</span>
    </label>
  );
}

function Time({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className={styles.time}>
      <span>{label}</span>
      <input
        type="time"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function WorkHoursCard({
  draft,
  current,
  onChange,
  disabled = false,
}: {
  draft: HoursDraft;
  current: WorkHours | null | undefined;
  onChange: (draft: HoursDraft) => void;
  disabled?: boolean;
}) {
  const set = (part: Partial<HoursDraft>) => onChange({ ...draft, ...part });
  const problem = hoursProblem(draft);
  const status = current?.days?.length
    ? current.inside
      ? { tone: "good", words: "Open now" }
      : { tone: "amber", words: "Closed now" }
    : null;
  return (
    <section className={card.card} aria-labelledby="work-hours-title">
      <div className={card.head}>
        <h3 id="work-hours-title" className={card.title}>
          Work hours
          {status ? (
            <span className={styles.chip} data-tone={status.tone}>
              {status.words}
            </span>
          ) : null}
        </h3>
        {draft.set && current?.days?.length ? (
          <button
            type="button"
            className={styles.quiet}
            disabled={disabled}
            onClick={() => set({ set: false })}
          >
            Clear
          </button>
        ) : null}
      </div>
      {draft.set ? (
        <>
          <p className={card.sub}>
            India time. Calls outside these hours stay on the seller&apos;s
            phone and are never logged.
          </p>
          <div className={styles.days} role="group" aria-label="Work days">
            {DAYS.map((label, day) => (
              <button
                key={label}
                type="button"
                aria-pressed={draft.days.includes(day)}
                disabled={disabled}
                onClick={() =>
                  set({
                    days: draft.days.includes(day)
                      ? draft.days.filter((item) => item !== day)
                      : [...draft.days, day].sort((a, b) => a - b),
                  })
                }
              >
                {label}
              </button>
            ))}
          </div>
          <div className={styles.times}>
            <Time
              label="Starts"
              value={draft.start}
              disabled={disabled}
              onChange={(start) => set({ start })}
            />
            <Time
              label="Ends"
              value={draft.end}
              disabled={disabled}
              onChange={(end) => set({ end })}
            />
          </div>
          <div className={styles.checks}>
            <Box
              checked={draft.pause}
              disabled={disabled}
              onChange={(pause) => set({ pause })}
            >
              New leads wait outside work hours, then go out when work starts
            </Box>
            <Box
              checked={draft.lunch !== null}
              disabled={disabled}
              onChange={(on) =>
                set({ lunch: on ? { start: "13:00", end: "14:00" } : null })
              }
            >
              A set break every work day (lunch), not counted against sellers
            </Box>
          </div>
          {draft.lunch ? (
            <div className={styles.times}>
              <Time
                label="Break starts"
                value={draft.lunch.start}
                disabled={disabled}
                onChange={(start) => set({ lunch: { ...draft.lunch!, start } })}
              />
              <Time
                label="Break ends"
                value={draft.lunch.end}
                disabled={disabled}
                onChange={(end) => set({ lunch: { ...draft.lunch!, end } })}
              />
            </div>
          ) : null}
          {problem ? (
            <p className={styles.problem} role="status">
              {problem}
            </p>
          ) : null}
        </>
      ) : (
        <>
          <p className={card.sub}>
            Not set: leads go out any time and every minute counts.
          </p>
          <button
            type="button"
            className={styles.outline}
            disabled={disabled}
            onClick={() =>
              set({
                set: true,
                days: draft.days.length ? draft.days : DEFAULT_DAYS,
              })
            }
          >
            Set work hours
          </button>
        </>
      )}
    </section>
  );
}
