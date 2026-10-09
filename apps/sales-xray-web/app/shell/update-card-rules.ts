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

export function eligibleEvents(entries: readonly UpdateNotification[]) {
  return entries.filter(
    (entry) => entry.kind !== "updates" && !entry.read && entry.urgent,
  );
}
