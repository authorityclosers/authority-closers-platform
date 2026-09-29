"use client";

import { LayoutGrid, RotateCw } from "lucide-react";
import Link from "next/link";

import styles from "./error-page.module.css";

/** A screen that failed to render: calm words, a retry, a way home. */
export default function ScreenError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className={styles.wrap}>
      <section className={styles.card} role="alert">
        <svg
          className={styles.art}
          viewBox="0 0 64 64"
          aria-hidden="true"
          focusable="false"
        >
          <circle cx="32" cy="32" r="28" className={styles.ring} />
          <path d="M20 36c4-6 8-6 12 0s8 6 12 0" className={styles.wave} />
        </svg>
        <h1>This screen hit a snag</h1>
        <p>
          Your calls and reports are safe. Try again, or head back to your
          dashboard.
        </p>
        <div className={styles.actions}>
          <button type="button" className={styles.primary} onClick={reset}>
            <RotateCw size={15} aria-hidden="true" />
            Try again
          </button>
          <Link className={styles.secondary} href="/dashboard">
            <LayoutGrid size={15} aria-hidden="true" />
            Dashboard
          </Link>
        </div>
        {error.digest ? (
          <p className={styles.ref}>Reference {error.digest}</p>
        ) : null}
      </section>
    </div>
  );
}
