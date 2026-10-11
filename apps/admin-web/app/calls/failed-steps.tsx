/**
 * One call's failed analysis steps, with the existing admin job retry for the
 * ones that never reached a provider. Codes only: failure text never shows.
 * Re-running a finished call is a different, unbuilt command (see Re-run).
 */
import { Badge } from "../ui/kit";
import { STAGE_LABEL, type FailedJob } from "../health/health-data";
import { RetryJob } from "../health/retry-job";
import { when } from "./call-data";
import styles from "./review.module.css";

export function FailedSteps({ jobs }: { jobs: FailedJob[] }) {
  if (!jobs.length) return null;
  return (
    <ul className={styles.runs} aria-label="Failed steps">
      {jobs.map((job) => (
        <li key={job.jobId}>
          <span className={styles.runHead}>
            <strong>{STAGE_LABEL[job.stage] ?? job.stage}</strong>
            <Badge tone="bad">Failed</Badge>
            <code className={styles.runMeta}>{job.code}</code>
          </span>
          <span className={styles.runMeta}>
            {[
              `${job.attempts} ${job.attempts === 1 ? "attempt" : "attempts"}`,
              job.failedAt ? `failed ${when(job.failedAt)}` : null,
              job.retryable ? null : "reached a provider, so not retried here",
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {job.retryable ? (
            <span className={styles.runActions}>
              <RetryJob jobId={job.jobId} retryable />
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
