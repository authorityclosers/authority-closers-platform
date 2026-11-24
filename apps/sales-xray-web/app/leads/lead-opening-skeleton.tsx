/**
 * The lead page's outline while a lead opens (v1.96 device polish, lane P:
 * on slow 3G a returning seller saw a bare "Opening the lead…" for 7 s). The
 * page's own shapes, so nothing moves when the lead arrives: the head card
 * (avatar, name, two lines, the stage and its steps), the four round actions,
 * then "Before you call" with its rows. The words stay for screen readers.
 */
import { Skeleton } from "../ui/kit";
import styles from "./lead-opening-skeleton.module.css";

export function LeadOpeningSkeleton() {
  return (
    <div
      className={styles.root}
      aria-busy="true"
      aria-label="Opening the lead"
      data-lead-opening=""
    >
      <span className={styles.readerOnly}>Opening the lead…</span>
      <div className={styles.card} aria-hidden="true">
        <div className={styles.head}>
          <Skeleton width={56} height={56} radius="circle" />
          <div className={styles.lines}>
            <Skeleton width="62%" height={22} />
            <Skeleton width="78%" height={13} />
            <Skeleton width="48%" height={13} />
          </div>
        </div>
        <div className={styles.stage}>
          <Skeleton width={128} height={14} />
          <Skeleton width={72} height={14} />
        </div>
        <div className={styles.steps}>
          {[0, 1, 2, 3].map((key) => (
            <span key={key} className={styles.step}>
              <Skeleton width={18} height={18} radius="circle" />
              <Skeleton width={52} height={11} />
            </span>
          ))}
        </div>
      </div>
      <div className={styles.actions} aria-hidden="true">
        {[0, 1, 2, 3].map((key) => (
          <span key={key} className={styles.action}>
            <Skeleton width={48} height={48} radius="circle" />
            <Skeleton width={54} height={11} />
          </span>
        ))}
      </div>
      <div className={styles.card} aria-hidden="true">
        <Skeleton width={132} height={16} />
        {[0, 1, 2, 3].map((key) => (
          <span key={key} className={styles.row}>
            <Skeleton width={76} height={13} />
            <Skeleton width={104} height={13} />
          </span>
        ))}
      </div>
    </div>
  );
}
