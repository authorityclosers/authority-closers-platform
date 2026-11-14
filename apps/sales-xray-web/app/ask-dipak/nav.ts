/**
 * Ask Dipak's screens live in its address (/ask-dipak?lesson=PB03), so the
 * phone's Back steps back one screen and a link can open a lesson. Moves use
 * the browser's own history (Next's router keeps its search params in step),
 * so changing screens fetches nothing.
 *
 * The breadcrumbs follow the spec's Flow F: a lesson goes back to the page it
 * was opened from; a category to Explore by topic; a featured topic, Search
 * and Saved lessons to Ask Dipak's home. When that page is the one before in
 * this visit, Back is the browser's back, so the history never loops.
 */

import { useSyncExternalStore } from "react";

export const ASK_PATH = "/ask-dipak";

export type AskView =
  | Readonly<{ kind: "home" }>
  | Readonly<{ kind: "topics" }>
  | Readonly<{ kind: "topic"; id: string }>
  | Readonly<{ kind: "category"; id: string }>
  | Readonly<{ kind: "lesson"; id: string }>
  | Readonly<{ kind: "search" }>
  | Readonly<{ kind: "saved" }>;

export const HOME: AskView = { kind: "home" };

const ID = /^[A-Za-z0-9-]{1,16}$/;

/** The screen an address's query names; anything unknown is the home. */
export function parseView(
  params: Pick<URLSearchParams, "get"> | null | undefined,
): AskView {
  if (!params) return HOME;
  const id = (key: string) => {
    const value = params.get(key);
    return value && ID.test(value) ? value : null;
  };
  const lesson = id("lesson");
  if (lesson) return { kind: "lesson", id: lesson };
  const category = id("category");
  if (category) return { kind: "category", id: category };
  const topic = id("topic");
  if (topic) return { kind: "topic", id: topic };
  const view = params.get("view");
  if (view === "topics" || view === "search" || view === "saved")
    return { kind: view };
  return HOME;
}

export function viewHref(view: AskView): string {
  switch (view.kind) {
    case "home":
      return ASK_PATH;
    case "topics":
    case "search":
    case "saved":
      return `${ASK_PATH}?view=${view.kind}`;
    case "topic":
    case "category":
    case "lesson":
      return `${ASK_PATH}?${view.kind}=${encodeURIComponent(view.id)}`;
  }
}

/** Where a screen's breadcrumb leads (spec Flow F); a lesson goes back. */
export function parentOf(view: AskView): AskView | "previous" {
  switch (view.kind) {
    case "lesson":
      return "previous";
    case "category":
      return { kind: "topics" };
    default:
      return HOME;
  }
}

export type Move = "load" | "push" | "replace" | "pop";

/** This visit's screens, oldest first, to tell a Back from a new screen. */
let trail: string[] = [];
let pending: { href: string; move: "push" | "replace" | "restart" } | null =
  null;
/** How far each screen was scrolled when the seller left it. */
const scrolled = new Map<string, number>();

/** Search's words: kept while the seller goes to a result and back. */
let words = "";
const wordListeners = new Set<() => void>();
function setWords(next: string) {
  words = next;
  wordListeners.forEach((listener) => listener());
}
function subscribeWords(listener: () => void) {
  wordListeners.add(listener);
  return () => {
    wordListeners.delete(listener);
  };
}
export function useSearchWords(): [string, (next: string) => void] {
  return [
    useSyncExternalStore(
      subscribeWords,
      () => words,
      () => "",
    ),
    setWords,
  ];
}

/** A fresh visit: the trail starts at the screen the page opened on. */
export function startTrail(href: string) {
  trail = [href];
  pending = null;
  setWords("");
}

/**
 * The address changed (our move, Back or Forward, or a tab tap): keep the
 * trail in step and say how it moved, so the screen can scroll to the top
 * or back to where it was.
 */
export function arrive(href: string): Move {
  if (pending && pending.href === href) {
    const { move } = pending;
    pending = null;
    if (move === "restart") {
      trail = [href];
      return "push";
    }
    if (move === "push") trail.push(href);
    else trail[Math.max(trail.length - 1, 0)] = href;
    return move;
  }
  pending = null;
  const at = trail.lastIndexOf(href);
  if (at >= 0 && at < trail.length - 1) {
    trail = trail.slice(0, at + 1);
    return "pop";
  }
  if (trail[trail.length - 1] !== href) trail.push(href);
  return "push";
}

export function rememberScroll(href: string, top: number) {
  scrolled.set(href, top);
}
export const scrollFor = (href: string): number => scrolled.get(href) ?? 0;

/** The screen in the address bar now, as viewHref writes it. */
export function currentHref(): string {
  if (window.location.pathname.replace(/\/$/, "") !== ASK_PATH) return "";
  return viewHref(parseView(new URLSearchParams(window.location.search)));
}

/** What the open screen does as it is left (it notes how far it was scrolled). */
let leaving: (() => void) | null = null;
export function onLeave(run: () => void): () => void {
  leaving = run;
  return () => {
    if (leaving === run) leaving = null;
  };
}

/** Opens a screen as a new step in the history; opening Search starts it empty, as the sample does. */
export function go(view: AskView) {
  const href = viewHref(view);
  if (view.kind === "search") setWords("");
  if (href === currentHref()) return;
  leaving?.();
  pending = { href, move: "push" };
  window.history.pushState(null, "", href);
}

/** Shows a screen in place of this one (a breadcrumb with nothing behind it). */
export function replace(view: AskView) {
  const href = viewHref(view);
  pending = { href, move: "replace" };
  window.history.replaceState(null, "", href);
}

/** A breadcrumb: the page before, if that is where it leads; else that page. */
export function goBack(view: AskView) {
  const parent = parentOf(view);
  const previous = trail.length >= 2 ? trail[trail.length - 2] : null;
  if (previous && (parent === "previous" || previous === viewHref(parent))) {
    window.history.back();
    return;
  }
  replace(parent === "previous" ? HOME : parent);
}

/**
 * The Ask Dipak tab tapped again: its link opens the home as a fresh start
 * (the top of the page, nothing behind it to step back to).
 */
export function restart() {
  if (currentHref() !== ASK_PATH) pending = { href: ASK_PATH, move: "restart" };
}

/** For tests: the trail as it stands. */
export const trailNow = (): readonly string[] => trail;
