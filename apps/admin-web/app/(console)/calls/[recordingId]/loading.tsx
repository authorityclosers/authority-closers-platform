import { Skeleton } from "@/app/ui/kit";
import styles from "@/app/calls/review.module.css";

/** The call screen's shape while it loads: header, player, transcript, views. Nothing moves when it arrives. */
export default function CallLoading() {
  return (
    <div
      className={styles.screen}
      role="status"
      aria-busy="true"
      aria-label="Loading the call"
    >
      <div className={styles.head}>
        <div className={styles.headText}>
          <Skeleton width={60} height={12} />
          <Skeleton width={260} height={24} />
          <Skeleton width={420} height={14} />
        </div>
      </div>
      <div />
      <div className={styles.grid}>
        <div className={styles.left}>
          <div className={styles.player} style={{ height: 118 }} />
          <div
            className={styles.transcriptPanel}
            style={{
              display: "grid",
              gap: 14,
              padding: 14,
              alignContent: "start",
            }}
          >
            {Array.from({ length: 8 }, (_, index) => (
              <Skeleton
                key={index}
                height={34}
                width={`${96 - (index % 3) * 12}%`}
              />
            ))}
          </div>
        </div>
        <div className={styles.right}>
          <Skeleton height={36} />
          <div
            className={styles.view}
            style={{
              display: "grid",
              gap: 14,
              padding: 16,
              alignContent: "start",
            }}
          >
            {Array.from({ length: 6 }, (_, index) => (
              <Skeleton
                key={index}
                height={index % 2 ? 48 : 18}
                width={index % 2 ? "100%" : "40%"}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
