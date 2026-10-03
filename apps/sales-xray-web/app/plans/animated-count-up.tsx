"use client";

import { useEffect, useState } from "react";
import { count } from "../billing/money";
import styles from "./plans.module.css";

export function AnimatedCountUp({
  targetMinutes,
  targetCredits,
  durationMs = 1200,
}: {
  targetMinutes: number;
  targetCredits?: number;
  durationMs?: number;
}) {
  const [currentMinutes, setCurrentMinutes] = useState(0);
  const [currentCredits, setCurrentCredits] = useState(0);

  useEffect(() => {
    let startTimestamp: number | null = null;
    let animId: number;

    const step = (timestamp: number) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const elapsed = timestamp - startTimestamp;
      const progress = Math.min(elapsed / durationMs, 1);
      // ease-out cubic
      const ease = 1 - Math.pow(1 - progress, 3);

      setCurrentMinutes(Math.round(ease * targetMinutes));
      setCurrentCredits(Math.round(ease * (targetCredits ?? 0)));

      if (progress < 1) {
        animId = requestAnimationFrame(step);
      }
    };

    animId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(animId);
  }, [targetMinutes, targetCredits, durationMs]);

  return (
    <div className={styles.animatedCounterBox} aria-live="polite">
      <div className={styles.counterRow}>
        <div className={styles.counterItem}>
          <span className={styles.counterValue}>+{count(currentMinutes)}</span>
          <span className={styles.counterLabel}>Analysis minutes</span>
        </div>
        {targetCredits !== undefined ? (
          <>
            <div className={styles.counterDivider} aria-hidden="true" />
            <div className={styles.counterItem}>
              <span className={styles.counterValue}>
                +{count(currentCredits)}
              </span>
              <span className={styles.counterLabel}>Credits</span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
