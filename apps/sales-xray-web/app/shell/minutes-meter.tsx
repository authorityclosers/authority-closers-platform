import type { CSSProperties } from "react";

import type { Allowance } from "../acquisition-client";
import styles from "./minutes-meter.module.css";

/**
 * The verified allowance from the session read, never an estimate. Nothing
 * renders until the caller has an actual allowance.
 */
export function MinutesMeter({
  allowance,
  variant = "rail",
}: {
  allowance?: Allowance | null;
  variant?: "rail" | "pill";
}) {
  if (!allowance) return null;
  if (allowance.unlimited)
    return (
      <p className={styles.meter} data-variant={variant} data-minutes-meter>
        <span className={styles.label}>Unlimited testing</span>
      </p>
    );
  const left = Math.floor(allowance.available_seconds / 60);
  const total = Math.floor(allowance.allowance_seconds / 60);
  const text = `${left} of ${total} trial minutes left`;
  if (variant === "pill")
    return (
      <p className={styles.meter} data-variant="pill" data-minutes-meter>
        <span className={styles.value} aria-hidden="true">
          {left} min left
        </span>
        <span className={styles.visuallyHidden}>{text}</span>
      </p>
    );
  const fill =
    allowance.allowance_seconds > 0
      ? Math.min(1, allowance.available_seconds / allowance.allowance_seconds)
      : 0;
  return (
    <div className={styles.meter} data-variant="rail" data-minutes-meter>
      <div className={styles.row}>
        <span className={styles.label}>Trial minutes</span>
        <span className={styles.value}>
          {left} of {total} left
        </span>
      </div>
      <div
        className={styles.track}
        role="meter"
        aria-label="Trial minutes left"
        aria-valuemin={0}
        aria-valuemax={allowance.allowance_seconds}
        aria-valuenow={allowance.available_seconds}
        aria-valuetext={text}
        style={{ "--lx-meter-fill": fill } as CSSProperties}
      >
        <span className={styles.fill} />
      </div>
    </div>
  );
}
