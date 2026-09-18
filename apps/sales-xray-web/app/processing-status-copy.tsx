"use client";

import { useEffect, useState } from "react";
import type { Progress } from "./acquisition-client";
import styles from "./acquisition-studio.module.css";

// This is a local observation window, not a provider timeout or failure signal.
const UPDATE_WAIT_MS = 60_000;
const CUE_INTERVAL_MS = 8_000;
const savedCue = "Your call is saved. There’s no need to upload it again.";
const stageCues = {
  checking: [
    "Checking the recording’s format and duration before analysis starts.",
    "Longer recordings can take a little longer to check.",
    savedCue,
  ],
  C2: [
    "Turning your recording into a transcript.",
    "The transcript keeps your analysis linked to the recording.",
    savedCue,
  ],
  C4: [
    "Reviewing the conversation against its transcript.",
    "This step connects observations with source moments.",
    savedCue,
  ],
  C5: [
    "Bringing your takeaways and next-call plan together.",
    "The report will open when its result is ready.",
    savedCue,
  ],
  waiting: [
    "Your call is saved. Waiting for the next stage update.",
    "Each step updates when its status is confirmed.",
    savedCue,
  ],
};

function cuesFor(progress: Progress | null) {
  if (progress?.local_state !== "completed") return stageCues.checking;
  const stage = progress.stages.findLast(
    (row) => row.state === "running",
  )?.stage;
  return stage === "C2" || stage === "C4" || stage === "C5"
    ? stageCues[stage]
    : stageCues.waiting;
}

function ActiveStatusCopy({ title, cues }: { title: string; cues: string[] }) {
  const [delayed, setDelayed] = useState(false);
  const [cue, setCue] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => setDelayed(true), UPDATE_WAIT_MS);
    return () => clearTimeout(timer);
  }, []);
  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let timer: ReturnType<typeof setInterval> | undefined;
    const sync = () => {
      clearInterval(timer);
      // Informational text only: never advance the stage or claim completion.
      if (!delayed && !motion.matches)
        timer = setInterval(
          () => setCue((value) => (value + 1) % 3),
          CUE_INTERVAL_MS,
        );
    };
    sync();
    motion.addEventListener("change", sync);
    return () => {
      clearInterval(timer);
      motion.removeEventListener("change", sync);
    };
  }, [delayed]);

  return (
    <div className={styles.progressCopy} data-update-delayed={delayed}>
      <p className={styles.progressKicker}>
        {delayed ? "WAITING FOR AN UPDATE" : "ANALYSIS IN PROGRESS"}
      </p>
      <h3>{title}</h3>
      <p className={styles.progressUpdateMessage} aria-live="off">
        {/* Reserve all variants to avoid layout shift. These informational
            cues are not new stage announcements in the enclosing live region. */}
        {cues.map((text, index) => (
          <span
            key={text}
            aria-hidden={delayed || cue !== index || undefined}
            data-visible={!delayed && cue === index}
          >
            {text}
          </span>
        ))}
        <span aria-hidden={!delayed || undefined} data-visible={delayed}>
          No new stage update yet. Your call is saved; no need to upload again.
        </span>
      </p>
    </div>
  );
}

export function ProcessingStatusCopy({
  submissionId,
  progress,
  title,
  paused,
  needsAttention,
}: {
  submissionId: string;
  progress: Progress | null;
  title: string;
  paused: boolean;
  needsAttention: boolean;
}) {
  if (needsAttention) {
    return (
      <div className={styles.progressCopy}>
        <p className={styles.progressKicker}>
          {paused ? "SAVED WORK · PAUSED" : "STATUS NEEDS ATTENTION"}
        </p>
        <h3>{paused ? "Analysis paused" : "Your call needs attention"}</h3>
        <p>This stage needs checking before analysis can continue.</p>
      </div>
    );
  }

  // The parser exposes only these semantic fields. Identical polling responses
  // must not reset the wait; any new stage row (including another C4 chunk),
  // state, source identity or automatic-progression change does reset it.
  const updateKey = JSON.stringify([submissionId, progress]);
  return (
    <ActiveStatusCopy key={updateKey} title={title} cues={cuesFor(progress)} />
  );
}
