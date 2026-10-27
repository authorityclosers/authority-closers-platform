/**
 * Where this person left off (owner, 27 Oct 2026: a returning user should see
 * data they recognise): the lead or Report they opened last, kept on this
 * device only, for Home's "Pick up where you left off". The lead sheet and the
 * Report write it; Home reads it. No React, so the writers stay light.
 */

const PICK_UP_KEY = "sx-pick-up";
const PICK_UP_DAYS = 3;
export const PICK_UP_EVENT = "sx:pick-up";

export type Opened = {
  kind: "lead" | "call";
  id: string;
  name: string;
  at: string;
  person: string;
  tenant: string;
};

/** Remembers what was just opened, for this person and workspace. */
export function rememberOpened(
  item: Omit<Opened, "at">,
  now: Date = new Date(),
): void {
  try {
    localStorage.setItem(
      PICK_UP_KEY,
      JSON.stringify({ ...item, at: now.toISOString() }),
    );
    window.dispatchEvent(new Event(PICK_UP_EVENT));
  } catch {
    // Storage blocked: nothing to pick up next time.
  }
}

/** The thing to pick up, if it is this person's, here, and recent. */
export function pickUpFrom(
  raw: string | null,
  who: { person: string; tenant: string } | null,
  now: Date = new Date(),
): Opened | null {
  if (!raw || !who) return null;
  try {
    const value = JSON.parse(raw) as Partial<Opened>;
    if (
      (value.kind !== "lead" && value.kind !== "call") ||
      typeof value.id !== "string" ||
      typeof value.name !== "string" ||
      typeof value.at !== "string" ||
      value.person !== who.person ||
      value.tenant !== who.tenant
    )
      return null;
    const age = now.getTime() - Date.parse(value.at);
    if (!(age >= 0 && age < PICK_UP_DAYS * 86_400_000)) return null;
    return value as Opened;
  } catch {
    return null;
  }
}

/** The stored value, or null where storage is blocked. */
export function readPickUp(): string | null {
  try {
    return localStorage.getItem(PICK_UP_KEY);
  } catch {
    return null;
  }
}

/** Calls back when it changes here or in another tab. */
export function onPickUp(change: () => void): () => void {
  window.addEventListener(PICK_UP_EVENT, change);
  window.addEventListener("storage", change);
  return () => {
    window.removeEventListener(PICK_UP_EVENT, change);
    window.removeEventListener("storage", change);
  };
}
