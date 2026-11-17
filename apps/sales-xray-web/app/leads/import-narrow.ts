"use client";

import { useSyncExternalStore } from "react";

/** Below the import's computer layout (900 px): the phone's flow (lead import I2-C). */
export const NARROW_QUERY = "(max-width: 899.98px)";

function subscribe(change: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const list = window.matchMedia(NARROW_QUERY);
  list.addEventListener?.("change", change);
  return () => list.removeEventListener?.("change", change);
}

const read = () =>
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia(NARROW_QUERY).matches
    : false;

/** The import is on a phone-sized screen. */
export function useNarrow(): boolean {
  return useSyncExternalStore(subscribe, read, () => false);
}
