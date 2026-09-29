"use client";

import Link from "next/link";
import { useId, type CSSProperties } from "react";

import styles from "./brand-lockup.module.css";

// The Sales Xray mark: a glass x-ray lens gliding over a call's waveform.
// Inside the lens the waveform lights up; outside it stays a quiet trace.
const MARK_BARS = [
  { x: 9, height: 14 },
  { x: 16, height: 24 },
  { x: 23, height: 34 },
  { x: 30, height: 44 },
  { x: 37, height: 30 },
  { x: 44, height: 22 },
  { x: 51, height: 14 },
] as const;

export function BrandLockup({
  href,
  markOnly = false,
}: {
  href: string;
  markOnly?: boolean;
}) {
  return (
    <Link
      className={`${styles.brand}${markOnly ? ` ${styles.markOnly}` : ""}`}
      href={href}
      aria-label="Sales Xray home"
    >
      <BrandMark markOnly={markOnly} />
    </Link>
  );
}

/** The living Sales Xray mark and wordmark, for callers that own the wrapper. */
export function BrandMark({ markOnly = false }: { markOnly?: boolean }) {
  const id = `sx-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const bars = MARK_BARS.map((bar, index) => (
    <rect
      key={bar.x}
      className={styles.bar}
      style={{ "--i": index } as CSSProperties}
      x={bar.x}
      y={32 - bar.height / 2}
      width="4"
      height={bar.height}
      rx="2"
    />
  ));
  return (
    <>
      <span className={styles.symbol} aria-hidden="true">
        <svg viewBox="0 0 64 64" focusable="false">
          <defs>
            <linearGradient id={`${id}-reveal`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" className={styles.revealStart} />
              <stop offset="100%" className={styles.revealEnd} />
            </linearGradient>
            <clipPath id={`${id}-lens`}>
              <circle className={styles.lensTravel} cx="32" cy="32" r="12" />
            </clipPath>
          </defs>
          <g className={styles.trace}>{bars}</g>
          <g
            className={styles.revealed}
            clipPath={`url(#${id}-lens)`}
            fill={`url(#${id}-reveal)`}
          >
            {bars}
          </g>
          <g className={styles.lensTravel}>
            <circle className={styles.lensGlass} cx="32" cy="32" r="12" />
            <path className={styles.lensGlint} d="M24.5 26.5a9 9 0 0 1 6-5.6" />
          </g>
        </svg>
      </span>
      {!markOnly && (
        <span className={styles.wordmark} aria-hidden="true">
          <span className={styles.name}>Sales Xray</span>
          <span className={styles.by}>by Authority Closers</span>
        </span>
      )}
    </>
  );
}
