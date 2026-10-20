"use client";

/**
 * Moving between screens (owner, 20 Oct: "this gap between loading should be
 * highly animated and made in such nice way … so that its smooth").
 *
 * A tap on a tab or a rail icon answers at once: the frame swaps the page
 * area for the next screen's outline (route-loading.tsx) inside a view
 * transition, so the page area fades through with a short slide in the
 * direction of travel (right for a place further along the tabs or a step
 * deeper, left for back) while the rail, bars and tab bar stay still. The
 * router fetches the screen meanwhile; when it arrives it takes the
 * outline's place, and the content fills in.
 *
 * Reduce motion gets a short dissolve and no slide. Browsers without view
 * transitions still get the outline at once. Moves the app makes itself
 * (router.push, Back) get a fade of the page area: opacity only, because a
 * transform on the page area would carry the page's fixed bars (the call
 * player) along with it.
 */
import { flushSync } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

export type ScreenMove = "forward" | "back";

/**
 * The places, left to right as the tab bar and rail list them. A page under
 * a place (a call under Calls, a person under Organisation) is a step
 * deeper; Settings' sections are one place.
 */
const PLACES = [
  "/dashboard",
  "/leads",
  "/chats",
  "/analysis/new",
  "/analysis/calls",
  "/prospects",
  "/coaching",
  "/organisation/insights",
  "/organisation",
  "/review",
  "/settings",
  "/account",
] as const;

const SAME_PLACE: Readonly<Record<string, string>> = {
  "/": "/dashboard",
  "/analysis": "/analysis/calls",
  "/calls": "/analysis/calls",
};

type Place = { index: number; depth: number };

export function placeOf(pathname: string | null): Place | null {
  if (!pathname) return null;
  const trimmed = pathname.replace(/\/$/, "") || "/";
  const route = SAME_PLACE[trimmed] ?? trimmed;
  for (let index = 0; index < PLACES.length; index += 1) {
    const root = PLACES[index];
    if (route !== root && !route.startsWith(`${root}/`)) continue;
    const depth =
      root === "/settings"
        ? 0
        : route.slice(root.length).split("/").filter(Boolean).length;
    return { index, depth };
  }
  return null;
}

/** Which way the screen moves between two addresses; null: it stays. */
export function screenMove(
  from: string | null,
  to: string | null,
): ScreenMove | null {
  const a = placeOf(from);
  const b = placeOf(to);
  if (!a || !b) return null;
  if (a.index === b.index)
    return a.depth === b.depth ? null : b.depth > a.depth ? "forward" : "back";
  return b.index > a.index ? "forward" : "back";
}

type ViewTransition = { finished: Promise<void> };
type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => ViewTransition;
};

/** Asks the frame to show the next screen's outline now. */
export const SCREEN_GOING_EVENT = "sx:screen-going";

/** How long an outline may stand in before the old screen comes back. */
export const SCREEN_GIVE_UP_MS = 12_000;

const reducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

let moves = 0;

/**
 * Moves to `to`: the frame shows its outline at once (inside a view
 * transition where the browser has them) and `navigate` asks the router
 * for it. Returns false when the move has no direction (same place, or a
 * page outside the app frame): the caller navigates as usual.
 */
export function moveScreen(
  navigate: () => void,
  from: string,
  to: string,
): boolean {
  const move = screenMove(from, to);
  if (!move) return false;
  const standIn = () =>
    window.dispatchEvent(
      new CustomEvent<string>(SCREEN_GOING_EVENT, { detail: to }),
    );
  const doc = document as ViewTransitionDocument;
  if (typeof doc.startViewTransition !== "function") {
    standIn();
    navigate();
    return true;
  }
  const root = document.documentElement;
  const token = (moves += 1);
  root.dataset.sxMove = reducedMotion() ? "fade" : move;
  try {
    const transition = doc.startViewTransition.call(doc, () => {
      standIn();
      navigate();
    });
    void transition.finished
      .catch(() => undefined)
      .then(() => {
        if (token === moves) delete root.dataset.sxMove;
      });
  } catch {
    delete root.dataset.sxMove;
    standIn();
    navigate();
  }
  return true;
}

/**
 * The frame's half. Returns the address whose outline stands in for the
 * page right now (null: the page itself shows). The outline goes as soon
 * as the router draws any new address; a move that never arrives gives up
 * after SCREEN_GIVE_UP_MS. Moves made without a tap (router.push, Back)
 * fade the page area in.
 */
export function useScreenMotion(
  pageRef: RefObject<HTMLElement | null>,
  pathname: string | null,
): string | null {
  const [going, setGoing] = useState<{ to: string; from: string } | null>(
    null,
  );
  // The address a tap moved away from: its arrival needs no second motion.
  const tappedFrom = useRef<string | null>(null);
  useEffect(() => {
    const onGoing = (event: Event) => {
      const to = (event as CustomEvent<unknown>).detail;
      if (typeof to !== "string") return;
      const from = window.location.pathname;
      tappedFrom.current = from;
      // Drawn before the view transition takes its "after" picture.
      flushSync(() => setGoing({ to, from }));
    };
    window.addEventListener(SCREEN_GOING_EVENT, onGoing);
    return () => window.removeEventListener(SCREEN_GOING_EVENT, onGoing);
  }, []);
  // Any new address ends the stand-in, wherever the router went.
  if (going !== null && going.from !== pathname) setGoing(null);
  const standing = going !== null && going.from === pathname ? going.to : null;
  useEffect(() => {
    if (!standing) return;
    const timer = window.setTimeout(() => {
      tappedFrom.current = null;
      setGoing(null);
    }, SCREEN_GIVE_UP_MS);
    return () => window.clearTimeout(timer);
  }, [standing]);

  const shown = useRef(pathname);
  useLayoutEffect(() => {
    const from = shown.current;
    shown.current = pathname;
    if (from === pathname) return;
    // The outline already moved the screen; the page simply takes its place.
    if (tappedFrom.current === from) {
      tappedFrom.current = null;
      return;
    }
    if (document.documentElement.dataset.sxMove) return;
    const page = pageRef.current;
    if (!screenMove(from, pathname) || typeof page?.animate !== "function")
      return;
    page.animate([{ opacity: 0 }, { opacity: 1 }], {
      duration: reducedMotion() ? 120 : 220,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
    });
  }, [pageRef, pathname]);
  return standing;
}
