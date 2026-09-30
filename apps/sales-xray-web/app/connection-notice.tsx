"use client";

import { CloudOff, RefreshCw } from "lucide-react";
import { useEffect, type CSSProperties } from "react";

import styles from "./connection-notice.module.css";

/** Seconds before the next automatic try: 5, 10, 20, then every 30. */
export function retryDelay(failures: number): number {
  return Math.min(30, 5 * 2 ** Math.max(0, failures - 1));
}

/**
 * A small corner card while the server cannot be reached. The page keeps its
 * frame behind it, the card tries again on its own, and a thin bar shows
 * when the next try happens.
 */
export function ConnectionNotice({
  message,
  failures,
  onRetry,
}: {
  message: string;
  failures: number;
  onRetry: () => void;
}) {
  const seconds = retryDelay(failures);
  useEffect(() => {
    const timer = window.setTimeout(onRetry, seconds * 1000);
    return () => window.clearTimeout(timer);
  }, [failures, onRetry, seconds]);

  return (
    <aside className={styles.card} aria-live="polite">
      <span className={styles.icon} aria-hidden="true">
        <CloudOff size={17} />
      </span>
      <div className={styles.copy}>
        <b>Can&apos;t reach Sales Xray</b>
        <p role="alert">{message}</p>
        <small>Trying again by itself in {seconds} s.</small>
      </div>
      <button type="button" className={styles.retry} onClick={onRetry}>
        <RefreshCw size={14} aria-hidden="true" /> Try again
      </button>
      <span
        key={failures}
        className={styles.timer}
        style={{ "--seconds": `${seconds}s` } as CSSProperties}
        aria-hidden="true"
      />
    </aside>
  );
}
