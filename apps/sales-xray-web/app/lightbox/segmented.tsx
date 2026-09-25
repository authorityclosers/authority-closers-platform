"use client";

import { useId, type ReactNode } from "react";
import styles from "./segmented.module.css";

export type SegmentedOption<T extends string> = Readonly<{
  value: T;
  label: ReactNode;
}>;

/** Native radios styled as segments: arrow keys and form semantics come free. */
export function Segmented<T extends string>({
  legend,
  value,
  options,
  onChange,
  hint,
  disabled = false,
  className = "",
}: {
  legend: ReactNode;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
  hint?: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  const name = useId();
  const hintId = `${name}-hint`;
  return (
    <fieldset
      className={`${styles.segmented} ${className}`}
      disabled={disabled}
      aria-describedby={hint ? hintId : undefined}
    >
      <legend className={styles.legend}>{legend}</legend>
      <div className={styles.track}>
        {options.map((option) => (
          <label key={option.value} className={styles.option}>
            <input
              className={styles.input}
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            <span className={styles.label}>{option.label}</span>
          </label>
        ))}
      </div>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
    </fieldset>
  );
}
