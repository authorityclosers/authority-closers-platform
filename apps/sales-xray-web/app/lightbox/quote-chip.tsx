import { Glyph } from "./glyph";
import { sourceTextAttributes } from "./script";
import { formatClock } from "./time";
import styles from "./quote-chip.module.css";

export type MomentKind =
  | "strength"
  | "focus"
  | "missed"
  | "objection"
  | "closing"
  | "hypothesis";

export const momentKindLabels: Record<MomentKind, string> = {
  strength: "strength",
  focus: "change first",
  missed: "missed opening",
  objection: "objection",
  closing: "closing",
  hypothesis: "possible reading",
};

export type QuoteChipState = "idle" | "playing" | "ended";

/**
 * A playable source quote. The quote is shown in full, in its original script;
 * it wraps instead of being clamped (INTEGRATION_DECISIONS.md decision 7).
 */
export function QuoteChip({
  startMs,
  quote,
  kind,
  state = "idle",
  onPlay,
  disabled = false,
  className = "",
}: {
  startMs: number;
  quote: string;
  kind: MomentKind;
  state?: QuoteChipState;
  onPlay: () => void;
  disabled?: boolean;
  className?: string;
}) {
  const clock = formatClock(startMs);
  return (
    <button
      type="button"
      className={`${styles.chip} ${className}`}
      data-kind={kind}
      data-state={state}
      aria-label={`Play ${momentKindLabels[kind]} moment at ${clock}: ${quote}`}
      disabled={disabled}
      onClick={onPlay}
    >
      <span className={styles.lead} aria-hidden="true">
        {state === "playing" ? (
          <span className={styles.equaliser} data-equaliser>
            <span />
            <span />
            <span />
          </span>
        ) : (
          <Glyph name={state === "ended" ? "retry" : "play-clip"} size={16} />
        )}
        <span className={styles.clock}>{clock}</span>
      </span>
      <q className={styles.quote} {...sourceTextAttributes(quote)}>
        {quote}
      </q>
    </button>
  );
}
