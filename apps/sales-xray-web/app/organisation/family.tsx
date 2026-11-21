/**
 * Small shared pieces of the settings family (sx-redesign board, owner 21 Nov
 * 2026): the progress ring a hero card carries, a person's initials circle,
 * and the switch of pills. Styles live in family.module.css.
 */
import type { ReactNode } from "react";

import styles from "./family.module.css";

/** A ring that fills to `done` of `total`, with its words in the middle. */
export function Ring({
  done,
  total,
  children,
  size = 96,
  tone,
  label,
}: {
  done: number;
  total: number;
  children: ReactNode;
  size?: number;
  tone?: "amber";
  /** What the ring says, for a screen reader. */
  label: string;
}) {
  const stroke = Math.max(7, Math.round(size / 11));
  const radius = 50 - (stroke / size) * 50;
  const length = 2 * Math.PI * radius;
  const share = total > 0 ? Math.min(1, Math.max(0, done / total)) : 0;
  return (
    <span
      className={styles.ring}
      style={{ ["--ring" as string]: `${size}px` }}
      data-tone={tone}
      role="img"
      aria-label={label}
    >
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle
          className={styles.ringTrack}
          cx="50"
          cy="50"
          r={radius}
          strokeWidth={(stroke / size) * 100}
        />
        <circle
          className={styles.ringArc}
          cx="50"
          cy="50"
          r={radius}
          strokeWidth={(stroke / size) * 100}
          strokeDasharray={length}
          strokeDashoffset={length * (1 - share)}
          style={{ opacity: share > 0 ? 1 : 0 }}
        />
      </svg>
      <span className={styles.ringText} aria-hidden="true">
        {children}
      </span>
    </span>
  );
}

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (
    parts.length > 1
      ? parts[0][0] + parts[parts.length - 1][0]
      : parts[0].slice(0, 2)
  ).toUpperCase();
}

/** The same soft colour for a person every time (a hash of their id). */
export function hueOf(key: string): string {
  let sum = 0;
  for (const char of key) sum = (sum * 31 + char.charCodeAt(0)) % 9973;
  return String(sum % 5);
}

export function Initials({
  name,
  id,
  photo,
  size,
}: {
  name: string;
  id: string;
  photo?: string | null;
  size?: number;
}) {
  return (
    <i
      className={styles.avatar}
      data-hue={hueOf(id)}
      aria-hidden="true"
      style={size ? { width: size, height: size } : undefined}
    >
      {/* The initials stay under a photo, so a photo still loading (or
          one that fails) never leaves a blank circle. */}
      {initialsOf(name)}
      {photo ? (
        // eslint-disable-next-line @next/next/no-img-element -- Private, session-bound photo; already small.
        <img
          src={photo}
          alt=""
          onError={(event) => {
            event.currentTarget.hidden = true;
          }}
        />
      ) : null}
    </i>
  );
}

/** A row of pills; the chosen one solid green (v1.90 Home). */
export function PillSwitch<K extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
  label: string;
}) {
  return (
    <div className={styles.switch} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          aria-pressed={option.key === value}
          onClick={() => onChange(option.key)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
