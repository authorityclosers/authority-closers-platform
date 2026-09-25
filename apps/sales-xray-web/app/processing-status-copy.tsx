"use client";

import { useEffect, useState } from "react";
import type { Progress } from "./acquisition-client";
import styles from "./processing-experience.module.css";
import { projectProcessing } from "./processing-state";

// Foreground observation only, never a provider timeout or predicted finish.
const UPDATE_WAIT_MS = 60_000;

function ObservedStatus({
  title,
  description,
  suspended,
}: {
  title: string;
  description: string;
  suspended: boolean;
}) {
  const [delayed, setDelayed] = useState(false);
  useEffect(() => {
    let remaining = UPDATE_WAIT_MS;
    let started: number | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const sync = () => {
      clearTimeout(timer);
      if (started !== null)
        remaining = Math.max(0, remaining - (performance.now() - started));
      started = null;
      if (!suspended && document.visibilityState !== "hidden") {
        started = performance.now();
        timer = setTimeout(() => setDelayed(true), remaining);
      }
    };
    sync();
    document.addEventListener("visibilitychange", sync);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [suspended]);
  return (
    <div className={styles.copy} data-update-delayed={delayed}>
      <p className={styles.kicker}>LAST CONFIRMED STATUS</p>
      <h3>{title}</h3>
      <p>{description}</p>
      {delayed && !suspended && (
        <p className={styles.waitNotice}>
          No new stage update yet. This does not tell us how much work remains.
        </p>
      )}
    </div>
  );
}

export function ProcessingStatusCopy({
  submissionId,
  progress,
  title,
  paused,
  needsAttention,
  refreshProblem = false,
  waitingForApproval = false,
}: {
  submissionId: string;
  progress: Progress | null;
  title: string;
  paused: boolean;
  needsAttention: boolean;
  refreshProblem?: boolean;
  waitingForApproval?: boolean;
}) {
  const projection = projectProcessing(progress, waitingForApproval);
  const current =
    projection.current?.state === "running" ? projection.current.stage : null;
  const description = progress?.has_report
    ? "Checking the saved report and its source moments before opening it."
    : needsAttention
      ? "This stage needs checking before analysis can continue."
      : waitingForApproval
        ? "Your recording is saved. Start analysis to generate your report."
        : projection.unknown
          ? "The latest status needs checking. No completion has been inferred."
          : progress?.local_state !== "completed"
            ? "Checking the recording’s format and duration before analysis starts."
            : current === "C2"
              ? "Turning your recording into a transcript."
              : current === "C4"
                ? "This step links conversation observations to source moments."
                : current === "C5"
                  ? "Bringing your takeaways and next-call plan together."
                  : "Each step updates when its status is confirmed.";
  if (needsAttention)
    return (
      <div className={styles.copy}>
        <p className={styles.kicker}>
          {paused ? "SAVED WORK · PAUSED" : "STATUS NEEDS ATTENTION"}
        </p>
        <h3>{paused ? "Analysis paused" : "Your call needs attention"}</h3>
        <p>{description}</p>
      </div>
    );
  return (
    <ObservedStatus
      key={JSON.stringify([submissionId, progress])}
      title={title}
      description={description}
      suspended={
        refreshProblem || waitingForApproval || Boolean(progress?.has_report)
      }
    />
  );
}
