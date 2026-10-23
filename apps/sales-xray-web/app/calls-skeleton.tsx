"use client";

import { Skeleton } from "./ui/kit";
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
              {/* The number's own line (its <b>), so the tile keeps the
                  loaded height and the name stays beside it. */}
              <dd>
                <b className={styles.phValue}>
                  <Skeleton width={48} height={16} />
                </b>
              </dd>
              <dd className={styles.kpiContext}>
                <Skeleton width={width} height={10} />
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
              <Skeleton key={chip} width={72} radius="pill" />
            ))}
          </span>
          <span className={`${styles.sort} ${styles.phControl}`} />
          <span
            className={`${styles.tool} ${styles.selectToggle} ${styles.phControl}`}
          >
            {/* The word keeps the button's own width; the outline hides it. */}
            <span className={styles.phWord}>Select</span>
          </span>
        </div>
        <div className={styles.table}>
          <div className={styles.head} aria-hidden="true" />
          {/* The first day's heading (Today), as the loaded list opens. */}
          <div className={styles.group} aria-hidden="true">
            <Skeleton width={44} height={10} />
          </div>
          {Array.from({ length: 8 }, (_, row) => (
            <div className={styles.skeletonRow} key={row}>
              <Skeleton width="min(360px, 60%)" height={12} />
              <Skeleton width="min(220px, 40%)" height={10} />
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
