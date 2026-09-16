"use client";

import { useEffect, useState } from "react";
import type { Progress } from "./acquisition-client";
import styles from "./acquisition-studio.module.css";

// This is a local observation window, not a provider timeout or failure signal.
const UPDATE_WAIT_MS = 60_000;

function ActiveStatusCopy({ title }: { title: string }) {
  const [delayed, setDelayed] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setDelayed(true), UPDATE_WAIT_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className={styles.progressCopy} data-update-delayed={delayed}>
      <p className={styles.progressKicker}>
        {delayed ? "WAITING FOR AN UPDATE" : "ANALYSIS IN PROGRESS"}
      </p>
      <h3>{title}</h3>
      <p className={styles.progressUpdateMessage}>
        {/* Reserve both copy variants so the timer cannot move the stage rail
            or recovery actions, including when text wraps on mobile. */}
        <span aria-hidden={delayed || undefined} data-visible={!delayed}>
          Your call is saved. We’ll update each step as your analysis completes.
        </span>
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
  return <ActiveStatusCopy key={updateKey} title={title} />;
}
