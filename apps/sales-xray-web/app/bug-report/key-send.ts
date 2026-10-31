/**
 * Sending a bug report from the keyboard (owner, 31 Oct 2026: "ctrl + enter
 * and enter to submit ... with only one time asking confirmation ... once a
 * tick box is ticked that never ask this again"), shared by the basic and the
 * advanced reporter. The choice is kept on this device (the app has no
 * per-person preferences store); where storage is off, it simply asks each time.
 */

export const KEY_SEND_STORE = "sx-bug-report-keys-send";

export function keySendAsks(): boolean {
  try {
    return window.localStorage.getItem(KEY_SEND_STORE) !== "without-asking";
  } catch {
    return true;
  }
}

export function stopAskingOnKeySend(): void {
  try {
    window.localStorage.setItem(KEY_SEND_STORE, "without-asking");
  } catch {
    // Storage is off: it asks again next time.
  }
}

/** Enter sends on a computer; on a touch screen it stays a new line (as Chats). */
export function enterSends(): boolean {
  return window.matchMedia?.("(pointer: fine)").matches !== false;
}
