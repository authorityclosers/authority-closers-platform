"use client";

/**
 * Saved views on Leads (the ease-of-use wave, 22 Oct 2026): a stage, a pipeline, whose
 * leads and a search, saved under a name and back in one tap. Kept on this device for
 * now (client-side first, as ranked); the address carries the same four, so a view is
 * also a link that can be bookmarked or shared.
 */

import { useCallback, useMemo, useSyncExternalStore } from "react";

import type { ListMore } from "./leads-client";
import type { Scope } from "./list-view";

export type ViewSpec = {
  /** "open" or a stage kind. */
  stage: string;
  /** One pipeline; none: every pipeline. */
  pipeline: string | null;
  who: Scope;
  /** Search words; empty: no search. */
  q: string;
  /** Sort and the other filters (owner, 24 Oct 2026). */
  more?: ListMore;
};

export type SavedView = ViewSpec & { id: string; name: string };

export const VIEWS_LIMIT = 12;
export const NAME_LIMIT = 40;

const STORE = "sx.leads.views.v1";
const CHANGED = "sx-saved-views";
const SCOPES: ReadonlySet<string> = new Set(["mine", "team", "unassigned"]);

/** Whose leads, from the address (`who=`); anything else: the default. */
export const asScope = (value: string | null): Scope | null =>
  value && SCOPES.has(value) ? (value as Scope) : null;

const storeKey = (owner: string) => `${STORE}:${owner}`;

function isView(value: unknown): value is SavedView {
  if (!value || typeof value !== "object") return false;
  const view = value as Record<string, unknown>;
  return (
    typeof view.id === "string" &&
    typeof view.name === "string" &&
    !!view.name.trim() &&
    typeof view.stage === "string" &&
    (view.pipeline === null || typeof view.pipeline === "string") &&
    typeof view.who === "string" &&
    SCOPES.has(view.who) &&
    typeof view.q === "string"
  );
}

/** The views kept as text; anything unreadable is dropped, never thrown. */
export function parseViews(raw: string): SavedView[] {
  if (!raw) return [];
  try {
    const list: unknown = JSON.parse(raw);
    return Array.isArray(list) ? list.filter(isView).slice(0, VIEWS_LIMIT) : [];
  } catch {
    return [];
  }
}

function readRaw(owner: string): string {
  try {
    return window.localStorage.getItem(storeKey(owner)) ?? "";
  } catch {
    return "";
  }
}

/** False when this browser keeps nothing (a private window, blocked storage). */
export function writeViews(owner: string, views: SavedView[]): boolean {
  try {
    window.localStorage.setItem(
      storeKey(owner),
      JSON.stringify(views.slice(0, VIEWS_LIMIT)),
    );
    return true;
  } catch {
    return false;
  } finally {
    window.dispatchEvent(new Event(CHANGED));
  }
}

function subscribe(change: () => void) {
  window.addEventListener("storage", change);
  window.addEventListener(CHANGED, change);
  return () => {
    window.removeEventListener("storage", change);
    window.removeEventListener(CHANGED, change);
  };
}

/** One person's saved views in one organisation (`owner` is "person:tenant"). */
export function useSavedViews(owner: string) {
  const raw = useSyncExternalStore(
    subscribe,
    () => readRaw(owner),
    () => "",
  );
  const views = useMemo(() => parseViews(raw), [raw]);
  const save = useCallback(
    (next: SavedView[]) => writeViews(owner, next),
    [owner],
  );
  return [views, save] as const;
}

const words = (q: string) => q.trim().toLowerCase();

export function sameView(a: ViewSpec, b: ViewSpec): boolean {
  return (
    a.stage === b.stage &&
    (a.pipeline ?? null) === (b.pipeline ?? null) &&
    a.who === b.who &&
    words(a.q) === words(b.q)
  );
}

export function findView(views: SavedView[], spec: ViewSpec): SavedView | null {
  return views.find((view) => sameView(view, spec)) ?? null;
}

/** Save `spec` as `name`; a view of the same name is replaced where it stood. */
export function withView(
  views: SavedView[],
  spec: ViewSpec,
  name: string,
  id: string,
): SavedView[] {
  const clean = name.trim().slice(0, NAME_LIMIT);
  const view: SavedView = {
    id,
    name: clean,
    stage: spec.stage,
    pipeline: spec.pipeline ?? null,
    who: spec.who,
    q: spec.q.trim(),
  };
  const same = views.findIndex(
    (item) => item.name.toLowerCase() === clean.toLowerCase(),
  );
  if (same >= 0)
    return views.map((item, index) => (index === same ? view : item));
  return [...views, view].slice(0, VIEWS_LIMIT);
}

export const withoutView = (views: SavedView[], id: string) =>
  views.filter((view) => view.id !== id);
