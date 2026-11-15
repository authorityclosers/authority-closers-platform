/**
 * The Leads screen's outline while it opens, light enough for the app's root
 * loading screen (design system v2, 20 Oct): only the kit, styles and the
 * shell, never the Lead Desk page or its API client.
 *
 * It is the page's own first screen in its real shapes (Leads part 05, 15 Nov
 * 2026: the old chip row and pill tabs drew here and moved when the page came):
 * the side switch, the work tabs, the stage chips with Filter, then the list's
 * card with its sort row and faithful rows. On a computer the page head and
 * tiles stand above, as they do once loaded.
 */

import { AcquisitionShell } from "../acquisition-shell";
import { Skeleton } from "../ui/kit";
import styles from "./leads.module.css";

/** A list row's outline (Leads part 05): the row's own 40 avatar, its name and
 *  two lines, and its two 44 circles 56 apart. */
export function LoadingRows({ count = 5 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, key) => (
        <div key={key} className={styles.listLoadingRow} aria-hidden="true">
          <Skeleton width={40} height={40} radius="circle" />
          <div className={styles.listLoadingText}>
            <Skeleton width={140} height={14} />
            <Skeleton width={120} height={11} />
            <Skeleton width={80} height={11} />
          </div>
          <span className={styles.listLoadingActions}>
            <Skeleton width={44} height={44} radius="circle" />
            <Skeleton width={44} height={44} radius="circle" />
          </span>
        </div>
      ))}
    </>
  );
}

export function LeadsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <div
        className={styles.root}
        data-tab="desk"
        aria-busy="true"
        aria-label="Loading leads"
      >
        <div className={styles.wideOnly}>
          <div className={styles.headSkeleton}>
            <Skeleton width={120} height={22} />
            <Skeleton width={260} height={12} />
          </div>
          <div className={styles.tilesSkeleton}>
            {[0, 1, 2, 3].map((key) => (
              <Skeleton key={key} height={86} />
            ))}
          </div>
        </div>
        <div className={styles.skeletonHead} aria-hidden="true">
          <Skeleton height={48} radius="pill" />
          <div className={styles.skeletonTabs}>
            <Skeleton width={72} height={14} />
            <Skeleton width={100} height={14} />
            <Skeleton width={92} height={14} />
          </div>
          <div className={styles.skeletonChips}>
            <Skeleton width={112} height={32} radius="pill" />
            <Skeleton width={96} height={32} radius="pill" />
            <Skeleton width={72} height={32} radius="pill" />
            <Skeleton width={40} height={40} radius="circle" />
          </div>
        </div>
        <div className={`${styles.listPanel} ${styles.skeletonCard}`}>
          <div className={styles.skeletonSort} aria-hidden="true">
            <Skeleton width={150} height={14} />
          </div>
          <LoadingRows />
        </div>
      </div>
    </AcquisitionShell>
  );
}
