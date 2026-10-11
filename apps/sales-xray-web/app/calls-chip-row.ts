"use client";

import { useLayoutEffect, useState, type RefObject } from "react";

/**
 * True when the Calls toolbar can't hold the status chips at full length on
 * one row beside search, rep and sort. The chips then get their own row
 * instead of being clipped behind a hidden scrollbar (owner, 11 Oct: "the
 * side scroll bar"). Measured before paint and on every resize; the need is
 * computed for the one-row layout, so the answer never flips back and forth.
 */
export function useChipsOwnRow(
  toolbar: RefObject<HTMLElement | null>,
  watch: unknown,
): boolean {
  const [ownRow, setOwnRow] = useState(false);
  useLayoutEffect(() => {
    const bar = toolbar.current;
    if (!bar || typeof ResizeObserver === "undefined") return;
    const measure = () => setOwnRow(chipsOverflow(bar));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    return () => observer.disconnect();
  }, [toolbar, watch]);
  return ownRow;
}

/** One-row width: search at its smallest, chips at full length, the rest as drawn. */
export function chipsOverflow(bar: HTMLElement): boolean {
  if (getComputedStyle(bar).display !== "flex") return false;
  const items = [...bar.children].filter(
    (item): item is HTMLElement =>
      item instanceof HTMLElement && getComputedStyle(item).display !== "none",
  );
  const chips = items.find((item) => item.hasAttribute("data-chips"));
  if (!chips) return false;
  const gap = parseFloat(getComputedStyle(bar).columnGap) || 0;
  // The chips' own length, whatever box they sit in now.
  const chipGap = parseFloat(getComputedStyle(chips).columnGap) || 0;
  const chipItems = [...chips.children].filter(
    (chip): chip is HTMLElement => chip instanceof HTMLElement,
  );
  const chipsLength =
    chipItems.reduce((sum, chip) => sum + chip.offsetWidth, 0) +
    chipGap * Math.max(0, chipItems.length - 1);
  const need = items.reduce(
    (sum, item) => {
      if (item === chips) return sum + chipsLength;
      const style = getComputedStyle(item);
      const smallest = parseFloat(style.minWidth);
      return (
        sum +
        (item.hasAttribute("data-shrinks") && smallest > 0
          ? smallest
          : item.offsetWidth)
      );
    },
    gap * (items.length - 1),
  );
  return need > bar.clientWidth + 0.5;
}
