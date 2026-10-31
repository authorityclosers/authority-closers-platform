"use client";

/**
 * Inbound and Cold numbers for the Leads header's selector (Dipak's handoff,
 * items 05-06 and 44-45). The page waits for them before it draws (persona QA,
 * 31 Oct 2026: the selector arriving seconds late pushed Search aside, a layout
 * jump of 0.07 at 1440), at most SIDES_WAIT_MS; the last answer per person and
 * workspace is kept, so coming back to Leads draws at once.
 */

import { useEffect, useState } from "react";

import { readSides, type SideNumbers } from "./leads-client";

export const SIDES_WAIT_MS = 1500;

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
        setGot({ key: keyed, value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setGaveUp(keyed);
      });
    return () => controller.abort();
  }, [ready, scope, keyed, version]);
  const numbers = got?.key === keyed ? got.value : (kept.get(keyed) ?? null);
  useEffect(() => {
    if (numbers) return;
    const timer = window.setTimeout(() => setGaveUp(keyed), SIDES_WAIT_MS);
    return () => window.clearTimeout(timer);
  }, [numbers, keyed]);
  return { numbers, settled: !ready || numbers !== null || gaveUp === keyed };
}
