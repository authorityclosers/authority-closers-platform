"use client";

import Link from "next/link";

import styles from "./brand-lockup.module.css";

export function BrandLockup({ href }: { href: string }) {
  return (
    <Link className={styles.brand} href={href} aria-label="Sales Xray home">
      <svg
        className={styles.symbol}
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <rect
          x="2"
          y="8"
          width="4.5"
          height="16"
          rx="2.25"
          fill="var(--lx-teal)"
        />
        <rect
          x="9.5"
          y="3"
          width="4.5"
          height="26"
          rx="2.25"
          fill="var(--lx-teal)"
        />
        <rect
          x="17"
          y="6"
          width="4.5"
          height="20"
          rx="2.25"
          fill="var(--lx-teal)"
        />
        <rect
          x="24.5"
          y="4"
          width="4.5"
          height="24"
          rx="2.25"
          fill="var(--lx-teal)"
        />
      </svg>
      <span className={styles.wordmark} aria-hidden="true">
        <span className={styles.name}>Sales Xray</span>
        <span className={styles.by}>by Authority Closers</span>
      </span>
    </Link>
  );
}
