"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AudioLines, Check, FileCheck2, ShieldCheck } from "lucide-react";
import type { Progress } from "./acquisition-client";
import { ProcessingStatusCopy } from "./processing-status-copy";
import { projectProcessing, stageLabels, stageNames } from "./processing-state";
import styles from "./processing-experience.module.css";

export function ProcessingExperience({
  submissionId,
  progress,
  waitingForApproval,
  accepted,
  refreshProblem,
  children,
}: {
  submissionId: string;
  progress: Progress | null;
  waitingForApproval: boolean;
  accepted: boolean;
  refreshProblem: boolean;
  children: ReactNode;
}) {
  const view = projectProcessing(progress, waitingForApproval);
  const [hidden, setHidden] = useState(false);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const sync = () => {
      setHidden(document.visibilityState === "hidden");
      setOffline(!navigator.onLine);
    };
    sync();
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      document.removeEventListener("visibilitychange", sync);
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);
  const connectionProblem = refreshProblem || offline;
  const guidance =
    accepted || progress?.automatic_progression
      ? "Analysis can continue after you leave. Keep this call’s link to return in this browser while your session and call remain available."
      : waitingForApproval
        ? "Start analysis here, or return to this call from Calls."
        : "Your recording is saved. We’re confirming that analysis has started.";
  return (
    <section
      className={styles.panel}
      aria-label="Analysis progress"
      data-paused={view.attention}
      data-motion-suspended={hidden || view.attention || connectionProblem}
    >
      <div className={styles.heading}>
        <span
          className={styles.signal}
          aria-hidden="true"
          data-phase={view.current?.stage ?? "processing"}
          data-paused={view.attention}
        >
          <AudioLines size={32} />
        </span>
        <div role="status" aria-live="polite" aria-atomic="true">
          <ProcessingStatusCopy
            submissionId={submissionId}
            progress={progress}
            title={view.title}
            paused={view.paused}
            needsAttention={view.attention}
            refreshProblem={connectionProblem}
            waitingForApproval={waitingForApproval}
          />
        </div>
      </div>
      {connectionProblem && (
        <p className={styles.connection} role="status">
          {offline
            ? "Your browser is offline."
            : "Status cannot currently be refreshed."}{" "}
          The stage trail shows the last confirmed information.
        </p>
      )}
      <div className={styles.body}>
        <ol className={styles.trail} aria-label="Processing stages">
          <li data-state={progress?.local_state ?? "pending"}>
            <span className={styles.marker} aria-hidden="true">
              {progress?.local_state === "completed" ? (
                <Check size={16} />
              ) : (
                <FileCheck2 size={16} />
              )}
            </span>
            <div>
              <strong>Recording</strong>
              <small>
                {progress?.local_state === "completed"
                  ? "Checked and saved"
                  : view.attention
                    ? "Received · needs attention"
                    : "Received · checking"}
              </small>
            </div>
          </li>
          {view.rows.map((row) => (
            <li
              key={row.stage}
              data-stage={row.stage}
              data-state={row.state ?? "not-started"}
              aria-current={
                row.stage === view.current?.stage ? "step" : undefined
              }
              aria-label={`${stageNames[row.stage]}: ${row.label}`}
            >
              <span className={styles.marker} aria-hidden="true">
                {row.state === "completed" ? <Check size={16} /> : <span />}
              </span>
              <div>
                <strong>{stageLabels[row.stage]}</strong>
                <small>{row.label}</small>
              </div>
            </li>
          ))}
        </ol>
        <div className={styles.context}>
          <aside className={styles.saved} aria-label="Saved work">
            <ShieldCheck size={22} aria-hidden="true" />
            <div>
              <h4>Your saved work</h4>
              <p>
                {view.savedTranscript && !view.attention
                  ? "Your recording and transcript are saved. No need to upload again."
                  : "Your recording is saved. There’s no need to upload it again."}
              </p>
              {view.savedTranscript && view.attention ? (
                <p>The completed transcript stays attached to this call.</p>
              ) : (
                view.attention && (
                  <p>A completed transcript has not been confirmed yet.</p>
                )
              )}
              {view.savedEvidence && (
                <p>Some conversation analysis is saved with this call.</p>
              )}
            </div>
          </aside>
          <details className={styles.next}>
            <summary>What happens next?</summary>
            <p>
              Sales Xray checks the transcript for evidence, then brings the
              supported observations into a coaching report. The report opens
              after its saved result and source moments are verified.
            </p>
            <p>
              Stages can take different amounts of time. This trail is not a
              percentage or a time estimate.
            </p>
            <p>
              Guest access depends on this browser session. Calls saved to an
              account can also be reopened by signing in to that owning account.
            </p>
          </details>
        </div>
      </div>
      <footer className={styles.footer}>
        <p>
          {view.attention
            ? "Completed work remains saved. Review the available recovery action before continuing."
            : guidance}
        </p>
        <div className={styles.actions}>{children}</div>
      </footer>
    </section>
  );
}
