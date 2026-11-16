"use client";

import { useEffect, useRef } from "react";

/**
 * Import asked for by the address (/leads?import=file or ?import=google): the
 * + sheet's Import leads, Settings → Lead sources → Import, Home's first run.
 *
 * Leads reads the ask when it opens; this hook also catches an ask that
 * arrives while Leads is already open (owner, 16 Nov 2026, on a laptop: the
 * + sheet's Import leads on Leads changed the address and opened nothing,
 * because the page only read it once). It calls back each time the ask
 * appears or changes, never for the ask Leads opened with.
 *
 * The ask leaves the address as soon as it is read. An open dialog owns a
 * history entry at the same address (ui/back-close), and closing it goes
 * back to the page's own entry; had that entry kept ?import=file, the next
 * Import leads would go to the address already shown and open nothing. It
 * also keeps a refresh from opening Import again.
 */
export type ImportAsk = "file" | "google";

export function importAsk(
  params: Pick<URLSearchParams, "get"> | null,
): ImportAsk | null {
  const value = params?.get("import");
  return value === "file" || value === "google" ? value : null;
}

/** Takes ?import off the current address, keeping the rest and the router's state. */
export function dropImportAsk(): void {
  const next = new URLSearchParams(window.location.search);
  if (!next.has("import")) return;
  next.delete("import");
  const query = next.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
  );
}

export function useImportAsked(
  params: Pick<URLSearchParams, "get"> | null,
  onAsk: (ask: ImportAsk) => void,
): void {
  const ask = importAsk(params);
  // The ask Leads opened with is the page's own first state, not news.
  const seen = useRef<ImportAsk | null>(ask);
  const call = useRef(onAsk);
  useEffect(() => {
    call.current = onAsk;
  });
  useEffect(() => {
    const before = seen.current;
    seen.current = ask;
    if (!ask) return;
    // Before the dialog's own history entry is pushed (settled next tick).
    dropImportAsk();
    if (ask !== before) call.current(ask);
  }, [ask]);
}
