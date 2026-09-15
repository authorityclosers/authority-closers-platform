import styles from "./processing-visual.module.css";

export type ProcessingVisualPhase =
  | "upload"
  | "C2"
  | "C4"
  | "C5"
  | "processing";

// Decorative bars give the processing state a calm visual rhythm. They are
// intentionally not derived from audio data or progress percentages.
const waveformBars = [
  4, 6, 8, 10, 13, 18, 25, 34, 46, 62, 84, 108, 78, 52, 32, 22, 14, 10, 8, 12,
  18, 29, 44, 64, 92, 112, 86, 58, 34, 22, 15, 11, 8, 10, 14, 21, 32, 48, 70,
  92, 66, 42, 27, 17, 12, 9, 7, 6, 5,
];

const phaseMessages: Record<ProcessingVisualPhase, readonly string[]> = {
  upload: ["Reading the recording", "Checking its duration", "Saving the source"],
  C2: ["Preparing the transcript", "Keeping source timing", "Waiting for the next confirmed stage"],
  C4: ["Reading the conversation", "Checking source evidence", "Preparing the review"],
  C5: ["Writing the coaching report", "Keeping the evidence attached", "Preparing your next step"],
  processing: ["Checking the recording", "Keeping your work private", "Preparing the next confirmed stage"],
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
        viewBox="0 0 760 160"
        preserveAspectRatio="none"
        focusable="false"
      >
        <line className={styles.baseline} x1="54" y1="80" x2="706" y2="80" />
        {waveformBars.map((height, index) => (
          <rect
            key={`${height}-${index}`}
            className={styles.bar}
            x={54 + index * 13.6}
            y={80 - height / 2}
            width="5"
            height={height}
            rx="2.5"
            style={{ animationDelay: `${index * -42}ms` }}
          />
        ))}
        <circle className={styles.dot} cx="54" cy="80" r="3" />
        <circle className={styles.dot} cx="706" cy="80" r="3" />
      </svg>
      <div className={styles.thoughtStream}>
        {phaseMessages[phase].map((message, index) => (
          <span
            key={message}
            className={styles.thought}
            style={{ animationDelay: `${index * 480}ms` }}
          >
            {message}
          </span>
        ))}
      </div>
    </div>
  );
}
