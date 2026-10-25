"use client";

/**
 * Every tap answers at once (owner, 24 Oct 2026: taps felt slow). The app
 * hides Android's own tap highlight (styles.css), and many buttons, links and
 * rows had no pressed look, so a tap showed nothing until its work was done.
 * Now whatever is pressed dims within PRESS_DELAY_MS, as Android's own lists
 * do: not at once, so starting a scroll doesn't flash every row it touches,
 * and a quick tap still shows it for PRESS_SHOW_MS. A scroll, a cancelled
 * touch or leaving the app takes it off. The look is styles.css's
 * [data-sx-pressed].
 */
import { useEffect } from "react";

import { installFocusMode } from "./ui/focus-mode";

export const PRESS_DELAY_MS = 60;
export const PRESS_SHOW_MS = 120;
/** A finger that moves this far is scrolling, not pressing. */
const SLOP_PX = 10;

/** What a tap can press: the innermost one wins. */
export const PRESSABLE = [
  "button:not(:disabled)",
  "a[href]",
  '[role="button"]',
  '[role="tab"]',
  '[role="switch"]',
  '[role="menuitem"]',
  '[role="option"]',
  "summary",
  "label[for]",
  "[data-lead-row]",
  "[data-pressable]",
].join(", ");

export const PRESSED = "data-sx-pressed";

/** Installs the press feedback on a document; returns how to remove it. */
export function watchPresses(doc: Document): () => void {
  let held: Element | null = null;
  let start: { x: number; y: number; at: number } | null = null;
  let show: number | null = null;
  let hide: number | null = null;
  const view = doc.defaultView ?? window;

  const clear = () => {
    if (show !== null) view.clearTimeout(show);
    if (hide !== null) view.clearTimeout(hide);
    show = hide = null;
    held?.removeAttribute(PRESSED);
    held = null;
    start = null;
  };

  const onDown = (event: PointerEvent) => {
    clear();
    if (!event.isPrimary || event.button > 0) return;
    const target = event.target instanceof Element ? event.target : null;
    const pressed = target?.closest(PRESSABLE);
    if (!pressed || pressed.closest('[aria-disabled="true"]')) return;
    held = pressed;
    start = { x: event.clientX, y: event.clientY, at: Date.now() };
    show = view.setTimeout(() => {
      show = null;
      held?.setAttribute(PRESSED, "");
    }, PRESS_DELAY_MS);
  };

  const onMove = (event: PointerEvent) => {
    if (!start || !event.isPrimary) return;
    if (
      Math.abs(event.clientX - start.x) > SLOP_PX ||
      Math.abs(event.clientY - start.y) > SLOP_PX
    )
      clear();
  };

  const onUp = (event: PointerEvent) => {
    if (!held || !event.isPrimary) return;
    let left: number;
    if (show !== null) {
      // A quick tap: show it now, briefly.
      view.clearTimeout(show);
      show = null;
      held.setAttribute(PRESSED, "");
      left = PRESS_SHOW_MS;
    } else {
      const shown = Date.now() - (start?.at ?? 0) - PRESS_DELAY_MS;
      left = Math.max(PRESS_SHOW_MS - shown, 0);
    }
    hide = view.setTimeout(clear, left);
  };

  const onHidden = () => {
    if (doc.visibilityState !== "visible") clear();
  };

  const options = { capture: true, passive: true } as const;
  doc.addEventListener("pointerdown", onDown, options);
  doc.addEventListener("pointermove", onMove, options);
  doc.addEventListener("pointerup", onUp, options);
  doc.addEventListener("pointercancel", clear, options);
  doc.addEventListener("scroll", clear, options);
  doc.addEventListener("visibilitychange", onHidden);
  view.addEventListener("blur", clear);
  return () => {
    clear();
    doc.removeEventListener("pointerdown", onDown, options);
    doc.removeEventListener("pointermove", onMove, options);
    doc.removeEventListener("pointerup", onUp, options);
    doc.removeEventListener("pointercancel", clear, options);
    doc.removeEventListener("scroll", clear, options);
    doc.removeEventListener("visibilitychange", onHidden);
    view.removeEventListener("blur", clear);
  };
}

/** Mounted once, in the root layout; it also keeps focus rings for keyboards. */
export function PressFeedback() {
  useEffect(() => watchPresses(document), []);
  useEffect(() => installFocusMode(document), []);
  return null;
}
