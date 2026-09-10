"use client";
import { useSyncExternalStore } from "react";
import {
  PracticeCompanion,
  type PracticeCompanionKind,
  type PracticeCompanionMood,
} from "@ac/ui";
import { Pause, Play } from "lucide-react";
import {
  readPracticeCompanionMotion,
  savePracticeCompanionMotion,
  subscribePracticeCompanion,
} from "../lib/practice-presentation";
import styles from "./practice-companion-stage.module.css";

/** Persistent motion control belongs next to the live character, not behind settings. */
export function PracticeCompanionStage({
  variant,
  mood,
  size = 156,
  active = true,
}: {
  variant: PracticeCompanionKind;
  mood: PracticeCompanionMood;
  size?: number;
  active?: boolean;
}) {
  const enabled = useSyncExternalStore(
    subscribePracticeCompanion,
    readPracticeCompanionMotion,
    () => true,
  );
  return (
    <div className={styles.stage}>
      <PracticeCompanion
        variant={variant}
        mood={mood}
        size={size}
        active={active}
        motion={enabled ? "alive" : "off"}
      />
      <button
        className={styles.toggle}
        aria-label={
          enabled ? "Pause character animation" : "Resume character animation"
        }
        title={
          enabled ? "Pause character animation" : "Resume character animation"
        }
        onClick={() => savePracticeCompanionMotion(!enabled)}
      >
        {enabled ? (
          <Pause size={14} aria-hidden="true" />
        ) : (
          <Play size={14} aria-hidden="true" />
        )}
      </button>
    </div>
  );
}
