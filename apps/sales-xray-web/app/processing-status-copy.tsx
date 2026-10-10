"use client";

import { useEffect, useState } from "react";
import type { Progress } from "./acquisition-client";
import styles from "./processing-experience.module.css";
import { projectProcessing } from "./processing-state";
import { AnalysisRetryAction } from "./analysis-retry-status";

// Foreground observation only, never a provider timeout or predicted finish.
const UPDATE_WAIT_MS = 60_000;

const REPORT_FAILURE_COPY: Record<string, string> = {
  conversation_call_map_invalid:
    "The call overview needs a valid structured draft.",
  conversation_call_map_evidence_unresolved:
    "The call overview needs quotes from this transcript.",
  conversation_call_map_time_out_of_range:
    "The call overview needs times within this recording.",
  conversation_call_map_phase_order_invalid:
    "The call overview needs its stages in time order.",
  conversation_call_map_reference_unknown:
    "The call overview needs valid speaker and item references.",
  conversation_call_map_role_mismatch:
    "The call overview needs evidence from the correct speaker role.",
  conversation_call_map_qualification_invalid:
    "The call overview needs a complete qualification check.",
  conversation_call_map_word_cap_exceeded:
    "The call overview needs shorter text and quotes.",
  conversation_call_map_signal_kind_unknown:
    "The call overview needs supported signal categories.",
  conversation_call_map_money_invalid:
    "The call overview needs valid amounts and units.",
  conversation_report_speaker_label_leak:
    "The report needs clear coaching language without provider speaker labels.",
  conversation_ethics_unverifiable_claim_missing:
    "The report needs a cited ethics note for an unverifiable claim.",
  conversation_report_dimension_evidence_required:
    "The report needs source evidence for its dimension assessments.",
};

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
  if (progress?.run_state === "failed")
    return (
      <div className={styles.copy}>
        <p className={styles.kicker}>LAST CONFIRMED STATUS</p>
        <h3>Analysis failed</h3>
        <p>
          {progress.minute_state === "released"
            ? "Your minutes have been released. Your recording is saved."
            : "Your recording is saved. No new analysis has been started."}
        </p>
        {progress.retry_available && progress.recording_id && (
          <AnalysisRetryAction
            key={submissionId}
            submissionId={submissionId}
            recordingId={progress.recording_id}
          />
        )}
      </div>
    );
  const projection = projectProcessing(progress, waitingForApproval);
  const current =
    projection.current?.state === "running" ? projection.current.stage : null;
  const description = progress?.has_report
    ? "Checking the saved report and its source moments before opening it."
    : progress?.run_state === "retrying"
      ? "Retrying your saved call within its accepted analysis plan."
      : progress?.run_state === "queued"
        ? "Your saved call is waiting for the next confirmed step."
        : needsAttention && !progress?.run_state
          ? (REPORT_FAILURE_COPY[progress?.failure_code ?? ""] ??
            "This stage needs checking before analysis can continue.")
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
  if (needsAttention && !progress?.run_state)
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
      title={
        progress?.run_state
          ? {
              queued: "Queued",
              working: "Working",
              retrying: "Retrying",
              failed: "Analysis failed",
              done: "Done",
            }[progress.run_state]
          : title
      }
      description={description}
      suspended={
        refreshProblem || waitingForApproval || Boolean(progress?.has_report)
      }
    />
  );
}
