"use client";

/**
 * The lead's stage as a step strip (Dipak, 31 Oct 2026: not a dropdown; lead
 * page P5, spec §3; the pipeline's round 2): the organisation's main path
 * in order, each step an equal column of at least 64 dp, done steps as
 * filled dots with a check, the current one a ring with its name in teal,
 * those ahead as small rings, a line joining them, teal up to the current
 * step. Names sit under the dots, up to two lines. A step ahead or behind
 * that the lead may move to opens the stage sheet on it, which asks what the
 * move needs (a meeting's time, a reason) before it moves anything. Lost and
 * Junk aren't on the path: they are in More.
 */

import { sideScrollFades, useSideScroll } from "@ac/ui/kit";

import type { Kind, StageView } from "./journey/journey-client";
import { stageName, type Side } from "./journey/stage-look";
import styles from "./lead-page.module.css";

/** Kinds that close or sit beside the path, never steps on it. */
const OFF_PATH: ReadonlySet<Kind | string> = new Set([
  "lost",
  "junk",
  "not_connected",
]);

export type PathStep = { key: string; label: string };

/** The organisation's main path, in order, named for the side shown. A lead
 *  in a stage beside it that isn't a close (Not Connected) has that stage on
 *  its own strip, where the organisation keeps it. */
export function mainPath(
  stages: readonly StageView[] | null | undefined,
  side: Side,
  current: string | null = null,
): PathStep[] {
  return (stages ?? [])
    .filter(
      (stage) =>
        !stage.archived &&
        stage.visible !== false &&
        (!OFF_PATH.has(stage.kind) ||
          (stage.key === current && stage.kind === "not_connected")),
    )
    .map((stage) => ({ key: stage.key, label: stageName(stage, side) }));
}

export function StageStepper({
  steps,
  current,
  movable,
  onPick,
}: {
  steps: readonly PathStep[];
  /** The lead's own stage (its key). */
  current: string;
  /** The steps it may move to now (the lead's moves). */
  movable: ReadonlySet<string>;
  onPick: (key: string) => void;
}) {
  const at = steps.findIndex((step) => step.key === current);
  // A path wider than the card: the current step in view, a fade at the edge
  // where more steps sit.
  // The step's own column (its offset within the strip, which is their
  // positioned parent), not the words inside it.
  const { ref, edges } = useSideScroll<HTMLOListElement>(
    'li[data-state="current"]',
    current,
  );
  return (
    <ol
      ref={ref}
      {...edges}
      className={`${styles.stepper} ${sideScrollFades}`}
      aria-label="Stage"
      style={{
        // Equal columns, at least 64 dp and wide enough for a step's longest
        // word (6 em of its xs type: the current step's bold "Connected" fits); spread out when they fit, else the
        // strip scrolls.
        gridTemplateColumns: `repeat(${steps.length}, minmax(max(64px, 6em), 1fr))`,
      }}
    >
      {steps.map((step, index) => {
        const state = index < at ? "done" : index === at ? "current" : "ahead";
        const dot = (
          <span className={styles.stepDot} aria-hidden="true">
            {state === "done" ? (
              <svg viewBox="0 0 16 16">
                <path d="M4 8.5l2.5 2.5L12 5.5" />
              </svg>
            ) : null}
          </span>
        );
        const words = <span className={styles.stepLabel}>{step.label}</span>;
        return (
          <li key={step.key} className={styles.step} data-state={state}>
            {state !== "current" && movable.has(step.key) ? (
              <button
                type="button"
                className={styles.stepButton}
                aria-label={`Move to ${step.label}`}
                aria-haspopup="dialog"
                onClick={() => onPick(step.key)}
              >
                {dot}
                {words}
              </button>
            ) : (
              <span
                className={styles.stepButton}
                aria-current={state === "current" ? "step" : undefined}
              >
                {dot}
                {words}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
