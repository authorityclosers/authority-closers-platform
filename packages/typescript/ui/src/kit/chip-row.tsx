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
  end = null,
  format = String,
}: {
  /** What the chips choose, for a screen reader: "Stage". */
  label: string;
  items: readonly RowChip<T>[];
  value: T;
  onChange: (key: T) => void;
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
        {...edges}
      >
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
