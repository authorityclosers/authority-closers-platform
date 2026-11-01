"use client";

/**
 * A call's "Fix recording" opens the recording check over the call: the
 * checked list at the step that fails on this phone, ending in its test call,
 * the same as the no-recording line's Fix (phone personas ph2-09 and ph2-31 on
 * v1.22, 1 Nov 2026: it still opened Settings, Privacy at Usage analytics, and
 * Back closed the lead). The setup is a dialog of its own, so closing it, or
 * Back, returns to the call.
 */

import { fixRecording } from "../capture-setup/recording-check";
import styles from "./capture-guard.module.css";

export function RecordingFix({ label }: { label: string }) {
  return (
    <button
      type="button"
      className={styles.fix}
      onClick={(event) => {
        // Inside a call row: open the check, not the row.
        event.preventDefault();
        event.stopPropagation();
        void fixRecording();
      }}
    >
      {label}
    </button>
  );
}
