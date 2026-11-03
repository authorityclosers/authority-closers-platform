import { expect, it } from "vitest";

import { OVERSCAN, keepInView, placed, rowTops, rowWindow } from "./row-window";

// Native-feel plan, item 4 (3 Nov 2026): a long Leads list draws the rows in
// view and six either side, each at its top.

it("puts each row at the sum of the heights above it, then the list's height", () => {
  expect(rowTops([72, 72, 88, 72])).toEqual([0, 72, 144, 232, 304]);
  expect(rowTops([])).toEqual([0]);
});

it("draws the rows in view and six either side", () => {
  expect(OVERSCAN).toBe(6);
  const tops = rowTops(Array.from({ length: 400 }, () => 72));
  // At the top of an 851 px view: rows 0 to 11 in sight, six more below.
  expect(rowWindow({ tops, scrollTop: 0, height: 851 })).toEqual({
    start: 0,
    end: 18,
  });
  // 7,200 px down (row 100 at the top): 94 to 117.
  expect(rowWindow({ tops, scrollTop: 7200, height: 851 })).toEqual({
    start: 94,
    end: 118,
  });
  // At the end: never past the last row.
  expect(rowWindow({ tops, scrollTop: 400 * 72, height: 851 })).toEqual({
    start: 394,
    end: 400,
  });
  // About twenty rows drawn, not 400.
  const { start, end } = rowWindow({ tops, scrollTop: 14_400, height: 851 });
  expect(end - start).toBeLessThanOrEqual(25);
});

it("counts the pinned head above the list as its scroll margin", () => {
  const tops = rowTops(Array.from({ length: 400 }, () => 72));
  // The head takes 260 px: scrolled 260 px, the list's first row is at the top.
  expect(rowWindow({ tops, scrollTop: 260, margin: 260, height: 851 })).toEqual(
    { start: 0, end: 18 },
  );
  // Scrolled 1,000 px past the head: row 13 at the top, 7 to 31 drawn.
  expect(
    rowWindow({ tops, scrollTop: 1260, margin: 260, height: 851 }),
  ).toEqual({ start: 7, end: 32 });
  // Not scrolled yet: the head takes 260 px of the view, so the list's first
  // nine rows are in sight, six more below.
  expect(rowWindow({ tops, scrollTop: 0, margin: 260, height: 851 })).toEqual({
    start: 0,
    end: 15,
  });
});

it("holds at font scale 2.0: rows read at twice the height draw fewer rows, at their tops", () => {
  // At 200% text a two-line row measures 144 px and a three-line row 176 px.
  const kinds = ["two", "three", "two", "two", "three", "two"];
  const big = { two: 144, three: 176 } as Record<string, number>;
  const tops = rowTops(kinds.map((kind) => big[kind]));
  expect(tops).toEqual([0, 144, 320, 464, 608, 784, 928]);
  const many = rowTops(Array.from({ length: 400 }, () => 144));
  // An 851 px view holds six rows at this size: six in sight, six below.
  expect(rowWindow({ tops: many, scrollTop: 0, height: 851 })).toEqual({
    start: 0,
    end: 12,
  });
  expect(rowWindow({ tops: many, scrollTop: 14_400, height: 851 })).toEqual({
    start: 94,
    end: 112,
  });
});

it("keeps the row at the view's top still when rows above it change height", () => {
  // Rows read at 72 px; scrolled to 30 px into the fifth row (y = 318).
  const before = rowTops([72, 72, 72, 72, 72, 72]);
  // The second row is drawn and reads 99 px (a line wraps): 27 px more.
  const taller = rowTops([72, 99, 72, 72, 72, 72]);
  expect(keepInView(before, taller, 318)).toBe(27);
  // A row below the view's top changing moves nothing in view.
  const below = rowTops([72, 72, 72, 72, 72, 99]);
  expect(keepInView(before, below, 318)).toBe(0);
  // At the list's top, or with the list's top still in view, no scroll.
  expect(keepInView(before, taller, 0)).toBe(0);
  expect(keepInView(before, taller, -40)).toBe(0);
});

it("places a drawn row by a move, and leaves a row outside a list alone", () => {
  expect(placed(144)).toEqual({
    position: "absolute",
    insetInline: 0,
    top: 0,
    transform: "translateY(144px)",
  });
  expect(placed(undefined)).toBeUndefined();
});
