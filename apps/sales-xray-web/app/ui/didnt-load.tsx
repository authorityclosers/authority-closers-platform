"use client";

/**
 * One pattern for a read that failed or hangs (v1.96 device polish, lane P:
 * on a backend 502, Plan showed three "Loading…" lines for ever, Leads swapped
 * shells and Home said it twice). The screen keeps its header and whatever it
 * already shows; one amber card says what didn't load, with Try again. A read
 * still loading after 8 seconds counts as failed (useLoadDeadline), so no
 * screen says "Loading…" for ever.
 */
import { CloudOff, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import styles from "./didnt-load.module.css";

export const LOAD_DEADLINE_MS = 8_000;

/** True once `loading` has stayed true for 8 s; false again as soon as it stops. */
export function useLoadDeadline(
  loading: boolean,
  ms: number = LOAD_DEADLINE_MS,
): boolean {
  const [late, setLate] = useState(false);
  if (!loading && late) setLate(false);
  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setLate(true), ms);
    return () => window.clearTimeout(timer);
  }, [loading, ms]);
  return loading && late;
}

export function DidntLoad({
  what,
  note = "What's already on screen is safe.",
  onRetry,
}: {
  /** What didn't load, as the card's title says it: "Your plan". */
  what: string;
  note?: string;
  onRetry?: () => void;
}) {
  return (
    <section className={styles.card} role="alert" data-didnt-load="">
      <span className={styles.icon} aria-hidden="true">
        <CloudOff size={18} />
      </span>
      <div className={styles.copy}>
        <b>{what} didn&apos;t load</b>
        <p>{note}</p>
      </div>
      {onRetry ? (
        <button type="button" className={styles.retry} onClick={onRetry}>
          <RefreshCw size={15} aria-hidden="true" /> Try again
        </button>
      ) : null}
    </section>
  );
}
