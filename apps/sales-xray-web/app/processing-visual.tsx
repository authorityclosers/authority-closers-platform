import {
  AudioLines,
  FileText,
  Pause,
  ScanText,
  Sparkles,
  Upload,
} from "lucide-react";
import styles from "./processing-visual.module.css";

export type ProcessingVisualPhase =
  | "upload"
  | "C2"
  | "C4"
  | "C5"
  | "processing";
const phaseIcons = {
  upload: Upload,
  C2: FileText,
  C4: ScanText,
  C5: Sparkles,
  processing: AudioLines,
};

/** Ambient motion represents activity only; completion comes from server stages. */
export function ProcessingVisual({
  phase,
  paused,
}: {
  phase: ProcessingVisualPhase;
  paused: boolean;
}) {
  const Icon = paused ? Pause : phaseIcons[phase];
  return (
    <div
      className={styles.visual}
      data-paused={paused}
      data-phase={phase}
      aria-hidden="true"
    >
      <span className={styles.halo} />
      <span className={styles.icon}>
        <Icon size={42} strokeWidth={1.8} />
      </span>
      <span className={styles.satellite}>
        <AudioLines size={18} />
      </span>
    </div>
  );
}
