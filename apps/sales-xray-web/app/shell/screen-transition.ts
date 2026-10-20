"use client";

/**
 * Moving between screens (owner, 20 Oct: "this gap between loading should be
 * highly animated and made in such nice way … so that its smooth").
 *
 * A press on a tab or a rail icon answers at once: the frame swaps the page
 * area for the next screen's outline (route-loading.tsx) and slides it in a
 * little in the direction of travel (right for a place further along the
 * tabs or a step deeper, left for back; a rise on wide screens), while the
 * rail, bars and tab bar stay still and their highlight glides across
 * (useGlide). The router fetches the screen meanwhile; when it arrives it
 * takes the outline's place, and the content fills in.
 *
 * No view transition: its overlay takes every pointer event while it runs,
 * so a transition started on the press swallowed the click that followed
 * (the tap never navigated). The page area is animated directly instead;
 * while the outline stands in, the page underneath is hidden, so a moving
 * page area carries no fixed bars with it.
 *
 * Reduce motion gets a short dissolve and no slide. Moves the app makes
 * itself (router.push, Back) fade the page area: opacity only, because a
 * transform there would carry the page's fixed bars (the call player).
 */
import { flushSync } from "react-dom";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

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

/** Asks the frame to show the next screen's outline now. */
export const SCREEN_GOING_EVENT = "sx:screen-going";
/** Asks the frame to give the page back: a press that never became a tap. */
export const SCREEN_BACK_EVENT = "sx:screen-back";

/** How long an outline may stand in before the old screen comes back. */
export const SCREEN_GIVE_UP_MS = 12_000;
/** A press shows its outline at once; with no click by then, it lets go. */
export const SCREEN_PRESS_HOLD_MS = 1_200;

type Going = { to: string; move: ScreenMove };

const reducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
const wide = () => window.matchMedia?.("(min-width: 900px)").matches === true;

const EASE_OUT = "cubic-bezier(0.22, 1, 0.36, 1)";

/** The spring from the tokens where the browser takes linear() curves. */
function spring(element: HTMLElement) {
  return (
    getComputedStyle(element).getPropertyValue("--sx-spring").trim() || EASE_OUT
  );
}

function animate(
  element: HTMLElement,
  frames: Keyframe[],
  options: KeyframeAnimationOptions,
) {
  if (typeof element.animate !== "function") return;
  try {
    element.animate(frames, options).finished.catch(() => undefined);
  } catch {
    element
      .animate(frames, { ...options, easing: EASE_OUT })
      .finished.catch(() => undefined);
  }
}

/**
 * Moves to `to`: the frame shows its outline at once and `navigate` asks
 * the router for it. Returns false when the move has no direction (same
 * place, or a page outside the app frame): the caller navigates as usual.
 */
export function moveScreen(
  navigate: () => void,
  from: string,
  to: string,
): boolean {
  const move = screenMove(from, to);
  if (!move) return false;
  window.dispatchEvent(
    new CustomEvent<Going>(SCREEN_GOING_EVENT, { detail: { to, move } }),
  );
  navigate();
  return true;
}

let pressed: { to: string; timer: number } | null = null;

/**
 * A press began on a link to `to` (pointer down): its outline shows now, so
 * nothing waits for the click, let alone the router (orchestrator's target:
 * under 100 ms). The click that follows navigates (takePress); a press that
 * ends without one gives the page back (releasePress).
 */
export function pressScreen(from: string, to: string): boolean {
  if (pressed?.to === to) return true;
  releasePress();
  if (!moveScreen(() => {}, from, to)) return false;
  pressed = {
    to,
    timer: window.setTimeout(() => releasePress(to), SCREEN_PRESS_HOLD_MS),
  };
  return true;
}

/** The click arrived: true when its press already moved the screen. */
export function takePress(to: string): boolean {
  if (pressed?.to !== to) return false;
  window.clearTimeout(pressed.timer);
  pressed = null;
  return true;
}

/** No click came (a long press, a drag away): give the page back. */
export function releasePress(to?: string) {
  if (!pressed || (to !== undefined && pressed.to !== to)) return;
  window.clearTimeout(pressed.timer);
  const back = pressed.to;
  pressed = null;
  window.dispatchEvent(
    new CustomEvent<string>(SCREEN_BACK_EVENT, { detail: back }),
  );
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
  const [going, setGoing] = useState<{ to: string; from: string } | null>(null);
  // The address a tap moved away from: its arrival needs no second motion.
  const tappedFrom = useRef<string | null>(null);
  useEffect(() => {
    const onGoing = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail as Going | null;
      if (!detail || typeof detail.to !== "string") return;
      const from = window.location.pathname;
      tappedFrom.current = from;
      // The outline is on screen before this returns...
      flushSync(() => setGoing({ to: detail.to, from }));
      // ...and slides in; the page underneath is hidden meanwhile.
      const page = pageRef.current;
      if (!page) return;
      if (reducedMotion()) {
        animate(page, [{ opacity: 0 }, { opacity: 1 }], {
          duration: 160,
          easing: "linear",
        });
        return;
      }
      const start = wide()
        ? { opacity: 0, transform: "translateY(10px) scale(0.995)" }
        : {
            opacity: 0,
            transform: `translateX(${detail.move === "back" ? -28 : 28}px)`,
          };
      animate(page, [start, { opacity: 1, transform: "none" }], {
        duration: 280,
        easing: EASE_OUT,
      });
    };
    // A press that never became a tap: the page comes back.
    const onBack = (event: Event) => {
      const to = (event as CustomEvent<unknown>).detail;
      tappedFrom.current = null;
      setGoing((current) => (current && current.to === to ? null : current));
    };
    window.addEventListener(SCREEN_GOING_EVENT, onGoing);
    window.addEventListener(SCREEN_BACK_EVENT, onBack);
    return () => {
      window.removeEventListener(SCREEN_GOING_EVENT, onGoing);
      window.removeEventListener(SCREEN_BACK_EVENT, onBack);
    };
  }, [pageRef]);
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
    const page = pageRef.current;
    if (!page || !screenMove(from, pathname)) return;
    animate(page, [{ opacity: 0 }, { opacity: 1 }], {
      duration: reducedMotion() ? 120 : 220,
      easing: EASE_OUT,
    });
  }, [pageRef, pathname]);
  return standing;
}

/**
 * The selected tab's (or rail icon's) capsule glides from where it was to
 * where it is now, on the spring, whenever `selected` changes: a tap, Back,
 * or a move the app made. Measured, not a view transition, so it never
 * blocks a pointer. `selector` finds the visible capsule inside `container`.
 */
export function useGlide(
  container: RefObject<HTMLElement | null>,
  selector: string,
  selected: unknown,
) {
  const last = useRef<DOMRect | null>(null);
  useLayoutEffect(() => {
    const pill = container.current?.querySelector<HTMLElement>(selector);
    const now = pill?.getBoundingClientRect() ?? null;
    const before = last.current;
    last.current = now && now.width > 0 ? now : null;
    if (!pill || !now || !before || now.width === 0 || reducedMotion()) return;
    const dx = before.left - now.left;
    const dy = before.top - now.top;
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
    animate(
      pill,
      [
        {
          opacity: 1,
          transform: `translate(${dx}px, ${dy}px) scale(${before.width / now.width}, ${before.height / now.height})`,
        },
        { opacity: 1, transform: "none" },
      ],
      { duration: 420, easing: spring(pill) },
    );
  }, [container, selector, selected]);
}
