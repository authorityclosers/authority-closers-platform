"use client";

import { useEffect, useId, useState } from "react";

import type { Allowance } from "../acquisition-client";
import styles from "./allowance-ring.module.css";

const RADIUS = 15;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The verified allowance as an animated ring in the top bar. The share and
 * percentage are computed from the session's own allowance, never estimated;
 * nothing renders until the caller has an actual allowance.
 */
export function AllowanceRing({ allowance }: { allowance?: Allowance | null }) {
  const gradient = `ring-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  // Draw the arc after mount so it sweeps in from empty.
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  if (!allowance) return null;

  const ring = (share: number, sweep: boolean) => (
    <svg className={styles.ring} viewBox="0 0 36 36" aria-hidden="true">
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" className={styles.stopStart} />
          <stop offset="100%" className={styles.stopEnd} />
        </linearGradient>
      </defs>
      <circle className={styles.track} cx="18" cy="18" r={RADIUS} />
      <circle
        className={styles.value}
        cx="18"
        cy="18"
        r={RADIUS}
        stroke={`url(#${gradient})`}
        strokeDasharray={CIRCUMFERENCE}
        strokeDashoffset={drawn ? CIRCUMFERENCE * (1 - share) : CIRCUMFERENCE}
      />
      {sweep ? (
        <circle className={styles.sweep} cx="18" cy="18" r={RADIUS} />
      ) : null}
    </svg>
  );

  if (allowance.unlimited)
    return (
      <div
        className={styles.meter}
        data-level="unlimited"
        title="Unlimited analysis time"
        data-minutes-meter
      >
        {ring(1, true)}
        <span className={styles.center} aria-hidden="true">
          ∞
        </span>
        <span className={styles.text} aria-hidden="true">
          <strong>Unlimited</strong>
          <small>analysis time</small>
        </span>
        <span className={styles.visuallyHidden}>Unlimited analysis time</span>
      </div>
    );

  const share =
    allowance.allowance_seconds > 0
      ? Math.min(1, allowance.available_seconds / allowance.allowance_seconds)
      : 0;
  const percent = Math.round(share * 100);
  const left = Math.floor(allowance.available_seconds / 60);
  const total = Math.floor(allowance.allowance_seconds / 60);
  const text = `${left} of ${total} trial minutes left`;
  return (
    <div
      className={styles.meter}
      data-level={share === 0 ? "empty" : share < 0.2 ? "low" : "ok"}
      role="meter"
      aria-label="Trial minutes left"
      aria-valuemin={0}
      aria-valuemax={allowance.allowance_seconds}
      aria-valuenow={allowance.available_seconds}
      aria-valuetext={text}
      title={text}
      data-minutes-meter
    >
      {ring(share, false)}
      <span className={styles.center} aria-hidden="true">
        {percent}%
      </span>
      <span className={styles.text} aria-hidden="true">
        <strong>{left} min left</strong>
        <small>of {total} min</small>
      </span>
      <span className={styles.visuallyHidden}>
        {left} of {total} left
      </span>
    </div>
  );
}
