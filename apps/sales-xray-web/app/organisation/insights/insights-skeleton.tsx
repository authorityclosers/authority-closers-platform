"use client";

import { PageHeader, Skeleton } from "../../ui/kit";
import styles from "./insights.module.css";

/**
 * Insights' loading outline, so nothing moves when the page arrives. Its own file, so
 * the frame's route outlines don't load the whole screen (24 Oct 2026).
 */
export function InsightsSkeleton({
  failed = false,
  onRetry,
}: {
  failed?: boolean;
  onRetry?: () => void;
}) {
  return (
    <div className={styles.page} aria-busy={!failed}>
      <PageHeader
        title="Insights"
        context={[<Skeleton key="c" width={180} />]}
      />
      <div className={styles.filters}>
        <Skeleton width={300} height={44} />
        <Skeleton width={140} height={44} />
        <Skeleton width={140} height={44} />
      </div>
      {failed ? (
        <p className={styles.preparing} role="status">
          Insights couldn’t load.{" "}
          {onRetry ? (
            <button type="button" className={styles.linkish} onClick={onRetry}>
              Try again
            </button>
          ) : null}
        </p>
      ) : null}
      <Skeleton height={170} />
      <div className={styles.grid}>
        <Skeleton height={320} />
        <Skeleton height={320} />
      </div>
      <Skeleton height={430} />
    </div>
  );
}
