"use client";

/**
 * The organisation's pipelines for the Leads page, the lead sheet and the add and
 * import dialogs (owner, 22 Oct 2026): read once and shared, read again after a
 * minute or after Lead stages changes them. Null until read, or when the read fails
 * (every page then works as with one pipeline).
 */

import { useEffect, useState } from "react";

import { useWorkspaceAccess } from "../workspace-access";
import { readPipelines, type PipelinesView } from "./journey/journey-client";

const FRESH_MS = 60_000;
const cached = new Map<string, { at: number; view: PipelinesView }>();
const pending = new Map<string, Promise<PipelinesView>>();
let revision = 0;

/** Lead stages changed the pipelines: the next reader asks again. */
export function forgetPipelines() {
  cached.clear();
  pending.clear();
  revision++;
}

export function usePipelines(enabled = true): PipelinesView | null {
  const access = useWorkspaceAccess();
  const context = access?.context;
  const scope = context
    ? `${context.personId}:${context.sessionId}:${context.tenantId}`
    : "standalone";
  const ready = enabled && (!access || access.status === "ready");
  const [loaded, setLoaded] = useState<{
    scope: string;
    view: PipelinesView;
  } | null>(null);
  useEffect(() => {
    if (!ready) return;
    const known = cached.get(scope);
    if (known && Date.now() - known.at < FRESH_MS) return;
    let live = true;
    const askedAt = revision;
    let request = pending.get(scope);
    if (!request) {
      request = readPipelines();
      pending.set(scope, request);
    }
    const asked = request;
    void asked
      .then(
        (next) => {
          if (askedAt !== revision) return;
          cached.set(scope, { at: Date.now(), view: next });
          if (live) setLoaded({ scope, view: next });
        },
        () => undefined,
      )
      .finally(() => {
        if (pending.get(scope) === asked) pending.delete(scope);
      });
    return () => {
      live = false;
    };
  }, [ready, scope]);
  if (!ready) return null;
  const known = cached.get(scope);
  return loaded?.scope === scope ? loaded.view : (known?.view ?? null);
}

/** Two or more pipelines: only then do pages offer a choice. */
export const several = (view: PipelinesView | null): view is PipelinesView =>
  (view?.pipelines.length ?? 0) > 1;
