"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AudioLines, Check, FileAudio2, FileText, ShieldCheck } from "lucide-react";
import type { Progress } from "./acquisition-client";
import { ProcessingStatusCopy } from "./processing-status-copy";
import { projectProcessing, stageNames, type ProcessingStage } from "./processing-state";
import styles from "./acquisition-processing-panel.module.css";

export type AcquisitionProcessingStageRow = {
  stage: ProcessingStage;
  state: string | null;
  label?: string;
};

type Props = {
  /** Pass projectProcessing(progress, waitingForApproval).rows; never advance these from a timer. */
  stageRows: readonly AcquisitionProcessingStageRow[];
  /** A server-backed status title, such as projectProcessing(...).title. */
  statusText: string;
  fileName?: string;
  fileMeta?: string;
  allowanceLabel?: string;
  paused?: boolean;
  submissionId?: string;
  progress?: Progress | null;
  waitingForApproval?: boolean;
  accepted?: boolean;
  refreshProblem?: boolean;
  children?: ReactNode;
};

const stages = [
  {
    id: "C2",
    title: "Listening",
    description: "Transcribing and separating speakers",
    Icon: FileAudio2,
  },
  {
    id: "C4",
    title: "Understanding",
    description: "Identifying key moments, objections and themes",
    Icon: AudioLines,
  },
  {
    id: "C5",
    title: "Preparing your report",
    description: "Turning saved findings into a clear summary",
    Icon: FileText,
  },
] as const;

const waveHeights = [23, 35, 51, 77, 38, 62, 96, 34, 58, 85, 47, 69, 31, 53, 22];

function visualState(state: string | null, paused: boolean) {
  if (state === "completed") return "completed";
  if (state === "saved") return "saved";
  if (state === "running" && !paused) return "active";
  if (["held", "failed", "cancelled", "uncertain"].includes(state ?? "") || paused && state === "running") return "attention";
  return "waiting";
}

export function AcquisitionProcessingPanel({
  stageRows,
  statusText,
  fileName,
  fileMeta,
  allowanceLabel,
  paused = false,
  submissionId,
  progress,
  waitingForApproval = false,
  accepted = false,
  refreshProblem = false,
  children,
}: Props) {
  const projection = projectProcessing(progress ?? null, waitingForApproval);
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
  const rows = stages.map((stage) => {
    const actual = stageRows.find((row) => row.stage === stage.id);
    return { ...stage, state: actual?.state ?? null, label: actual?.label };
  });
  const active = !paused && rows.some((row) => row.state === "running");
  const queued = rows.some((row) => row.state === "queued" || row.state === "pending");
  const needsAttention = paused || rows.some((row) => ["held", "failed", "cancelled", "uncertain"].includes(row.state ?? ""));
  const connectionProblem = refreshProblem || offline;
  const motionSuspended = hidden || needsAttention || connectionProblem;
  const currentStage = projection.current?.stage ?? rows.find((row) => row.state === "running")?.id ?? "processing";
  const guidance = accepted || progress?.automatic_progression
    ? "Analysis can continue after you leave. Keep this call’s link to return in this browser while your session and call remain available."
    : "Keep this tab open to finish starting analysis. Your upload is saved; analysis approval is not confirmed yet.";
  const fileStatus = needsAttention ? "Needs attention" : active ? "Processing" : queued ? "Queued" : "Checking status";

  return (
    <section className={styles.panel} aria-label="Analysis progress" data-paused={needsAttention} data-motion-suspended={motionSuspended} data-animated={active && !motionSuspended}>
      <div className={styles.heading}>
        <span className={styles.headingSignal} data-phase={currentStage} data-paused={needsAttention} aria-hidden="true">
          <AudioLines className={styles.headingWave} size={33} strokeWidth={1.85} />
        </span>
        <h2 id="acquisition-processing-title">Processing your call</h2>
        {allowanceLabel && (
          <span className={styles.allowance}><ShieldCheck size={19} strokeWidth={1.8} aria-hidden="true" />{allowanceLabel}</span>
        )}
      </div>

      <div className={styles.journey}>
        <ol className={styles.stageList} aria-label="Processing stages">
          {rows.map((row) => {
            const state = visualState(row.state, needsAttention);
            const Icon = row.Icon;
            return (
              <li
                className={styles.stage}
                key={row.id}
                data-stage={row.id}
                data-state={row.state ?? "not-started"}
                data-visual-state={state}
                aria-current={state === "active" ? "step" : undefined}
                aria-label={`${stageNames[row.id]}: ${row.label ?? (row.state === null ? "Not started" : row.state)}`}
              >
                <span className={styles.stageIcon} aria-hidden="true">
                  {state === "completed" ? <Check size={24} strokeWidth={2.8} /> : <Icon size={27} strokeWidth={1.9} />}
                </span>
                <strong>{row.title}</strong>
                <span className={styles.stageDescription}>{row.description}</span>
                <small className={styles.stageStatus}>{row.label ?? (row.state === null ? "Not started" : row.state)}</small>
              </li>
            );
          })}
        </ol>

        <div className={styles.signalCard} data-animated={active && !motionSuspended}>
          <svg className={styles.waveform} viewBox="0 0 352 112" fill="none" aria-hidden="true" focusable="false">
            <defs>
              <linearGradient id="processing-wave-gradient" x1="0" y1="0" x2="352" y2="0" gradientUnits="userSpaceOnUse">
                <stop stopColor="#A7EEE1" />
                <stop offset="0.54" stopColor="#3BC5B2" />
                <stop offset="1" stopColor="#028E8D" />
              </linearGradient>
            </defs>
            {waveHeights.map((height, index) => (
              <rect
                key={index}
                className={styles.waveBar}
                x={8 + index * 22}
                y={(112 - height) / 2}
                width="7"
                height={height}
                rx="3.5"
                fill="url(#processing-wave-gradient)"
              />
            ))}
          </svg>
          <span className={styles.signalDivider} aria-hidden="true" />
          <div className={styles.signalCopy} role="status" aria-live="polite" aria-atomic="true">
            {submissionId ? (
              <ProcessingStatusCopy
                submissionId={submissionId}
                progress={progress ?? null}
                title={statusText}
                paused={projection.paused}
                needsAttention={needsAttention}
                refreshProblem={connectionProblem}
                waitingForApproval={waitingForApproval}
              />
            ) : (
              <div><h3>{statusText}</h3><p>The stages above reflect the latest confirmed update for this call.</p></div>
            )}
          </div>
        </div>
      </div>

      {connectionProblem && (
        <p className={styles.connection} role="status">
          {offline ? "Your browser is offline." : "Status cannot currently be refreshed."}{" "}
          The stage trail shows the last confirmed information.
        </p>
      )}

      <div className={styles.fileCard}>
        <div className={styles.fileHeading}>
          <FileText size={23} strokeWidth={1.9} aria-hidden="true" />
          <h3>Uploaded file</h3>
        </div>
        <div className={styles.fileRow}>
          <span className={styles.fileIcon} aria-hidden="true"><FileAudio2 size={24} strokeWidth={1.8} /></span>
          <span className={styles.fileCopy}>
            <strong title={fileName || undefined}>{fileName || "Your recording"}</strong>
            {fileMeta && <small>{fileMeta}</small>}
          </span>
          <span className={styles.fileStatus} data-state={needsAttention ? "attention" : active ? "active" : "waiting"}>
            <span aria-hidden="true" />{fileStatus}
          </span>
        </div>
        {!needsAttention && projection.savedEvidence && (
          <p className={styles.savedEvidence}>Some conversation analysis is saved with this call.</p>
        )}
        {needsAttention && (
          <aside className={styles.savedWork} aria-label="Saved work">
            <ShieldCheck size={17} aria-hidden="true" />
            <div>
              <strong>Your saved work</strong>
              <p>Your recording is saved. There’s no need to upload it again.</p>
              <p>{projection.savedTranscript
                ? "The completed transcript stays attached to this call."
                : "A completed transcript has not been confirmed yet."}</p>
              {projection.savedEvidence && <p>Some conversation analysis is saved with this call.</p>}
            </div>
          </aside>
        )}
      </div>
      <footer className={styles.footer}>
        <p>{needsAttention
          ? "Completed work remains saved. Review the available recovery action before continuing."
          : guidance}</p>
        <div className={styles.actions}>{children}</div>
      </footer>
    </section>
  );
}
