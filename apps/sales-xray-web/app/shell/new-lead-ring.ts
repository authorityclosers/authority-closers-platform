/**
 * A new lead that came in by itself rings on a computer (owner, 17 Nov 2026:
 * "a nice notification to grab attention … so the hot lead gets contacted as
 * fast as possible"): the sound picked for "New lead given to me" (the sound
 * library, round-2 board 4, 20 Nov 2026; before, two notes made up in code)
 * when the browser lets the page play sound, and, while the tab is in the
 * background, a system notification that opens the lead. Only where
 * notifications are already allowed: this never asks for permission (no
 * prompt mid-use).
 */

import { playEvent } from "../sounds/player";

/** The picked new-lead sound; silent where the browser blocks sound. */
export function chime(): void {
  try {
    playEvent("sx.new_lead");
  } catch {
    // No sound here: the banner and the bell still show the lead.
  }
}

/** A system notification while the tab is hidden, where already allowed. */
export function popOnComputer(
  id: string,
  title: string,
  body: string | undefined,
  open: () => void,
): boolean {
  try {
    if (typeof window.Notification !== "function") return false;
    if (window.Notification.permission !== "granted") return false;
    if (document.visibilityState !== "hidden") return false;
    const shown = new window.Notification(title, {
      body: body ?? "",
      tag: `lead-new:${id}`,
      requireInteraction: true,
    });
    shown.onclick = () => {
      window.focus();
      open();
      shown.close();
    };
    return true;
  } catch {
    // Android's WebView and Chrome on a phone have no page notifications.
    return false;
  }
}

export function ringNewLead(
  id: string,
  title: string,
  body: string | undefined,
  open: () => void,
): void {
  chime();
  popOnComputer(id, title, body, open);
}
