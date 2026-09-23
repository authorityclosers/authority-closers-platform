import type { ReactNode } from "react";
import { AudioLines, Check, FileAudio2, FileText, ShieldCheck } from "lucide-react";
import type { ProcessingStage } from "./processing-state";
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
  children,
}: Props) {
  const rows = stages.map((stage) => {
    const actual = stageRows.find((row) => row.stage === stage.id);
    return { ...stage, state: actual?.state ?? null, label: actual?.label };
  });
  const active = !paused && rows.some((row) => row.state === "running");
  const queued = rows.some((row) => row.state === "queued" || row.state === "pending");
  const needsAttention = paused || rows.some((row) => ["held", "failed", "cancelled", "uncertain"].includes(row.state ?? ""));
  const fileStatus = needsAttention ? "Needs attention" : active ? "Processing" : queued ? "Queued" : "Checking status";

  return (
    <section className={styles.panel} aria-labelledby="acquisition-processing-title" data-paused={needsAttention} data-animated={active && !needsAttention}>
      <div className={styles.heading}>
        <AudioLines className={styles.headingWave} size={33} strokeWidth={1.85} aria-hidden="true" />
        <h2 id="acquisition-processing-title">Processing your call</h2>
        {allowanceLabel && (
          <span className={styles.allowance}><ShieldCheck size={19} strokeWidth={1.8} aria-hidden="true" />{allowanceLabel}</span>
        )}
      </div>

      <div className={styles.journey}>
        <ol className={styles.stageList} aria-label="Analysis stages">
          {rows.map((row) => {
            const state = visualState(row.state, needsAttention);
            const Icon = row.Icon;
            return (
              <li
                className={styles.stage}
                key={row.id}
                data-state={state}
                aria-current={state === "active" ? "step" : undefined}
                aria-label={`${row.title}: ${row.label ?? (row.state === null ? "Not started" : row.state)}`}
              >
                <span className={styles.stageIcon} aria-hidden="true">
                  {state === "completed" ? <Check size={24} strokeWidth={2.8} /> : <Icon size={27} strokeWidth={1.9} />}
                </span>
                <strong>{row.title}</strong>
                <small>{row.description}</small>
              </li>
            );
          })}
        </ol>

        <div className={styles.signalCard} data-animated={active && !needsAttention}>
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
            <strong>{statusText}</strong>
            <p>The stages above reflect the latest confirmed update for this call.</p>
          </div>
        </div>
      </div>

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
      </div>
      {children && <div className={styles.actions}>{children}</div>}
    </section>
  );
}
