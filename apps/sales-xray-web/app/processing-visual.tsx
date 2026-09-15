import styles from "./processing-visual.module.css";

export type ProcessingVisualPhase =
  | "upload"
  | "C2"
  | "C4"
  | "C5"
  | "processing";

const phaseLabels: Record<ProcessingVisualPhase, string> = {
  upload: "Upload check",
  C2: "Transcription",
  C4: "Conversation check",
  C5: "Coaching report",
  processing: "Private processing",
};

export function ProcessingVisual({
  phase,
  paused,
}: {
  phase: ProcessingVisualPhase;
  paused: boolean;
}) {
  return (
    <div
      className={styles.visual}
      data-paused={paused}
      data-phase={phase}
      aria-hidden="true"
    >
      <svg
        className={styles.art}
        data-paused={paused}
        viewBox="0 0 160 160"
        focusable="false"
      >
        <defs>
          <linearGradient
            id="processing-visual-ring"
            x1="20"
            y1="20"
            x2="140"
            y2="140"
          >
            <stop offset="0" stopColor="currentColor" stopOpacity="0.28" />
            <stop offset="0.52" stopColor="currentColor" stopOpacity="0.96" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0.22" />
          </linearGradient>
          <radialGradient id="processing-visual-core">
            <stop offset="0" stopColor="currentColor" stopOpacity="0.9" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0.12" />
          </radialGradient>
        </defs>
        <circle className={styles.backdrop} cx="80" cy="80" r="64" />
        <circle className={styles.ring} cx="80" cy="80" r="49" />
        <circle className={styles.ringSecondary} cx="80" cy="80" r="37" />
        <path
          className={styles.orbit}
          d="M80 17a63 63 0 1 1-44.55 18.45"
          pathLength="100"
        />
        <path
          className={styles.wave}
          d="M42 80h13l7-14 10 29 10-38 11 46 9-23 7 11h12"
          pathLength="100"
        />
        <circle className={styles.core} cx="80" cy="80" r="19" />
        <circle className={styles.coreDot} cx="80" cy="80" r="5" />
      </svg>
      <span className={styles.phase}>{phaseLabels[phase]}</span>
      <span className={styles.status}>
        {paused ? "Paused" : "Status synced"}
      </span>
    </div>
  );
}
