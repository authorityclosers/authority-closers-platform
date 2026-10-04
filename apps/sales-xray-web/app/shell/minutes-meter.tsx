import { Info } from "lucide-react";
import type { CSSProperties } from "react";

import type { Allowance } from "../acquisition-client";
import { formatAnalysisTime } from "../analysis-time";
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
      <p
        className={styles.meter}
        data-variant={variant}
        data-minutes-meter
        title="Analysis time balance unavailable"
      >
        <span className={styles.label}>Time unavailable</span>
      </p>
    );
  const left = Math.floor(allowance.available_seconds / 60);
  const secs = allowance.available_seconds % 60;
  const total = Math.floor(allowance.allowance_seconds / 60);
  const availableText =
    secs > 0 ? `${left}m ${secs}s available` : `${left}m available`;
  const text = `${left} of ${total} analysis minutes left`;
  const balanceText = `${left} of ${total} left`;
  if (variant === "pill")
    return (
      <p
        className={styles.meter}
        data-variant="pill"
        data-minutes-meter
        title={text}
      >
        <span className={styles.value} aria-hidden="true">
          {formatAnalysisTime(allowance.available_seconds)} left
        </span>
        <span className={styles.visuallyHidden}>{text}</span>
      </p>
    );
  const fill =
    allowance.allowance_seconds > 0
      ? Math.min(1, allowance.available_seconds / allowance.allowance_seconds)
      : 0;
  const strokeDashoffset = 100 - fill * 100;
  return (
    <div className={styles.meter} data-variant="rail" data-minutes-meter>
      <div className={styles.usageRow}>
        <svg className={styles.donut} viewBox="0 0 36 36" aria-hidden="true">
          <path
            className={styles.donutBg}
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none"
            stroke="var(--lx-line-soft)"
            strokeWidth="3.5"
          />
          <path
            className={styles.donutVal}
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none"
            stroke="var(--lx-teal)"
            strokeWidth="3.5"
            strokeDasharray="100, 100"
            strokeDashoffset={strokeDashoffset}
          />
        </svg>
        <span className={styles.availableLabel}>{availableText}</span>
        <span className={styles.infoIcon} title={text} aria-hidden="true">
          <Info size={15} />
        </span>
      </div>
      <div
        className={styles.track}
        role="meter"
        aria-label="Analysis time left"
        aria-valuemin={0}
        aria-valuemax={allowance.allowance_seconds}
        aria-valuenow={allowance.available_seconds}
        aria-valuetext={text}
        style={{ "--lx-meter-fill": fill } as CSSProperties}
      >
        <span className={styles.fill} />
      </div>
      <span className={styles.visuallyHidden}>{balanceText}</span>
    </div>
  );
}
