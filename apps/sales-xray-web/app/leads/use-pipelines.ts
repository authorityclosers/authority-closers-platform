"use client";

/**
 * The organisation's pipelines for the Leads page, the lead sheet and the add and
 * import dialogs (owner, 22 Oct 2026): read once and shared, read again after a
 * minute or after Lead stages changes them. Null until read, or when the read fails
 * (every page then works as with one pipeline).
 */

import { useEffect, useState } from "react";

import { readPipelines, type PipelinesView } from "./journey/journey-client";

const FRESH_MS = 60_000;
let cached: { at: number; view: PipelinesView } | null = null;
let pending: Promise<PipelinesView> | null = null;

/** Lead stages changed the pipelines: the next reader asks again. */
export function forgetPipelines() {
  cached = null;
}

export function usePipelines(enabled = true): PipelinesView | null {
  const [view, setView] = useState<PipelinesView | null>(
    () => cached?.view ?? null,
  );
  useEffect(() => {
    if (!enabled || (cached && Date.now() - cached.at < FRESH_MS)) return;
    let live = true;
    pending ??= readPipelines().finally(() => {
      pending = null;
    });
    pending.then(
      (next) => {
        cached = { at: Date.now(), view: next };
        if (live) setView(next);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [enabled]);
  return enabled ? view : null;
}

/** Two or more pipelines: only then do pages offer a choice. */
export const several = (view: PipelinesView | null): view is PipelinesView =>
  (view?.pipelines.length ?? 0) > 1;
