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
 * Junk aren't on the path: they are under the stage's Change, above the strip
 * (Shivam's review, 17 Nov 2026). A path wider than the card slides sideways,
 * each step at least 72 dp, so no name runs into the next at large text.
 * On a phone the strip shows three steps, the one before, the current one
 * and the next, each a third of the card, with a fading line at an edge
 * where more steps sit (v1.96 device polish: at 360-430 the sliding strip
 * cut the next name mid-word, "Meetin… schedu…"). The rest are under Change.
 */

import { sideScrollFades, useSideScroll } from "@ac/ui/kit";

import type { Kind, StageView } from "./journey/journey-client";
import { stageName, type Side } from "./journey/stage-look";
import { useLayoutEffect, type CSSProperties } from "react";

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

/** A stage's name as the strip says it, short and in sentence case (Leads
 *  part 06, P5's words): "Open" for "Open Leads", "Meeting scheduled". */
export function stripWord(label: string): string {
  return label
    .trim()
    .replace(/\s+Leads$/i, "")
    .split(/\s+/)
    .map((word, index) =>
      index > 0 && /^[A-Z][a-z]+$/.test(word) ? word.toLowerCase() : word,
    )
    .join(" ");
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
  // The phone's three: the step before, the current one and the next (the
  // first three, or the last three, at an end of the path).
  const first = Math.max(0, Math.min(at - 1, steps.length - 3));
  const last = Math.min(steps.length - 1, first + 2);
  // A path wider than the card: the current step in view, a fade at the edge
  // where more steps sit.
  // The step's own column (its offset within the strip, which is their
  // positioned parent), not the words inside it.
  const { ref, edges } = useSideScroll<HTMLOListElement>(
    'li[data-state="current"]',
    current,
  );
  // The line from each dot to the one before, measured: the columns differ.
  useLayoutEffect(() => {
    const list = ref.current;
    if (!list) return;
    const place = () => {
      // The steps drawn (a phone hides those away from the current one): a
      // line joins each to the one drawn before it.
      const items = (Array.from(list.children) as HTMLElement[]).filter(
        (item) => item.offsetParent !== null,
      );
      const centre = (item: HTMLElement) => {
        const dot = item.querySelector<HTMLElement>("[data-step-dot]");
        return (
          item.offsetLeft +
          (dot ? dot.offsetLeft + dot.offsetWidth / 2 : item.offsetWidth / 2)
        );
      };
      items.forEach((item, index) => {
        if (index === 0) {
          item.style.removeProperty("--line-from");
          item.style.removeProperty("--line-span");
          return;
        }
        const from = centre(items[index - 1]);
        const to = centre(item);
        item.style.setProperty("--line-from", `${from - item.offsetLeft}px`);
        item.style.setProperty("--line-span", `${to - from}px`);
      });
    };
    place();
    const watch =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    watch?.observe(list);
    return () => watch?.disconnect();
  }, [ref, steps, current]);
  return (
    <ol
      ref={ref}
      {...edges}
      className={`${styles.stepper} ${sideScrollFades}`}
      aria-label="Stage"
      // A strip that slides is reached by keyboard too (axe
      // scrollable-region-focusable, v1.93 Readability Gate): Tab, then the
      // arrow keys scroll it.
      tabIndex={0}
      style={
        {
          // Each column as wide as its step's longest word and at least 72 dp
          // (the step's own min-width), spread across the card when they fit;
          // a longer path slides, the next step peeking (Shivam's review, 17
          // Nov 2026: minmax(36px, min-content) never grew past 36 dp in a
          // full strip, so the names ran into each other).
          // A phone's three columns come from lead-page.module.css.
          "--step-count": steps.length,
          "--step-near": last - first + 1,
        } as CSSProperties
      }
    >
      {steps.map((step, index) => {
        const state = index < at ? "done" : index === at ? "current" : "ahead";
        const dot = (
          <span className={styles.stepDot} data-step-dot="" aria-hidden="true">
            {state === "done" ? (
              <svg viewBox="0 0 16 16">
                <path d="M4 8.5l2.5 2.5L12 5.5" />
              </svg>
            ) : null}
          </span>
        );
        const words = (
          <span className={styles.stepLabel}>{stripWord(step.label)}</span>
        );
        return (
          <li
            key={step.key}
            className={styles.step}
            data-state={state}
            // Away from the current step: hidden on a phone. At the edge of
            // the phone's three with more beyond it: a fading line.
            data-far={index < first || index > last ? "" : undefined}
            data-more={
              index === first && first > 0
                ? "before"
                : index === last && last < steps.length - 1
                  ? "after"
                  : undefined
            }
          >
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
