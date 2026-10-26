"use client";

import { useSyncExternalStore } from "react";

import {
  dropKept,
  holdState,
  installReleaseHoldFetch,
  sendKept,
  subscribeHold,
} from "./release-hold";
import styles from "./release-hold.module.css";

// In front of every fetch before any page asks for anything: this module loads with the
// layout, ahead of the pages' effects.
installReleaseHoldFetch();

function useHoldState() {
  return useSyncExternalStore(subscribeHold, holdState, holdState);
}

/** The calm line at the top while Sales X-Ray updates (release-hold.ts). */
export function ReleaseHoldBanner() {
  const { holding, kept } = useHoldState();
  if (!holding && kept === 0) return null;
  return (
    <div className={styles.banner} role="status" aria-live="polite">
      {holding ? <span className={styles.pulse} aria-hidden="true" /> : null}
      <span>
        {holding
          ? "Updating Sales X-Ray, back in a moment"
          : "Sales X-Ray is back"}
        {kept > 0 ? ". Your change is kept." : null}
      </span>
      {kept > 0 ? (
        <span className={styles.actions}>
          <button type="button" className={styles.primary} onClick={sendKept}>
            Retry
          </button>
          {holding ? null : (
            <button type="button" className={styles.quiet} onClick={dropKept}>
              Not now
            </button>
          )}
        </span>
      ) : null}
    </div>
  );
}
