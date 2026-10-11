import { Skeleton } from "../../ui/kit";
import styles from "./person.module.css";

/*
 * The profile's loading outline, in a light module the app shell's session
 * check can draw without pulling in the page.
 */

export function ActivitySkeleton() {
  return (
    <div className={styles.skeleton} aria-hidden="true">
      <div className={styles.skeletonTiles}>
        {[0, 1, 2, 3].map((index) => (
          <span key={index} className={styles.skeletonBlock} data-h="tile" />
        ))}
      </div>
      <div className={styles.grid}>
        {[0, 1].map((index) => (
          <span key={index} className={styles.skeletonBlock} data-h="chart" />
        ))}
      </div>
    </div>
  );
}

/** The profile's outline while it loads: header, tiles and two charts. */
export function PersonSkeleton() {
  return (
    <div role="status" aria-busy="true" aria-label="Loading this person">
      <div className={styles.header}>
        <Skeleton width={48} height={48} />
        <div className={styles.who}>
          <Skeleton width={200} height={24} />
          <Skeleton width={280} height={13} />
        </div>
      </div>
      <ActivitySkeleton />
    </div>
  );
}
