"use client";

import { useEffect, useSyncExternalStore } from "react";

import { dismissNotice, notify } from "./notice-center";
import {
  dropKept,
  holdState,
  installReleaseHoldFetch,
  sendKept,
  subscribeHold,
} from "./release-hold";

// In front of every fetch before any page asks for anything: this module loads with the
// layout, ahead of the pages' effects.
installReleaseHoldFetch();

function useHoldState() {
  return useSyncExternalStore(subscribeHold, holdState, holdState);
}

const HOLD_NOTICE = "release-hold";

/**
 * While Sales X-Ray updates (release-hold.ts), one calm card says so: a corner card as
 * every app notice is, and one line at the top of Leads on a phone (the notice dock), so
 * it never covers the Inbound and Cold switch, the + or the tab bar (phone personas
 * ph1-43, 1 Nov 2026: the banner at the top did, said "Your change is kept" with nothing
 * changed, and its Retry did nothing while the update lasted). A change made meanwhile is
 * offered once Sales X-Ray is back: Send, or Not now.
 */
export function ReleaseHoldBanner() {
  const { holding, kept } = useHoldState();
  useEffect(() => {
    if (holding)
      notify({
        id: HOLD_NOTICE,
        tone: "info",
        title: "Sales X-Ray is updating",
        message:
          kept > 0
            ? "Back in a moment. What you just changed waits until then."
            : "Back in a moment. Anything still loading opens then.",
        timeout: 0,
        dock: true,
        noReport: true,
      });
    else if (kept > 0)
      notify({
        id: HOLD_NOTICE,
        tone: "info",
        title: "Sales X-Ray is back",
        message:
          kept === 1
            ? "Send the change you made while it updated?"
            : `Send the ${kept} changes you made while it updated?`,
        action: { label: "Send", run: sendKept, icon: "none" },
        dismissLabel: "Not now",
        onDismiss: async () => dropKept(),
        timeout: 0,
        dock: true,
        noReport: true,
      });
    else dismissNotice(HOLD_NOTICE);
  }, [holding, kept]);
  return null;
}
