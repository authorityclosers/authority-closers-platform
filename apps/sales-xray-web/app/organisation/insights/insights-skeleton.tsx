"use client";

import { Kpi, PageHeader, Panel, Skeleton, Tiles } from "../../ui/kit";
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
        <Skeleton width={300} height={32} />
        <Skeleton width={140} height={32} />
        <Skeleton width={140} height={32} />
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
      <Tiles label="Loading">
        {[0, 1, 2, 3].map((index) => (
          <Kpi
            key={index}
            label=""
            value={<Skeleton width={72} height={24} />}
            note={<Skeleton width={120} />}
          />
        ))}
      </Tiles>
      <Panel title="Calls over time" className={styles.wide}>
        <div className={styles.inset}>
          <Skeleton height={190} />
        </div>
      </Panel>
      <div className={styles.grid}>
        <Panel title="How calls ended">
          <div className={styles.inset}>
            <Skeleton height={220} />
          </div>
        </Panel>
        <Panel title="Skills across the calls">
          <div className={styles.inset}>
            <Skeleton height={220} />
          </div>
        </Panel>
      </div>
    </div>
  );
}
