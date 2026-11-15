import type { UpdateNote, UpdateNotification } from "./updates-client";

const SESSION_KEY = "ac.xray.update-card-shown";
let shownInMemory = false;

/** A display throttle only. Seen/read receipts always belong to the API. */
export function claimUpdateCard(
  storage: Pick<Storage, "getItem" | "setItem"> | null,
): boolean {
  if (shownInMemory) return false;
  try {
    if (storage?.getItem(SESSION_KEY)) {
      shownInMemory = true;
      return false;
    }
    storage?.setItem(SESSION_KEY, "1");
  } catch {}
  shownInMemory = true;
  return true;
}

export function eligibleUpdate(notes: readonly UpdateNote[]) {
  return notes.find((note) => !note.seen && note.major);
}

/**
 * How old a line may be and still pop: a banner is news. Older unread lines
 * wait in the bell (tester report 206, production 1.58, 14 Nov 2026: "Website
 * Connect Test is your lead now", a lead given on 30 Oct, popped over a call
 * report two weeks later, as it did at every app open while it stayed unread).
 */
export const EVENT_BANNER_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export function eligibleEvents(
  entries: readonly UpdateNotification[],
  now = Date.now(),
) {
  return entries.filter(
    (entry) =>
      entry.kind !== "updates" &&
      !entry.read &&
      entry.urgent &&
      !(now - Date.parse(entry.created_at) > EVENT_BANNER_MAX_AGE_MS),
  );
}
