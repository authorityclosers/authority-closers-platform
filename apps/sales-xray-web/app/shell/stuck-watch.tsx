"use client";

/**
 * A screen stuck loading offers Reload (orchestrator, 24 Oct 2026: a tester
 * reinstalled the app when it "hung a little"; the app should never need
 * that). When a loading outline (aria-busy) covers much of the screen for
 * 15 seconds, a corner card says so with Reload; it leaves by itself once the
 * screen has loaded.
 */
import { useEffect } from "react";

import { dismissNotice, notify } from "../notice-center";

export const STUCK_AFTER_MS = 15_000;
const CHECK_EVERY_MS = 2_000;
export const STUCK_NOTICE = "screen-stuck";

/** True while a loading outline covers at least a third of the screen. */
export function loadingOnScreen(): boolean {
  const width = window.innerWidth;
  const height = window.innerHeight;
  const area = width * height;
  if (!area) return false;
  for (const element of document.querySelectorAll<HTMLElement>(
    '[aria-busy="true"]',
  )) {
    const box = element.getBoundingClientRect();
    const seen =
      Math.max(0, Math.min(box.right, width) - Math.max(box.left, 0)) *
      Math.max(0, Math.min(box.bottom, height) - Math.max(box.top, 0));
    if (seen >= area / 3) return true;
  }
  return false;
}

export function StuckWatch() {
  useEffect(() => {
    let since: number | null = null;
    let shown = false;
    const check = () => {
      if (document.visibilityState !== "visible") {
        since = null;
        return;
      }
      if (!loadingOnScreen()) {
        since = null;
        if (shown) {
          shown = false;
          dismissNotice(STUCK_NOTICE);
        }
        return;
      }
      since ??= Date.now();
      if (shown || Date.now() - since < STUCK_AFTER_MS) return;
      shown = true;
      notify({
        id: STUCK_NOTICE,
        tone: "info",
        title: "This is taking longer than usual",
        message:
          navigator.onLine === false
            ? "This phone has no connection. The screen loads once it's back."
            : "Reload to start this screen again. You stay signed in, and nothing you entered is lost.",
        action: { label: "Reload", run: () => window.location.reload() },
        // Closing it keeps it away until the next time a screen is stuck.
        onDismiss: async () => undefined,
      });
    };
    const timer = window.setInterval(check, CHECK_EVERY_MS);
    return () => window.clearInterval(timer);
  }, []);
  return null;
}
