import { Skeleton } from "../ui/kit";
import styles from "./coaching.module.css";

/**
 * Coaching's own loading outline (focus, pillars and the mission rail), in a
 * light module the app shell can import without pulling in the page.
 */
export function CoachingSkeleton() {
  return (
    <div
      className={styles.skeleton}
      role="status"
      aria-busy="true"
      aria-label="Loading Coaching"
    >
      <Skeleton width={220} height={24} />
      <Skeleton width={320} height={13} />
      <div className={styles.layout}>
        <div className={styles.main}>
          <span className={styles.skeletonBlock} style={{ height: 232 }} />
          <span className={styles.skeletonBlock} style={{ height: 200 }} />
          <span className={styles.skeletonBlock} style={{ height: 280 }} />
        </div>
        <div className={styles.rail}>
          <span className={styles.skeletonBlock} style={{ height: 300 }} />
          <span className={styles.skeletonBlock} style={{ height: 160 }} />
        </div>
      </div>
    </div>
  );
}
