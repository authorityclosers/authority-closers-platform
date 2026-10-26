"use client";

/**
 * Call from Sales X-Ray, not the phone's dialler (builder, 24 Oct 2026): inside
 * the phone app a call placed here gets "How did the call go?" and its
 * recording. The Play build does not read the call log, so a call made from the
 * phone's own dialler is never seen. In a browser there is nothing to say.
 */

import { Info } from "lucide-react";
import { useSyncExternalStore } from "react";

import styles from "./leads.module.css";
import { inPhoneApp } from "./native-phone";

export const IN_APP_CALL = "Call from Sales X-Ray";
export const IN_APP_CALL_HINT =
  "Calls made here are logged, with their recording.";

const still = () => () => undefined;

/** Whether this page runs inside the phone app; false while rendering on the server. */
export function useInPhoneApp(): boolean {
  return useSyncExternalStore(still, inPhoneApp, () => false);
}

/** The one line under a call button, in the phone app only: a hint, not a
 *  warning (owner, #30, 26 Oct 2026: it read like an error). */
export function InAppCallHint() {
  const inApp = useInPhoneApp();
  if (!inApp) return null;
  return (
    <p className={styles.callHint} data-call-hint="">
      <Info size={14} aria-hidden="true" />
      <span>{IN_APP_CALL_HINT}</span>
    </p>
  );
}
