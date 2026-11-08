"use client";

/**
 * Inbound and Cold numbers for the Leads header's selector (Dipak's handoff,
 * items 05-06 and 44-45). The page waits for them before it draws (persona QA,
 * 31 Oct 2026: the selector arriving seconds late pushed Search aside, a layout
 * jump of 0.07 at 1440), at most SIDES_WAIT_MS from when they can be asked
 * for; the last answer per person and workspace is kept, in this visit and on
 * this device, so coming back to Leads draws at once, a reload too (QA robot
 * 22a02493, 8 Nov 2026: on a slow dev, Inbound | Cold arrived after the wait
 * and pushed Leads down 52 px).
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import { raiseNotificationLines } from "../shell/update-notices";
import { readSides, type SideNumbers } from "./leads-client";

/** From the read's start: a slow network answers in about 2 s (QA robot 844,
 *  1 Nov 2026: a wait that began before sign-in had settled ran out first, and
 *  the selector arriving moved the head, a layout shift of 0.19 at 1440). */
export const SIDES_WAIT_MS = 3000;

const kept = new Map<string, SideNumbers>();
const never = () => () => undefined;
const STORE = "sx:leads-sides:";

/** The last answer kept on this device, without its bell lines (those are
 *  raised by a fresh answer only). */
function stored(keyed: string): SideNumbers | null {
  try {
    const value = JSON.parse(
      localStorage.getItem(STORE + keyed) ?? "null",
    ) as SideNumbers | null;
    return value?.inbound && value.cold ? value : null;
  } catch {
    return null;
  }
}

function store(keyed: string, value: SideNumbers) {
  try {
    const numbers: SideNumbers = { ...value };
    delete numbers.bell_lines;
    localStorage.setItem(STORE + keyed, JSON.stringify(numbers));
  } catch {
    // Storage blocked: kept for this visit only.
  }
}

/** Tests: forget the kept answers; `device` false keeps this device's, as a
 *  reload does. */
export function forgetSideNumbers(device = true) {
  kept.clear();
  if (!device) return;
  try {
    for (const key of Object.keys(localStorage))
      if (key.startsWith(STORE)) localStorage.removeItem(key);
  } catch {
    // Storage blocked: nothing was kept there.
  }
}

export function useSideNumbers({
  ready,
  scope,
  keyed,
  version,
}: {
  /** Signed in with a role: the numbers can be asked for. */
  ready: boolean;
  scope: "mine" | "team";
  /** Whose numbers (person, workspace, scope): another key asks afresh. */
  keyed: string;
  /** Read again when the page refreshes. */
  version: number;
}): { numbers: SideNumbers | null; settled: boolean } {
  const [got, setGot] = useState<{ key: string; value: SideNumbers } | null>(
    () => {
      const value = kept.get(keyed);
      return value ? { key: keyed, value } : null;
    },
  );
  const [gaveUp, setGaveUp] = useState<string | null>(null);
  // A reload: this device's last answer, once the page is hydrated (the
  // server never sees it) and before it is drawn, until the fresh one comes.
  const hydrated = useSyncExternalStore(
    never,
    () => true,
    () => false,
  );
  const [looked, setLooked] = useState<string | null>(null);
  if (hydrated && looked !== keyed) {
    setLooked(keyed);
    const value = kept.has(keyed) ? null : stored(keyed);
    if (value) setGot({ key: keyed, value });
  }
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    readSides(scope, controller.signal)
      .then((value) => {
        kept.set(keyed, value);
        store(keyed, value);
        // A "<name> is your lead now" line lands with the page, in the same
        // commit as the draw this answer lets through; the bell's own first
        // read (at 3 s) then finds it shown (QA robot 10572d93, 2 Nov 2026:
        // the docked line arrived late and pushed Leads down 52 px).
        raiseNotificationLines(value.bell_lines ?? []);
        setGot({ key: keyed, value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setGaveUp(keyed);
      });
    return () => controller.abort();
  }, [ready, scope, keyed, version]);
  const numbers = got?.key === keyed ? got.value : (kept.get(keyed) ?? null);
  useEffect(() => {
    if (!ready || numbers) return;
    const timer = window.setTimeout(() => setGaveUp(keyed), SIDES_WAIT_MS);
    return () => window.clearTimeout(timer);
  }, [ready, numbers, keyed]);
  return { numbers, settled: !ready || numbers !== null || gaveUp === keyed };
}
