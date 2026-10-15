import { Skeleton } from "../ui/kit";
import styles from "./coaching.module.css";

/**
 * Coaching's own loading outline (the first numbered pillars in one column),
 * in a light module the app shell can import without pulling in the page.
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
      <div className={styles.conversation}>
        {[260, 220, 300].map((height) => (
          <div key={height} className={styles.pillar}>
            <Skeleton width={260} height={22} />
            <span className={styles.skeletonBlock} style={{ height }} />
          </div>
        ))}
      </div>
    </div>
  );
}
