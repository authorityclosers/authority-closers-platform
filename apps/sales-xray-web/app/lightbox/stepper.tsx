import { Glyph } from "./glyph";
import styles from "./stepper.module.css";

/** Journey position only; a completed step never implies analysis progress. */
export function Stepper({
  steps,
  current,
  label = "Steps",
  className = "",
}: {
  steps: readonly string[];
  /** Zero-based index of the current step. */
  current: number;
  label?: string;
  className?: string;
}) {
  return (
    <ol className={`${styles.stepper} ${className}`} aria-label={label}>
      {steps.map((step, index) => {
        const state =
          index < current ? "done" : index === current ? "current" : "next";
        return (
          <li
            key={step}
            className={styles.step}
            data-step-state={state}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className={styles.marker} aria-hidden="true">
              {state === "done" ? (
                <Glyph name="strength" size={16} />
              ) : (
                index + 1
              )}
            </span>
            {state === "done" ? (
              <span className={styles.visuallyHidden}>Completed: </span>
            ) : null}
            {step}
          </li>
        );
      })}
    </ol>
  );
}
