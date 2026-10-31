"use client";

/**
 * Revenue in Growth, Analytics (owner meeting, 28 Oct 2026): what Won leads were
 * worth in the period, by Inbound or Cold and by seller (by name, never ranked).
 * Wins with no amount are counted, never guessed. The page that owns Analytics
 * mounts it (performance-view.tsx) beside its own numbers.
 */

import { useEffect, useState } from "react";

import {
  inr,
  readRevenueBreakdown,
  type RevenueBreakdown,
} from "../dashboard/revenue-client";
import styles from "../dashboard/revenue.module.css";

export function RevenueSplit({ days }: { days: 7 | 30 | 90 }) {
  const [split, setSplit] = useState<RevenueBreakdown | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const read = await readRevenueBreakdown(days, controller.signal);
        if (!controller.signal.aborted) setSplit(read);
      } catch {
        // Analytics stands without it.
      }
    })();
    return () => controller.abort();
  }, [days]);
  if (!split || (split.deals === 0 && split.amount_not_set === 0)) return null;
  const most = Math.max(1, ...split.by_side.map((line) => line.won));
  return (
    <section className={styles.detail} aria-label="Revenue">
      <div className={styles.line}>
        <span className={styles.amounts}>
          <strong>{inr(split.won)}</strong>
          <span>
            {" "}
            won · {split.deals} deal{split.deals === 1 ? "" : "s"}
          </span>
        </span>
        {split.amount_not_set ? (
          <span className={styles.small}>
            {split.amount_not_set} without an amount
          </span>
        ) : null}
      </div>
      <ul className={styles.sellers} aria-label="By Inbound or Cold">
        {split.by_side.map((line) => (
          <li key={line.key} className={styles.seller}>
            <div className={styles.line}>
              <span className={styles.sellerName}>{line.label}</span>
              <span className={styles.amounts}>
                <strong>{inr(line.won)}</strong>
              </span>
            </div>
            <span className={styles.track} aria-hidden="true">
              <span
                className={styles.fill}
                style={{ width: `${(line.won / most) * 100}%` }}
              />
            </span>
          </li>
        ))}
      </ul>
      {split.by_seller.length > 1 ? (
        <ul className={styles.sellers} aria-label="By seller">
          {split.by_seller.map((line) => (
            <li key={line.key} className={styles.line}>
              <span className={styles.sellerName}>{line.label}</span>
              <span className={styles.amounts}>
                <strong>{inr(line.won)}</strong>
                <span> · {line.deals}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
