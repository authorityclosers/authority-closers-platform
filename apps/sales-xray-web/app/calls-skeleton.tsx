"use client";

import type { CSSProperties } from "react";

import styles from "./calls-library.module.css";

/** The loaded strip's labels, with a placeholder as long as its usual line. */
const FIGURES = [
  ["Calls", "8em"],
  ["Reports ready", "9em"],
  ["Call time", "8em"],
  ["Next step agreed", "10em"],
] as const;

/** The loaded page's own blocks in loading mode, so nothing moves. */
export function CallsBodySkeleton({
  workspace = true,
}: {
  workspace?: boolean;
}) {
  return (
    <div
      className={styles.skeleton}
      role="status"
      aria-busy="true"
      aria-label="Loading your calls"
    >
      {workspace ? (
        <dl className={styles.strip}>
          {FIGURES.map(([label, width]) => (
            <div className={styles.kpi} key={label}>
              <dt>{label}</dt>
              <dd>
                <i className={styles.phValue} />
              </dd>
              <dd className={styles.kpiContext}>
                <i
                  className={styles.phText}
                  style={{ "--w": width } as CSSProperties}
                />
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {/* The list's own frame (toolbar and table 10 px apart) and the
          toolbar's own boxes (search, chips, sort; on phones also Select),
          so its one or two rows keep their height. */}
      <div className={styles.list}>
        <div className={styles.toolbar}>
          <span className={`${styles.search} ${styles.phControl}`} />
          <span className={styles.filters}>
            {[0, 1, 2].map((chip) => (
              <i key={chip} className={styles.phChip} />
            ))}
          </span>
          <span className={`${styles.sort} ${styles.phControl}`} />
          <span
            className={`${styles.tool} ${styles.selectToggle} ${styles.phControl}`}
          />
        </div>
        <div className={styles.table}>
          <div className={styles.head} aria-hidden="true" />
          {Array.from({ length: 8 }, (_, row) => (
            <div className={styles.skeletonRow} key={row}>
              <i data-w="title" />
              <i data-w="meta" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Route-level loading: the header plus the same skeleton blocks. */
export function CallsSkeleton() {
  return (
    // The standalone page's frame: its h1 is for screen readers only (the
    // shell's bar says "Calls"), so the loading outline must not show one.
    <div
      className={styles.page}
      data-variant="standalone"
      data-workspace="true"
    >
      <header className={styles.header}>
        <div className={styles.headerCopy}>
          <h1>Calls</h1>
          <p>Private to your account and workspace</p>
        </div>
      </header>
      <CallsBodySkeleton />
    </div>
  );
}
