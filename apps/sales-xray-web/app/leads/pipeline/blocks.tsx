"use client";

/**
 * The stage sheet's and the meeting sheet's parts (Lead OS): when to follow up,
 * the meeting (date, time, kind, link or place), a reason, why a call didn't
 * connect, and a note. Each sheet shows only the parts its move asks for.
 */

import {
  localInputValue,
  nextCallTime,
  NOT_CONNECTED_REASONS,
  when,
  type CallTime,
} from "../leads-client";
import {
  MEETING_MODES,
  type MeetingMode,
  type Reason,
} from "./pipeline-client";
import styles from "./pipeline.module.css";

/* ---------- when to follow up ---------- */

export type WhenPick = CallTime | "custom";

const WHEN_PICKS: { key: WhenPick; label: string }[] = [
  { key: "hour", label: "In 1 hour" },
  { key: "evening", label: "This evening" },
  { key: "morning", label: "Tomorrow morning" },
  { key: "week", label: "Next week" },
  { key: "custom", label: "Pick a time" },
];

export function whenOf(
  pick: WhenPick | null,
  custom: string,
  now = new Date(),
) {
  if (pick === null) return null;
  if (pick !== "custom") return nextCallTime(pick, now);
  const at = custom ? new Date(custom) : null;
  return at && !Number.isNaN(at.getTime()) ? at : null;
}

export function WhenBlock({
  label,
  pick,
  custom,
  onPick,
  onCustom,
  required,
}: {
  label: string;
  pick: WhenPick | null;
  custom: string;
  onPick: (pick: WhenPick) => void;
  onCustom: (value: string) => void;
  required?: boolean;
}) {
  const at = whenOf(pick, custom);
  return (
    <fieldset className={styles.block}>
      <legend className={styles.blockLabel}>
        {label}
        {required ? null : <span className={styles.optional}> · optional</span>}
      </legend>
      <div className={styles.chips}>
        {WHEN_PICKS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={styles.chip}
            aria-pressed={pick === item.key}
            onClick={() => onPick(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {pick === "custom" ? (
        <label className={styles.field}>
          <span>Date and time</span>
          <input
            type="datetime-local"
            value={custom}
            min={localInputValue(new Date())}
            onChange={(event) => onCustom(event.target.value)}
          />
        </label>
      ) : at ? (
        <p className={styles.hint}>{capital(when(at.toISOString()))}</p>
      ) : null}
    </fieldset>
  );
}

/* ---------- the meeting ---------- */

export type MeetingDraft = {
  pick: "tomorrow_11" | "tomorrow_17" | "in_2_days" | "custom" | null;
  custom: string;
  mode: MeetingMode | null;
  link: string;
  location: string;
};

export const EMPTY_MEETING: MeetingDraft = {
  pick: null,
  custom: "",
  mode: null,
  link: "",
  location: "",
};

const MEETING_PICKS: {
  key: Exclude<MeetingDraft["pick"], null>;
  label: string;
}[] = [
  { key: "tomorrow_11", label: "Tomorrow 11 am" },
  { key: "tomorrow_17", label: "Tomorrow 5 pm" },
  { key: "in_2_days", label: "In 2 days" },
  { key: "custom", label: "Pick a time" },
];

export function meetingStart(
  draft: MeetingDraft,
  now = new Date(),
): Date | null {
  if (draft.pick === null) return null;
  if (draft.pick === "custom") {
    const at = draft.custom ? new Date(draft.custom) : null;
    return at && !Number.isNaN(at.getTime()) ? at : null;
  }
  const at = new Date(now);
  at.setSeconds(0, 0);
  at.setDate(at.getDate() + (draft.pick === "in_2_days" ? 2 : 1));
  at.setHours(draft.pick === "tomorrow_17" ? 17 : 11, 0, 0, 0);
  return at;
}

/** Whether the meeting has what the server needs: a time and a kind. */
export function meetingReady(draft: MeetingDraft): boolean {
  return meetingStart(draft) !== null && draft.mode !== null;
}

export function MeetingBlock({
  draft,
  onChange,
}: {
  draft: MeetingDraft;
  onChange: (next: MeetingDraft) => void;
}) {
  const at = meetingStart(draft);
  const online = draft.mode === "zoom" || draft.mode === "google_meet";
  return (
    <fieldset className={styles.block}>
      <legend className={styles.blockLabel}>When is the meeting?</legend>
      <div className={styles.chips}>
        {MEETING_PICKS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={styles.chip}
            aria-pressed={draft.pick === item.key}
            onClick={() => onChange({ ...draft, pick: item.key })}
          >
            {item.label}
          </button>
        ))}
      </div>
      {draft.pick === "custom" ? (
        <label className={styles.field}>
          <span>Date and time</span>
          <input
            type="datetime-local"
            value={draft.custom}
            min={localInputValue(new Date())}
            onChange={(event) =>
              onChange({ ...draft, custom: event.target.value })
            }
          />
        </label>
      ) : at ? (
        <p className={styles.hint}>{capital(when(at.toISOString()))}</p>
      ) : null}
      <span className={styles.blockLabel}>How</span>
      <div className={styles.chips}>
        {MEETING_MODES.map((item) => (
          <button
            key={item.key}
            type="button"
            className={styles.chip}
            aria-pressed={draft.mode === item.key}
            onClick={() => onChange({ ...draft, mode: item.key })}
          >
            {item.label}
          </button>
        ))}
      </div>
      {online ? (
        <label className={styles.field}>
          <span>Meeting link · optional</span>
          <input
            type="url"
            inputMode="url"
            placeholder="https://"
            value={draft.link}
            onChange={(event) =>
              onChange({ ...draft, link: event.target.value })
            }
          />
        </label>
      ) : draft.mode === "in_person" ? (
        <label className={styles.field}>
          <span>Where · optional</span>
          <input
            type="text"
            autoComplete="street-address"
            value={draft.location}
            onChange={(event) =>
              onChange({ ...draft, location: event.target.value })
            }
          />
        </label>
      ) : null}
    </fieldset>
  );
}

/* ---------- reasons ---------- */

export function ReasonBlock({
  label,
  reasons,
  value,
  note,
  onPick,
  onNote,
  required,
}: {
  label: string;
  reasons: Reason[];
  value: string | null;
  note: string;
  onPick: (key: string) => void;
  onNote: (value: string) => void;
  required?: boolean;
}) {
  return (
    <fieldset className={styles.block}>
      <legend className={styles.blockLabel}>
        {label}
        {required ? null : <span className={styles.optional}> · optional</span>}
      </legend>
      <div className={styles.chips}>
        {reasons.map((reason) => (
          <button
            key={reason.key}
            type="button"
            className={styles.chip}
            aria-pressed={value === reason.key}
            onClick={() => onPick(reason.key)}
          >
            {reason.label}
          </button>
        ))}
      </div>
      {value === "other" ? (
        <label className={styles.field}>
          <span>What happened</span>
          <input
            type="text"
            value={note}
            maxLength={500}
            onChange={(event) => onNote(event.target.value)}
          />
        </label>
      ) : null}
    </fieldset>
  );
}

export function NcReasonBlock({
  value,
  onPick,
}: {
  value: string | null;
  onPick: (key: string) => void;
}) {
  return (
    <fieldset className={styles.block}>
      <legend className={styles.blockLabel}>Why didn&apos;t it connect?</legend>
      <div className={styles.chips}>
        {NOT_CONNECTED_REASONS.map((reason) => (
          <button
            key={reason.key}
            type="button"
            className={styles.chip}
            aria-pressed={value === reason.key}
            onClick={() => onPick(reason.key)}
          >
            {reason.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function NoteBlock({
  value,
  onChange,
  label = "Note",
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
}) {
  return (
    <label className={`${styles.block} ${styles.field}`}>
      <span className={styles.blockLabel}>
        {label}
        <span className={styles.optional}> · optional</span>
      </span>
      <textarea
        rows={2}
        maxLength={500}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
