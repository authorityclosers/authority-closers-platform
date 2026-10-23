"use client";

/**
 * Where the Offer Studio keeps offers for now: this browser's storage, one
 * key, shared by the studio and the catalogue's "Add to offer". Export and
 * import JSON move offers between browsers; a shared server store comes
 * next. Every read and write survives storage being blocked or full.
 */
import { useCallback, useSyncExternalStore } from "react";

import {
  EMPTY_STUDIO,
  STUDIO_VERSION,
  normalizeStudio,
  type Offer,
  type Studio,
} from "./offer-model";

export const STUDIO_KEY = "ac-offer-studio-v1";

const listeners = new Set<() => void>();
const cache = new Map<string, { raw: string | null; studio: Studio }>();

function read(key: string): Studio {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    raw = null;
  }
  const hit = cache.get(key);
  if (hit && hit.raw === raw) return hit.studio;
  let studio = EMPTY_STUDIO;
  if (raw) {
    try {
      studio = normalizeStudio(JSON.parse(raw));
    } catch {
      studio = EMPTY_STUDIO;
    }
  }
  cache.set(key, { raw, studio });
  return studio;
}

/** Saves the studio; false when the browser refused (private mode, full). */
export function writeStudio(key: string, studio: Studio): boolean {
  const raw = JSON.stringify({ ...studio, version: STUDIO_VERSION });
  let saved = true;
  try {
    window.localStorage.setItem(key, raw);
  } catch {
    saved = false;
  }
  cache.set(key, { raw: saved ? raw : (cache.get(key)?.raw ?? null), studio });
  for (const listener of listeners) listener();
  return saved;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key.startsWith("ac-offer-studio"))
      listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useStudio(key: string = STUDIO_KEY) {
  const studio = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => EMPTY_STUDIO,
  );
  const save = useCallback(
    (next: Studio | ((current: Studio) => Studio)) =>
      writeStudio(key, typeof next === "function" ? next(read(key)) : next),
    [key],
  );
  return { studio, save };
}

/** Replaces one offer, stamping its update time. */
export function withOffer(studio: Studio, offer: Offer): Studio {
  const stamped = { ...offer, updatedAt: new Date().toISOString() };
  return {
    ...studio,
    offers: studio.offers.map((o) => (o.id === offer.id ? stamped : o)),
  };
}
