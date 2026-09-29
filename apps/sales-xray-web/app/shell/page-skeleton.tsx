"use client";

import styles from "./page-skeleton.module.css";

export type SkeletonVariant = "dashboard" | "list" | "account" | "studio";

/**
 * Instant content-area placeholder shown while the shell is mounted but page
 * data is still loading. Uses design tokens so it matches the real layout.
 */
export function PageSkeleton({ variant }: { variant: SkeletonVariant }) {
  if (variant === "dashboard") {
    return (
      <div className={styles.dashboard}>
        {/* 4 KPI cards */}
        <div className={styles.kpiRow}>
          <div className={styles.kpiCard} />
          <div className={styles.kpiCard} />
          <div className={styles.kpiCard} />
          <div className={styles.kpiCard} />
        </div>
        {/* 2/3 chart + 1/3 status */}
        <div className={styles.analyticsRow}>
          <div className={styles.chartBlock} />
          <div className={styles.chartBlock} />
        </div>
        {/* Recent calls rows */}
        <div className={styles.tableRows}>
          {Array.from({ length: 5 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: skeleton
            <div key={i} className={styles.tableRow} />
          ))}
        </div>
      </div>
    );
  }

  if (variant === "list") {
    return (
      <div className={styles.list}>
        {Array.from({ length: 8 }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: skeleton
          <div key={i} className={styles.listRow} />
        ))}
      </div>
    );
  }

  if (variant === "account") {
    return (
      <div className={styles.account}>
        <div className={styles.accountHeader} />
        <div className={styles.accountCard} />
        <div className={styles.accountCard} />
      </div>
    );
  }

  // studio
  return (
    <div className={styles.studio}>
      <div className={styles.uploadPanel} />
    </div>
  );
}
