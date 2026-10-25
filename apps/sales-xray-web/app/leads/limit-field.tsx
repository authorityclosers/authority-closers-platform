"use client";

/**
 * An open-lead limit (owner, 25 Oct 2026: a seller showed "168 / 50" with no
 * way to say "no limit"): a whole number from 1 to 1000, or No limit. Used on
 * a seller's rules (their profile and Lead rules) and for new sellers.
 */

import styles from "./limit-field.module.css";

export type LimitDraft = { none: boolean; value: string };

export const LIMIT_RULE =
  "Open-lead limit is a whole number from 1 to 1000, or No limit.";

/** The draft for a saved limit; null is No limit. */
export function limitDraft(
  max: number | null | undefined,
  fallback = 50,
): LimitDraft {
  return max === null
    ? { none: true, value: String(fallback) }
    : { none: false, value: String(max ?? fallback) };
}

/** The limit to save: a number, null for No limit, undefined when not valid. */
export function readLimit(draft: LimitDraft): number | null | undefined {
  if (draft.none) return null;
  const max = Number(draft.value.trim());
  return draft.value.trim() && Number.isInteger(max) && max >= 1 && max <= 1000
    ? max
    : undefined;
}

/** Open leads against the limit: "31/50", or "31" with no limit. */
export function openWords(open: number, max: number | null): string {
  return max === null ? `${open}` : `${open}/${max}`;
}

/** Leads over the limit (the server's count, else worked out). */
export function overBy(rep: {
  open_leads: number;
  max_open: number | null;
  over_capacity?: number;
}): number {
  if (rep.over_capacity !== undefined) return Math.max(0, rep.over_capacity);
  return rep.max_open === null ? 0 : Math.max(0, rep.open_leads - rep.max_open);
}

export function LimitField({
  id,
  label,
  hint,
  draft,
  onChange,
}: {
  id: string;
  label: string;
  /** A line under the field, e.g. "Organisation default". */
  hint?: string;
  draft: LimitDraft;
  onChange: (next: LimitDraft) => void;
}) {
  return (
    <fieldset className={styles.limit}>
      <legend className={styles.label}>{label}</legend>
      <div className={styles.row}>
        <input
          id={id}
          className={styles.number}
          inputMode="numeric"
          aria-label={label}
          value={draft.none ? "" : draft.value}
          placeholder={draft.none ? "No limit" : undefined}
          disabled={draft.none}
          onChange={(event) =>
            onChange({ ...draft, value: event.target.value })
          }
        />
        <label className={styles.none}>
          <input
            type="checkbox"
            checked={draft.none}
            onChange={(event) =>
              onChange({ ...draft, none: event.target.checked })
            }
          />
          No limit
        </label>
      </div>
      {hint ? <p className={styles.hint}>{hint}</p> : null}
    </fieldset>
  );
}
