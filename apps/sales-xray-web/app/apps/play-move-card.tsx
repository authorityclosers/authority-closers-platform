"use client";

/**
 * Inside the download-link app only, once per phone: a corner card saying Sales
 * X-Ray is now on Google Play, and how to switch without losing a recording
 * (the Android session, 24 Oct 2026). That app has no updater of its own, so
 * the page it shows is how its users hear.
 */
import { useEffect } from "react";

import { inPhoneApp, phoneStatus } from "../leads/native-phone";
import { notify } from "../notice-center";
import { usePlayLink } from "./play";

export const PLAY_MOVE_SEEN = "sx-play-move-card";

function seen(): boolean {
  try {
    return window.localStorage.getItem(PLAY_MOVE_SEEN) !== null;
  } catch {
    return true;
  }
}

function markSeen() {
  try {
    window.localStorage.setItem(PLAY_MOVE_SEEN, new Date().toISOString());
  } catch {
    // Storage blocked: the card may come back next time.
  }
}

export function PlayMoveCard() {
  const link = usePlayLink();
  useEffect(() => {
    if (!link || !inPhoneApp() || seen()) return;
    let alive = true;
    void phoneStatus().then((status) => {
      // Builds that don't say their store are download-link builds too.
      if (!alive || !status || status.store === "play") return;
      notify({
        id: "play-move",
        tone: "info",
        title: "Sales X-Ray is now on Google Play",
        message:
          "To switch, first analyse any conversation you recorded in this app; those recordings stay on this phone. Then uninstall this app and install it from Google Play. Your leads, calls and Reports are safe in your account.",
        action: {
          label: "Open Google Play",
          icon: "open",
          run: () => {
            markSeen();
            window.location.href = link;
          },
        },
        // Stays until dismissed; dismissed once is enough.
        onDismiss: async () => markSeen(),
      });
    });
    return () => {
      alive = false;
    };
  }, [link]);
  return null;
}
