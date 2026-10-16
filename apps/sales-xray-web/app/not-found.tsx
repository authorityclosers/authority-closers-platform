"use client";

import { ArrowLeft, LayoutGrid } from "lucide-react";
import Link from "next/link";

import styles from "./error-page.module.css";

/**
 * An address that leads nowhere gets the app's own page with a way home,
 * never the framework's bare "404" (owner, 17 Oct: it looked broken inside
 * the phone app).
 */
export default function NotFound() {
  return (
    <div className={styles.wrap} data-not-found="">
      <section className={styles.card} aria-labelledby="not-found-title">
        <svg
          className={styles.art}
          viewBox="0 0 64 64"
          aria-hidden="true"
          focusable="false"
        >
          <circle cx="32" cy="32" r="28" className={styles.ring} />
          <path d="M20 36c4-6 8-6 12 0s8 6 12 0" className={styles.wave} />
        </svg>
        <h1 id="not-found-title">This page isn’t here</h1>
        <p>The link may be old or mistyped. Your calls and reports are safe.</p>
        <div className={styles.actions}>
          <Link className={styles.primary} href="/dashboard">
            <LayoutGrid size={15} aria-hidden="true" />
            Go to Home
          </Link>
          <button
            type="button"
            className={styles.secondary}
            onClick={() => window.history.back()}
          >
            <ArrowLeft size={15} aria-hidden="true" />
            Go back
          </button>
        </div>
      </section>
    </div>
  );
}
