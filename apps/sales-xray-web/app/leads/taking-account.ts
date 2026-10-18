"use client";

/**
 * "Taking new leads" in the account sheet (UX study item 8 leftover): the same
 * switch as on the desk, reachable from every page. It reads the seller's
 * state only while the sheet is open in an organisation; a workspace without
 * Leads (or a failed read) shows no row.
 */

import { useCallback, useEffect, useState } from "react";

import { readMe, setTaking, type Desk } from "./leads-client";

export type TakingAccount = {
  taking: boolean;
  /** Outside work hours with the pause on: new leads wait until then. */
  pausedUntil: string | null;
  busy: boolean;
  toggle: () => void;
};

export function useTakingLeads(enabled: boolean): TakingAccount | null {
  const [me, setMe] = useState<Desk["me"] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    readMe(controller.signal)
      .then(setMe)
      .catch(() => setMe(null));
    return () => controller.abort();
  }, [enabled]);

  const toggle = useCallback(() => {
    if (!me || busy) return;
    const next = !(me.taking_leads !== false);
    setBusy(true);
    setMe({ ...me, taking_leads: next });
    setTaking(next)
      .then((saved) => setMe({ ...me, ...saved }))
      .catch(() => setMe(me))
      .finally(() => setBusy(false));
  }, [me, busy]);

  if (!enabled || !me) return null;
  return {
    taking: me.taking_leads !== false,
    pausedUntil: me.paused_until ?? null,
    busy,
    toggle,
  };
}
