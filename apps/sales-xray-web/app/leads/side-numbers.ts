"use client";

/**
 * Inbound and Cold numbers for the Leads header's selector (Dipak's handoff,
 * items 05-06 and 44-45). The page waits for them before it draws (persona QA,
 * 31 Oct 2026: the selector arriving seconds late pushed Search aside, a layout
 * jump of 0.07 at 1440), at most SIDES_WAIT_MS from when they can be asked
 * for; the last answer per person and workspace is kept, so coming back to
 * Leads draws at once.
 */

import { useEffect, useState } from "react";

import { raiseNotificationLines } from "../shell/update-notices";
import { readSides, type SideNumbers } from "./leads-client";

/** From the read's start: a slow network answers in about 2 s (QA robot 844,
 *  1 Nov 2026: a wait that began before sign-in had settled ran out first, and
 *  the selector arriving moved the head, a layout shift of 0.19 at 1440). */
export const SIDES_WAIT_MS = 3000;

const kept = new Map<string, SideNumbers>();

/** Tests: forget the kept answers. */
export function forgetSideNumbers() {
  kept.clear();
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
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    readSides(scope, controller.signal)
      .then((value) => {
        kept.set(keyed, value);
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
