/**
 * Which rows of a long list are drawn (native-feel plan, item 4, 3 Nov 2026):
 * the rows in the scroller's view and six either side, each placed at its top.
 * Each row's height is read from it once drawn (a row not drawn yet takes its
 * kind's), so rows hold at 200% text, in Devanagari and when a line wraps.
 * A 400-row fling draws about twenty rows, not 400.
 */

import type { CSSProperties } from "react";

/** Rows drawn either side of the view, ahead of a fling. */
export const OVERSCAN = 6;
/** A kind's height before a row of it is drawn: 72 dp at the usual size. */
export const ROW_ESTIMATE = 72;
/** The view before the scroller is measured, the server's first rows too. */
export const FIRST_VIEW = 900;

/** Each row's top, then the list's full height. */
export function rowTops(heights: readonly number[]): number[] {
  const tops = new Array<number>(heights.length + 1);
  tops[0] = 0;
  for (let index = 0; index < heights.length; index += 1)
    tops[index + 1] = tops[index] + heights[index];
  return tops;
}

/** The row at `y` from the list's top: the first whose bottom is below it. */
function rowAt(tops: readonly number[], y: number): number {
  let low = 0;
  let high = tops.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (tops[mid + 1] > y) high = mid;
    else low = mid + 1;
  }
  return low;
}

/**
 * The rows to draw, [start, end): those in view in a scroller `height` tall
 * and scrolled `scrollTop` from its top, where the list starts `margin` into
 * the scroller's content (the pinned head and anything above it), and
 * `overscan` more either side.
 */
export function rowWindow({
  tops,
  scrollTop,
  height,
  margin = 0,
  overscan = OVERSCAN,
}: {
  tops: readonly number[];
  scrollTop: number;
  height: number;
  margin?: number;
  overscan?: number;
}): { start: number; end: number } {
  const count = tops.length - 1;
  if (count <= 0) return { start: 0, end: 0 };
  const top = Math.max(0, scrollTop - margin);
  const bottom = Math.max(0, scrollTop - margin + height);
  return {
    start: Math.max(0, rowAt(tops, top) - overscan),
    end: Math.min(count, rowAt(tops, bottom) + 1 + overscan),
  };
}

/**
 * How far to scroll so the row at the view's top stays where it is when rows
 * change height: by how far that row's top moved. `y` is the view's top from
 * the list's top; none while the list's top is in view.
 */
export function keepInView(
  before: readonly number[],
  after: readonly number[],
  y: number,
): number {
  if (y <= 0 || before.length !== after.length || before.length < 2) return 0;
  const at = rowAt(before, y);
  return at < before.length - 1 ? after[at] - before[at] : 0;
}

/** A drawn row's place in its list (a move, so a row placed again never
 *  shifts the page's layout); none for a row outside such a list. */
export function placed(at: number | undefined): CSSProperties | undefined {
  return at === undefined
    ? undefined
    : {
        position: "absolute",
        insetInline: 0,
        top: 0,
        transform: `translateY(${at}px)`,
      };
}

/** The element the list scrolls in: the app's content area, or the page. */
export function scrollParent(node: HTMLElement): Element {
  for (let at = node.parentElement; at; at = at.parentElement) {
    const flow = getComputedStyle(at).overflowY;
    if (flow === "auto" || flow === "scroll") return at;
  }
  return document.scrollingElement ?? document.documentElement;
}
