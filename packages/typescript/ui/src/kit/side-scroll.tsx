"use client";

/**
 * A row that scrolls sideways inside itself (owner bugs #43–#47, 27 Oct 2026:
 * on a phone the Connections bars stacked their labels, ran off the screen and
 * pushed every card past its edge). A scroller's automatic minimum width is 0,
 * so it never widens the page the way a bare segmented control in a grid did;
 * the chosen item comes into view; and the row fades at an edge only while
 * something sits past it.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

import styles from "./side-scroll.module.css";

/** The fades' class, for a row that scrolls on its own (the hub's tab row). */
export const sideScrollFades = styles.fades;

/**
 * Brings the item matching `selector` into view whenever `chosen` changes, and
 * gives the row's fades as data attributes while something is past an edge.
 */
export function useSideScroll<T extends HTMLElement>(
  selector: string,
  chosen: string,
) {
  const ref = useRef<T>(null);
  const [edges, setEdges] = useState({ less: false, more: false });
  useEffect(() => {
    const row = ref.current;
    if (!row) return;
    const item = row.querySelector<HTMLElement>(selector);
    // Past the edge: brought in with room to spare for the fade.
    if (item && item.offsetLeft + item.offsetWidth > row.clientWidth)
      row.scrollLeft =
        item.offsetLeft + item.offsetWidth - row.clientWidth + 32;
    const measure = () => {
      const less = row.scrollLeft > 1;
      const more = row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
      setEdges((now) =>
        now.less === less && now.more === more ? now : { less, more },
      );
    };
    const frame = requestAnimationFrame(measure);
    const resize =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    resize?.observe(row);
    row.addEventListener("scroll", measure, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      resize?.disconnect();
      row.removeEventListener("scroll", measure);
    };
  }, [selector, chosen]);
  return {
    ref,
    edges: {
      "data-less": edges.less ? "" : undefined,
      "data-more": edges.more ? "" : undefined,
    },
  };
}

/**
 * A segmented control (or any row of buttons) that keeps each label on one
 * line and scrolls inside itself where it doesn't fit; the pressed item
 * (`aria-pressed`) comes into view.
 */
export function SideScroll({
  chosen,
  className,
  children,
}: {
  /** The chosen item's key: when it changes, it comes into view. */
  chosen: string;
  className?: string;
  children: ReactNode;
}) {
  const { ref, edges } = useSideScroll<HTMLDivElement>(
    '[aria-pressed="true"]',
    chosen,
  );
  return (
    <div
      ref={ref}
      className={`${styles.row} ${styles.fades}${className ? ` ${className}` : ""}`}
      {...edges}
    >
      {children}
    </div>
  );
}
