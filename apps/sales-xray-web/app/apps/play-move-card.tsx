"use client";

/**
 * Inside the download-link app, for everyone on it (orchestrator, 24 Oct
 * 2026): a corner card saying Sales X-Ray is moving to Google Play, with
 * "Switch to Play" and "Later" (a week). That app has no updater of its own,
 * so the page it shows is how its users hear.
 */
import { useEffect, useState } from "react";

import { inPhoneApp, phoneStatus } from "../leads/native-phone";
import { notify } from "../notice-center";
import { replayWrites, useWrites } from "../sync/write-queue";
import { PLAY, unsentLine } from "./play";

export const PLAY_MOVE_SEEN = "sx-play-move-card";
/** "Later", the X or "Switch to Play" hide the card for a week. */
export const PLAY_MOVE_AGAIN_MS = 7 * 24 * 60 * 60 * 1000;

function hidden(): boolean {
  try {
    const at = Date.parse(window.localStorage.getItem(PLAY_MOVE_SEEN) ?? "");
    return Number.isFinite(at) && Date.now() - at < PLAY_MOVE_AGAIN_MS;
  } catch {
    return true;
  }
}

function hideForAWeek() {
  try {
    window.localStorage.setItem(PLAY_MOVE_SEEN, new Date().toISOString());
  } catch {
    // Storage blocked: the card may come back next time.
  }
}

export function PlayMoveCard() {
  const [shown, setShown] = useState(false);
  const { deviceTotal } = useWrites();
  useEffect(() => {
    if (!inPhoneApp() || hidden()) return;
    let alive = true;
    void phoneStatus().then((status) => {
      // Builds that don't say their store are download-link builds too.
      if (alive && status && status.store !== "play") setShown(true);
    });
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!shown) return;
    const later = async () => {
      hideForAWeek();
      setShown(false);
    };
    // An uninstall deletes changes not sent yet: no Switch until they're sent.
    if (deviceTotal > 0) {
      notify({
        id: "play-move",
        tone: "info",
        title: PLAY.cardTitle,
        message: `${unsentLine(deviceTotal)} Uninstalling this app now would delete ${
          deviceTotal === 1 ? "it" : "them"
        }; you can switch once ${deviceTotal === 1 ? "it's" : "they're"} sent.`,
        action: {
          label: "Send now",
          run: () => void replayWrites({ force: true }),
        },
        dismissLabel: "Later",
        onDismiss: later,
      });
      return;
    }
    notify({
      id: "play-move",
      tone: "info",
      title: PLAY.cardTitle,
      message: PLAY.cardMessage,
      action: {
        label: "Switch to Play",
        icon: "open",
        run: () => {
          hideForAWeek();
          window.location.href = PLAY.url;
        },
      },
      dismissLabel: "Later",
      // Stays until dismissed.
      onDismiss: later,
    });
  }, [shown, deviceTotal]);
  return null;
}
