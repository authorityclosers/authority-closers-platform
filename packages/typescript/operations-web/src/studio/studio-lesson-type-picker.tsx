"use client";

import { useId } from "react";
import { Check, ChevronDown } from "lucide-react";
import { LearningSymbol } from "@ac/ui";
import type { StudioActivityKind } from "../admin-api";
import styles from "./studio-lesson-type-picker.module.css";

export const studioLessonKinds = {
  VIDEO: {
    label: "Video lesson",
    symbol: "watch",
    description: "Teach with a video and supporting instructions.",
  },
  REFLECTION: {
    label: "Reflection",
    symbol: "reflect",
    description: "Ask a question that helps the learning sink in.",
  },
  IMPLEMENTATION_CHALLENGE: {
    label: "Implementation",
    symbol: "implement",
    description: "Give learners a task to try in the real world.",
  },
  REVIEW: {
    label: "Review",
    symbol: "review",
    description: "Make space to review the learner’s work.",
  },
  IMPROVE: {
    label: "Improve",
    symbol: "improve",
    description: "Help learners refine what they have practised.",
  },
} as const;

/** Native radio behavior, one semantic palette, shared by Coach and Admin. */
export function StudioLessonTypePicker({
  value,
  disabled,
  onChange,
}: {
  value: StudioActivityKind;
  disabled: boolean;
  onChange: (kind: StudioActivityKind) => void;
}) {
  const id = useId();
  return (
    <details className={styles.disclosure}>
      <summary>
        <LearningSymbol kind={studioLessonKinds[value].symbol} size={36} />
        <span>
          <small>Lesson format</small>
          <strong>{studioLessonKinds[value].label}</strong>
        </span>
        <span className={styles.change}>
          Change <ChevronDown size={16} aria-hidden="true" />
        </span>
      </summary>
      <fieldset className={styles.picker} disabled={disabled}>
        <legend>What would you like to add?</legend>
        <p className={styles.hint}>
          Choose a format. You’ll add the title and instructions below.
        </p>
        <div className={styles.options}>
          {Object.entries(studioLessonKinds).map(([kind, item]) => (
            <label key={kind} className={styles.option}>
              <input
                type="radio"
                name={`${id}-lesson-kind`}
                value={kind}
                aria-label={item.label}
                aria-describedby={`${id}-${kind}-hint`}
                checked={value === kind}
                onChange={() => onChange(kind as StudioActivityKind)}
              />
              <span className={styles.card}>
                <LearningSymbol kind={item.symbol} size={36} />
                <span className={styles.words}>
                  <strong>{item.label}</strong>
                  <small id={`${id}-${kind}-hint`}>{item.description}</small>
                </span>
                <span className={styles.selected} aria-hidden="true">
                  <Check size={13} />
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    </details>
  );
}
