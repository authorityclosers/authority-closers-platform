"use client";

import Link from "next/link";
import { useId, type CSSProperties } from "react";

import styles from "./brand-lockup.module.css";

export function BrandLockup({
  href,
  markOnly = false,
}: {
  href: string;
  markOnly?: boolean;
}) {
  const id = `sx-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <Link
      className={`${styles.brand}${markOnly ? ` ${styles.markOnly}` : ""}`}
      href={href}
      aria-label="Sales Xray home"
    >
      <svg
        className={styles.symbol}
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient id={`${id}-bars`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" className={styles.barStart} />
            <stop offset="100%" className={styles.barEnd} />
          </linearGradient>
          <linearGradient id={`${id}-scan`} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" className={styles.scanEdge} />
            <stop offset="50%" className={styles.scanCore} />
            <stop offset="100%" className={styles.scanEdge} />
          </linearGradient>
          <clipPath id={`${id}-clip`}>
            <rect x="2" y="8" width="4.5" height="16" rx="2.25" />
            <rect x="9.5" y="3" width="4.5" height="26" rx="2.25" />
            <rect x="17" y="6" width="4.5" height="20" rx="2.25" />
            <rect x="24.5" y="4" width="4.5" height="24" rx="2.25" />
          </clipPath>
        </defs>
        <g fill={`url(#${id}-bars)`}>
          <rect
            className={styles.bar}
            style={{ "--i": 0 } as CSSProperties}
            x="2"
            y="8"
            width="4.5"
            height="16"
            rx="2.25"
          />
          <rect
            className={styles.bar}
            style={{ "--i": 1 } as CSSProperties}
            x="9.5"
            y="3"
            width="4.5"
            height="26"
            rx="2.25"
          />
          <rect
            className={styles.bar}
            style={{ "--i": 2 } as CSSProperties}
            x="17"
            y="6"
            width="4.5"
            height="20"
            rx="2.25"
          />
          <rect
            className={styles.bar}
            style={{ "--i": 3 } as CSSProperties}
            x="24.5"
            y="4"
            width="4.5"
            height="24"
            rx="2.25"
          />
        </g>
        {/* An X-ray scan light passing over the waveform. */}
        <g clipPath={`url(#${id}-clip)`}>
          <rect
            className={styles.scan}
            x="-10"
            y="0"
            width="10"
            height="32"
            fill={`url(#${id}-scan)`}
          />
        </g>
      </svg>
      {!markOnly && (
        <span className={styles.wordmark} aria-hidden="true">
          <span className={styles.name}>Sales Xray</span>
          <span className={styles.by}>by Authority Closers</span>
        </span>
      )}
    </Link>
  );
}
