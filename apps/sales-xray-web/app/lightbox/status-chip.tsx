import type { ReactNode } from "react";
import styles from "./status-chip.module.css";

export type StatusTone =
  | "ready"
  | "analysing"
  | "needs-you"
  | "paused"
  | "neutral"
  | "danger";

/** Qualitative status only; the label carries the meaning, not the colour. */
export function StatusChip({
  tone,
  live = false,
  children,
  className = "",
}: {
  tone: StatusTone;
  /** A decorative activity dot for work confirmed as running. */
  live?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`${styles.chip} ${className}`} data-tone={tone}>
      {live ? (
        <span className={styles.dot} aria-hidden="true" data-live />
      ) : null}
      {children}
    </span>
  );
}
