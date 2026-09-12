"use client";
import { useSyncExternalStore } from "react";
import {
  PracticeCompanion,
  type PracticeCompanionKind,
  type PracticeCompanionMood,
} from "@ac/ui";
import {
  readPracticeCompanionMotion,
  subscribePracticeCompanion,
} from "../lib/practice-presentation";
import styles from "./practice-companion-stage.module.css";

/** A finite entrance/reaction; reduced-motion preferences remain authoritative. */
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
        motion={enabled ? "once" : "off"}
      />
    </div>
  );
}
