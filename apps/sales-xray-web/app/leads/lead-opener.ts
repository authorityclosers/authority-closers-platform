"use client";

import { useSyncExternalStore } from "react";

import { CALLS_PAGE_NAME } from "../calls-page-name";

/**
 * The page that opened the lead showing on Leads, while it shows and until its
 * Back has stepped there (Redmi QA batch 6, 13 Nov 2026: a call opened from
 * Calls lit the Leads tab, and the lead's Back read "Back to Leads"). Its path
 * lights its own tab; its name is the lead's Back. In memory only.
 */
export type LeadOpener = { path: string; name: string };

// The pages whose Back returns there, by the name their page shows (the
// calls page's own name, "Reports" since the owner's 13 Nov 2026 word).
const NAMES: readonly (readonly [string, string])[] = [
  ["/analysis/calls", CALLS_PAGE_NAME],
  ["/calls", CALLS_PAGE_NAME],
];

/** The opener for a page's path, or null for a page Back doesn't return to. */
export function openerAt(path: string | null | undefined): LeadOpener | null {
  if (!path) return null;
  const hit = NAMES.find(
    ([root]) => path === root || path.startsWith(`${root}/`),
  );
  return hit ? { path, name: hit[1] } : null;
}

let opener: LeadOpener | null = null;
const listeners = new Set<() => void>();

export function setLeadOpener(next: LeadOpener | null) {
  if (opener?.path === next?.path && opener?.name === next?.name) return;
  opener = next;
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export function useLeadOpener(): LeadOpener | null {
  return useSyncExternalStore(
    subscribe,
    () => opener,
    () => null,
  );
}
