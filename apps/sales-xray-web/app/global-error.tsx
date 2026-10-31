"use client";

import { RotateCw } from "lucide-react";

import "./styles.css";
import styles from "./error-page.module.css";

/**
 * When the app can't render at all (the connection lost mid-move, a crash in
 * the root layout), Next shows this in place of the whole document. It is a
 * proper page: a title and its language (the test robot, 31 Oct 2026: axe
 * found Next's bare error document with neither), calm words and a retry.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" data-lx-root="" data-theme="light">
      <body>
        <title>Sales X-Ray · Authority Closers</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <main className={styles.wrap}>
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
            <h1>This screen didn’t load</h1>
            <p>
              Your calls and reports are safe. Check your connection, then try
              again.
            </p>
            <div className={styles.actions}>
              <button type="button" className={styles.primary} onClick={reset}>
                <RotateCw size={15} aria-hidden="true" />
                Try again
              </button>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => window.location.reload()}
              >
                Reload
              </button>
            </div>
            {error.digest ? (
              <p className={styles.ref}>Reference {error.digest}</p>
            ) : null}
          </section>
        </main>
      </body>
    </html>
  );
}
