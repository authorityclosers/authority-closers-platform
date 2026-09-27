"use client";

import Link from "next/link";
import { useId } from "react";

import styles from "./brand-lockup.module.css";

/** AC symbol and Sales ✕ray wordmark drawn with tokens, so both themes stay legible. */
export function BrandLockup({ href }: { href: string }) {
  const gradient = `lx-${useId().replace(/[^A-Za-z0-9_-]/g, "")}-beam`;
  return (
    <Link className={styles.brand} href={href} aria-label="Sales Xray home">
      <svg
        className={styles.symbol}
        viewBox="0 0 512 512"
        aria-hidden="true"
        focusable="false"
      >
        <polygon points="32,432 192,48 280,48 120,432" />
        <polygon points="308,112 440,432 144,432 184,328 296,328 260,224" />
      </svg>
      <span className={styles.wordmark} aria-hidden="true">
        <span className={styles.name}>
          Sales
          <svg className={styles.beam} viewBox="0 0 15 16" focusable="false">
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="var(--lx-teal)" />
                <stop offset="1" stopColor="var(--lx-teal-2)" />
              </linearGradient>
            </defs>
            <path
              d="M2 2l11 12M13 2L2 14"
              stroke={`url(#${gradient})`}
              strokeWidth="3.2"
              strokeLinecap="round"
            />
          </svg>
          ray
        </span>
        <span className={styles.by}>BY AUTHORITY CLOSERS</span>
      </span>
    </Link>
  );
}
