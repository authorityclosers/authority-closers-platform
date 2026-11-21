"use client";

/**
 * Off | On as the family's big pill switch (v1.90 Home: a sunken well, the
 * chosen pill solid deep green), for the lead rules page (v1.93, round-2
 * board 3, 22 Nov 2026). One control with role="switch", so a screen reader
 * hears one on/off switch, not two buttons.
 */
import styles from "./on-off.module.css";

export function OnOff({
  label,
  on,
  onChange,
  disabled = false,
  feature,
}: {
  label: string;
  on: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  /** data-sx-feature for the product's usage count. */
  feature?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={styles.switch}
      disabled={disabled}
      data-sx-feature={feature}
      onClick={() => onChange(!on)}
    >
      <span data-lit={on ? undefined : ""}>Off</span>
      <span data-lit={on ? "" : undefined}>On</span>
    </button>
  );
}
