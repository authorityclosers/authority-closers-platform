"use client";

/**
 * One row of filter chips with their counts, and an action pinned at its end
 * (Leads L1, chosen by the owner 8 Nov 2026: "All stages 128 · New lead 46 ·
 * Not connected 38 …", then Filter). Chips size to their words and never wrap:
 * the row scrolls sideways, fading under the pinned end, and the chosen chip
 * comes into view. The chosen chip carries a check as well as its tint, two
 * cues rather than colour alone.
 */

import type { ReactNode } from "react";

import styles from "./chip-row.module.css";
import { sideScrollFades, useSideScroll } from "./side-scroll";

/** The edge fades' width (side-scroll.module.css). */
const CLEAR_START = 28;
/** The pinned end covers the row's last 32 px (chip-row.module.css), and a
 * focus ring needs room past that. */
const CLEAR_END = 44;

/**
 * Brings a chip taking keyboard focus clear of the fades and the pinned end.
 * The browser scrolls a focused chip in only when none of it shows, so one
 * partly in view took focus under Filter (QA robot a83aab5d and e3a00def,
 * 8 Nov 2026, /leads at 363 and 390). A tap's focus leaves the row as it is.
 */
function clearOfEdges(row: HTMLElement, target: EventTarget) {
  if (!(target instanceof HTMLElement) || target === row) return;
  let keyboard = false;
  try {
    keyboard = target.matches(":focus-visible");
  } catch {
    return;
  }
  if (!keyboard) return;
  const box = row.getBoundingClientRect();
  const chip = target.getBoundingClientRect();
  const before = box.left + CLEAR_START - chip.left;
  const past = chip.right - (box.right - CLEAR_END);
  if (before > 0) row.scrollLeft -= before;
  else if (past > 0) row.scrollLeft += past;
}

export type RowChip<T extends string> = {
  key: T;
  label: string;
  /** The chip's count once known. */
  count?: number | null;
};

export function ChipRow<T extends string>({
  label,
  items,
  value,
  onChange,
  start = null,
  end = null,
  format = String,
}: {
  /** What the chips choose, for a screen reader: "Stage". */
  label: string;
  items: readonly RowChip<T>[];
  value: T;
  onChange: (key: T) => void;
  /** First in the row, inside the scroll: a chip that opens a list. */
  start?: ReactNode;
  /** Pinned at the row's end, outside the scroll: a Filter button. */
  end?: ReactNode;
  format?: (count: number) => string;
}) {
  const { ref, edges } = useSideScroll<HTMLDivElement>(
    '[aria-pressed="true"]',
    value,
  );
  return (
    <div className={styles.wrap}>
      <div
        ref={ref}
        className={`${styles.row} ${sideScrollFades}`}
        role="group"
        aria-label={label}
        onFocus={(event) => clearOfEdges(event.currentTarget, event.target)}
        {...edges}
      >
        {start}
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            className={styles.chip}
            aria-pressed={item.key === value}
            onClick={() => {
              if (item.key !== value) onChange(item.key);
            }}
          >
            {item.key === value ? (
              <svg
                className={styles.check}
                viewBox="0 0 16 16"
                aria-hidden="true"
              >
                <path d="M3.5 8.5l3 3 6-7" />
              </svg>
            ) : null}
            <span>{item.label}</span>
            {typeof item.count === "number" ? (
              <>
                {" "}
                <span className={styles.count}>{format(item.count)}</span>
              </>
            ) : null}
          </button>
        ))}
      </div>
      {end ? <div className={styles.end}>{end}</div> : null}
    </div>
  );
}
