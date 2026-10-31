"use client";

/**
 * A call's "Fix recording" opens the recording check over the call (phone
 * personas on v1.21, 1 Nov 2026: it opened Settings, Privacy at Usage
 * analytics, two screens above the check, and Back went to Leads instead of
 * the call). Closing the sheet, or Back, returns to the call.
 */

import dynamic from "next/dynamic";
import { useState } from "react";

import { Sheet } from "../ui/sheet";
import styles from "./capture-guard.module.css";

// The check loads when it opens: most calls never need it.
const RecordingFixBody = dynamic(
  () =>
    import("./recording-fix-body").then((module) => module.RecordingFixBody),
  { ssr: false },
);

export function RecordingFix({ label }: { label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={styles.fix}
        onClick={(event) => {
          // Inside a call row: open the check, not the row.
          event.preventDefault();
          event.stopPropagation();
          setOpen(true);
        }}
      >
        {label}
      </button>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title="Call recording check"
      >
        {open ? <RecordingFixBody /> : null}
      </Sheet>
    </>
  );
}
