"use client";

/**
 * Review 2.0's coaching review on the call page's Coaching tab (owner 19 Oct:
 * "coaching review is separate"): this run's coaching as points, each judged in
 * coaching terms (true for this call, how useful for this rep, what it should
 * say), apart from how the report lays coaching out.
 */
import { useState } from "react";

import {
  myAnswers,
  othersOn,
  withSaved,
  type CoachingPoint,
  type ReviewCall,
} from "./review-verdicts-data";
import { VerdictChips } from "./verdict-chips";
import styles from "./analysis-tab.module.css";

export function CoachingReview({
  recordingId,
  review,
  points,
}: {
  recordingId: string;
  review: ReviewCall;
  points: readonly CoachingPoint[];
}) {
  const pipeline =
    review.pipelines.find((item) => item.targets.includes("coaching")) ?? null;
  const [verdicts, setVerdicts] = useState(review.verdicts);
  if (!pipeline || !points.length) return null;
  return (
    <section className={styles.tab} aria-label="Coaching review">
      <p className={styles.summary}>
        <strong>Coaching review</strong>
        <span>
          {points.length} points · judged as coaching, apart from the report
          layout
        </span>
      </p>
      <section className={styles.group}>
        <ul>
          {points.map((point) => (
            <li key={point.ref}>
              <span className={styles.label}>{point.title}</span>
              <span className={styles.value}>{point.text}</span>
              <span className={styles.meta} />
              <VerdictChips
                recordingId={recordingId}
                pipeline={pipeline}
                targetKind="coaching"
                targetRef={point.ref}
                mine={myAnswers(verdicts, point.ref)}
                others={othersOn(verdicts, point.ref)}
                onSaved={(saved) =>
                  setVerdicts((current) => withSaved(current, saved))
                }
              />
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}
