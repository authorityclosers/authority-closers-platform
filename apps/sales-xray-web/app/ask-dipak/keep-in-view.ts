/**
 * A focused field stays in sight above the phone's keyboard (issue 215, 14 Nov
 * 2026: Ask Dipak's search box was hidden behind it). The keyboard shortens the
 * visual viewport, not the page; while the field has focus, each time the visual
 * viewport moves or resizes, the page's scroller is scrolled just enough that the
 * field sits inside what is still seen. The same reading of the visual viewport
 * as the after-call screen's Save (leads/wrap-up.tsx). Nothing changes on screen
 * without a keyboard.
 */
import { useEffect, type RefObject } from "react";

/** Room kept between the field and the keyboard's top, or the screen's top. */
const MARGIN = 16;

/**
 * How far to scroll so a box (its rect, relative to the layout viewport) lies
 * inside the visible part: positive scrolls down. 0 when it is in sight.
 */
export function inViewShift(
  box: { top: number; bottom: number },
  view: { offsetTop: number; height: number },
  margin = MARGIN,
): number {
  const top = view.offsetTop + margin;
  const bottom = view.offsetTop + view.height - margin;
  if (box.bottom > bottom) return Math.ceil(box.bottom - bottom);
  if (box.top < top) return Math.floor(box.top - top);
  return 0;
}

/** The element that scrolls a node's page: the nearest scrolling ancestor, or the window. */
function scrollerFor(node: HTMLElement): Element {
  for (let at = node.parentElement; at; at = at.parentElement) {
    const overflow = window.getComputedStyle(at).overflowY;
    if (
      (overflow === "auto" || overflow === "scroll") &&
      at.scrollHeight > at.clientHeight
    )
      return at;
  }
  return document.scrollingElement ?? document.documentElement;
}

/** Keeps the field in sight above the keyboard while it has focus. */
export function useKeepInView(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const field = ref.current;
    const view = typeof window === "undefined" ? null : window.visualViewport;
    if (!field || !view) return;
    const keep = () => {
      if (document.activeElement !== field) return;
      const shift = inViewShift(field.getBoundingClientRect(), view);
      if (shift) scrollerFor(field).scrollBy?.({ top: shift });
    };
    field.addEventListener("focus", keep);
    view.addEventListener("resize", keep);
    view.addEventListener("scroll", keep);
    return () => {
      field.removeEventListener("focus", keep);
      view.removeEventListener("resize", keep);
      view.removeEventListener("scroll", keep);
    };
  }, [ref]);
}
