/**
 * How long a workspace switch takes, as the person feels it (owner, 25 Oct
 * 2026, Admin #17: "switching orgs is slow"). Two numbers per switch: tap to
 * the first visible answer (the new name and the page's outline), and tap to
 * a usable screen in the new workspace (its context known and its first frame
 * drawn after the reload). The tap is kept for the next document in
 * sessionStorage; the last results stay on this device for checks
 * ("[sx-switch]" in the console, `sx-switch-times` in localStorage). Nothing
 * leaves the device.
 */

const MARK = "sx-switch-timing";
const TIMES = "sx-switch-times";
const KEEP = 20;
// A mark older than this belongs to a switch that never finished.
const STALE_MS = 60_000;

type Mark = { at: number; to: string; feedback?: number };
export type SwitchTime = {
  at: number;
  feedback: number | null;
  usable: number;
};

function read<T>(storage: Storage, key: string): T | null {
  try {
    const raw = storage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(storage: Storage, key: string, value: unknown) {
  try {
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(value));
  } catch {
    // Private windows and full storage: timing is a nicety, never a blocker.
  }
}

/** The tap: kept for the next document. */
export function markSwitchStart(tenantId: string, now = Date.now()) {
  write(sessionStorage, MARK, { at: now, to: tenantId } satisfies Mark);
}

/** The first frame that answered the tap. */
export function markSwitchFeedback(now = Date.now()) {
  const mark = read<Mark>(sessionStorage, MARK);
  if (mark && mark.feedback === undefined)
    write(sessionStorage, MARK, { ...mark, feedback: now - mark.at });
}

/** A switch that did not happen: nothing to time. */
export function cancelSwitch() {
  write(sessionStorage, MARK, null);
}

/** The new workspace is usable: record the switch once, and say it. */
export function finishSwitch(
  tenantId: string | null,
  now = Date.now(),
): SwitchTime | null {
  const mark = read<Mark>(sessionStorage, MARK);
  if (!mark || !tenantId || mark.to !== tenantId) return null;
  write(sessionStorage, MARK, null);
  const usable = now - mark.at;
  if (usable < 0 || usable > STALE_MS) return null;
  const time: SwitchTime = {
    at: mark.at,
    feedback: mark.feedback ?? null,
    usable,
  };
  const kept = read<SwitchTime[]>(localStorage, TIMES) ?? [];
  write(localStorage, TIMES, [...kept, time].slice(-KEEP));
  console.info(
    `[sx-switch] tap to feedback ${time.feedback ?? "?"} ms, tap to usable ${usable} ms`,
  );
  return time;
}

/** The last switches on this device, oldest first. */
export function switchTimes(): SwitchTime[] {
  return read<SwitchTime[]>(localStorage, TIMES) ?? [];
}
