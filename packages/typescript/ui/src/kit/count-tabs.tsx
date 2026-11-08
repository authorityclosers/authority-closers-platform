"use client";

/**
 * Text tabs with their counts (Leads L1, chosen by the owner 8 Nov 2026:
 * "To call 128 · Follow-ups 12 · All leads 387"). Each tab hugs its words, the
 * chosen one underlined in the accent; the row stays one line and scrolls
 * sideways where it doesn't fit, never wrapping or cutting a word (bugs 165,
 * 180), and the chosen tab comes into view. One count style on every tab (bug
 * 167).
 */

import styles from "./count-tabs.module.css";
import { sideScrollFades, useSideScroll } from "./side-scroll";

export type CountTab<T extends string> = {
  key: T;
  label: string;
  /** The tab's count once known; none while it is being counted. */
  count?: number | null;
};

export function CountTabs<T extends string>({
  label,
  items,
  value,
  onChange,
  format = String,
}: {
  /** What the tabs choose, for a screen reader: "Leads to show". */
  label: string;
  items: readonly CountTab<T>[];
  value: T;
  onChange: (key: T) => void;
  /** A count in words, short enough for a phone (7, 999, 1.2K). */
  format?: (count: number) => string;
}) {
  const { ref, edges } = useSideScroll<HTMLDivElement>(
    '[aria-selected="true"]',
    value,
  );
  return (
    <div ref={ref} className={`${styles.row} ${sideScrollFades}`} {...edges}>
      <div className={styles.tabs} role="tablist" aria-label={label}>
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            className={styles.tab}
            aria-selected={item.key === value}
            onClick={() => {
              if (item.key !== value) onChange(item.key);
            }}
          >
            <span className={styles.word}>{item.label}</span>
            {typeof item.count === "number" ? (
              <>
                {" "}
                <span className={styles.count}>{format(item.count)}</span>
              </>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}
