"use client";

/**
 * Inbound Leads | Cold Leads (Leads redesign, sections 1 and 6; Dipak's final
 * model, 30–31 Oct 2026): a two-option selector, not an on/off switch, so it
 * is always clear which group you are working in. One component for Leads and
 * Home. The chosen side is filled: Inbound with the brand accent, Cold with
 * slate blue. It keeps no state: Leads keeps the side in its address
 * (?side=cold) and opens on Inbound; Home keeps its own.
 */

import type { KeyboardEvent } from "react";

import styles from "./side-selector.module.css";

export type Side = "inbound" | "cold";

export const SIDES: readonly { key: Side; label: string }[] = [
  { key: "inbound", label: "Inbound Leads" },
  { key: "cold", label: "Cold Leads" },
];

export function SideSelector({
  value,
  onChange,
  notes,
  label = "Lead type",
}: {
  value: Side;
  onChange: (side: Side) => void;
  /** A short line under it for the chosen side ("Fresh enquiries"); optional. */
  notes?: Partial<Record<Side, string>>;
  label?: string;
}) {
  // A radio group: the arrow keys move between the two, as in any radio group.
  const onKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (
      !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)
    )
      return;
    event.preventDefault();
    const next: Side = value === "inbound" ? "cold" : "inbound";
    onChange(next);
    event.currentTarget.parentElement
      ?.querySelector<HTMLButtonElement>(`[data-side="${next}"]`)
      ?.focus();
  };
  const note = notes?.[value];
  return (
    <div className={styles.wrap}>
      <div role="radiogroup" aria-label={label} className={styles.selector}>
        {SIDES.map((side) => {
          const chosen = side.key === value;
          return (
            <button
              key={side.key}
              type="button"
              role="radio"
              aria-checked={chosen}
              tabIndex={chosen ? 0 : -1}
              data-side={side.key}
              className={styles.option}
              onClick={() => {
                if (!chosen) onChange(side.key);
              }}
              onKeyDown={onKey}
            >
              {side.label}
            </button>
          );
        })}
      </div>
      {note ? <p className={styles.note}>{note}</p> : null}
    </div>
  );
}
