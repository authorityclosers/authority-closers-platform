"use client";

/**
 * The reporter in plain sight on a computer (orchestrator for the owner, 31 Oct 2026: it was
 * found only through Ctrl K): a small round button in the corner, and Report a problem in the
 * profile menu. Anyone may hide the button; it stays hidden in this browser, and the profile
 * menu shows it again. Phones keep shake-to-report and their own menus.
 */
import { MessageSquareWarning, X } from "lucide-react";
import { useSyncExternalStore } from "react";

import { notify } from "../notice-center";
import { openBugReport } from "./open";
import styles from "./bug-report.module.css";

const HIDDEN_KEY = "sx.report-button.hidden";
const CHANGED = "sales-xray:report-button";

// Where storage is closed (a private window), hiding holds until the page reloads.
let hiddenHere: boolean | null = null;

function hidden(): boolean {
  if (hiddenHere !== null) return hiddenHere;
  try {
    return window.localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

function watch(change: () => void) {
  window.addEventListener(CHANGED, change);
  window.addEventListener("storage", change);
  return () => {
    window.removeEventListener(CHANGED, change);
    window.removeEventListener("storage", change);
  };
}

/** Whether the person hid the corner button. */
export function useReportButtonHidden(): boolean {
  return useSyncExternalStore(watch, hidden, () => false);
}

export function setReportButtonHidden(hide: boolean) {
  hiddenHere = hide;
  try {
    if (hide) window.localStorage.setItem(HIDDEN_KEY, "1");
    else window.localStorage.removeItem(HIDDEN_KEY);
  } catch {
    // No storage here: it holds for this page.
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function ReportButton() {
  const off = useReportButtonHidden();
  if (off) return null;
  return (
    // Its own picture of the screen leaves it out (capture.ts).
    <div className={styles.corner} data-capture-skip="">
      <button
        type="button"
        className={styles.cornerButton}
        aria-label="Report a problem"
        title="Report a problem"
        onClick={() => openBugReport()}
      >
        <MessageSquareWarning size={18} aria-hidden="true" />
      </button>
      <button
        type="button"
        className={styles.cornerHide}
        aria-label="Hide the report button"
        title="Hide"
        onClick={() => {
          setReportButtonHidden(true);
          notify({
            id: "report-button",
            tone: "info",
            title: "Report button hidden",
            message: "Report a problem stays in your profile menu.",
            action: {
              label: "Show it again",
              run: () => setReportButtonHidden(false),
            },
          });
        }}
      >
        <X size={12} aria-hidden="true" />
      </button>
    </div>
  );
}
