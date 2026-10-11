"use client";

import styles from "./calls-library.module.css";

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
        <div className={`${styles.strip} ${styles.skeletonStrip}`}>
          {[0, 1, 2, 3].map((tile) => (
            <div className={styles.kpi} key={tile}>
              <i data-w="label" />
              <i data-w="value" />
              <i data-w="context" />
            </div>
          ))}
        </div>
      ) : null}
      <div className={styles.skeletonToolbar}>
        <i data-w="search" />
        <i data-w="chips" />
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
  );
}

/** Route-level loading: the header plus the same skeleton blocks. */
export function CallsSkeleton() {
  return (
    <div className={styles.page} data-workspace="true">
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
