"use client";

import { RecentCallsSkeleton } from "./recent-calls";
import { DayBarsSkeleton, StatusSplitSkeleton } from "./dashboard-visuals";
import styles from "./dashboard.module.css";

/** The loaded dashboard's blocks in loading mode, so nothing moves on arrival. */
export function DashboardSkeleton() {
  return (
    <div
      className={styles.page}
      role="status"
      aria-busy="true"
      aria-label="Loading your dashboard"
    >
      <header className={styles.header}>
        <div>
          <i className={styles.skeletonValue} data-w="title" />
          <i className={styles.skeletonContext} />
        </div>
      </header>
      <div className={styles.strip}>
        {[0, 1, 2, 3].map((tile) => (
          <div className={styles.kpi} key={tile}>
            <i className={styles.skeletonContext} data-w="label" />
            <i className={styles.skeletonValue} />
            <i className={styles.skeletonContext} />
          </div>
        ))}
      </div>
      <div className={styles.columns}>
        <div className={styles.section}>
          <div className={styles.sectionHead} />
          <div className={styles.surface}>
            <DayBarsSkeleton />
          </div>
        </div>
        <div className={styles.section}>
          <div className={styles.sectionHead} />
          <div className={styles.surface}>
            <StatusSplitSkeleton />
          </div>
        </div>
      </div>
      <div className={styles.section}>
        <div className={styles.sectionHead} />
        <div className={styles.surface} data-flush="">
          <RecentCallsSkeleton />
        </div>
      </div>
    </div>
  );
}
