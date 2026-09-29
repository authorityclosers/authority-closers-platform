"use client";

import { ArrowUp } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import styles from "./report-scroll-rail.module.css";

type Checkpoint = { id: string; label: string; y: number; active: boolean };

type Rail = {
  top: number;
  left: number;
  height: number;
  thumbTop: number;
  thumbHeight: number;
  scrolled: boolean;
  checkpoints: Checkpoint[];
};

function scrollerOf(node: HTMLElement | null): HTMLElement | null {
  for (
    let current = node?.parentElement ?? null;
    current;
    current = current.parentElement
  ) {
    const overflow = getComputedStyle(current).overflowY;
    if (overflow === "auto" || overflow === "scroll") return current;
  }
  return null;
}

/**
 * A slim position rail beside the report in place of the native scrollbar:
 * one checkpoint per visible report section (hover names it, click jumps to
 * it, the one you are reading is lit), a draggable thumb, and "back to top".
 */
export function ReportScrollRail() {
  const anchor = useRef<HTMLSpanElement>(null);
  const scroller = useRef<HTMLElement | null>(null);
  const drag = useRef<{ startY: number; startScroll: number } | null>(null);
  const [rail, setRail] = useState<Rail | null>(null);
  const [dragging, setDragging] = useState(false);

  const measure = useCallback(() => {
    const element = scroller.current;
    if (!element) return;
    const { clientHeight, scrollHeight, scrollTop } = element;
    const range = scrollHeight - clientHeight;
    if (range <= 4) {
      setRail(null);
      return;
    }
    const box = element.getBoundingClientRect();
    const height = Math.max(0, box.height - 24);
    const thumbHeight = Math.max(36, (height * clientHeight) / scrollHeight);
    const travel = height - thumbHeight;
    const progress = scrollTop / range;
    const sections = Array.from(
      element.querySelectorAll<HTMLElement>(
        "section[data-report-mode-section]",
      ),
    ).filter((section) => !section.hidden && section.offsetParent !== null);
    const offsets = sections.map(
      (section) =>
        section.getBoundingClientRect().top - box.top + element.scrollTop,
    );
    // The section whose top has passed the reading line is the current one.
    let current = -1;
    offsets.forEach((offset, index) => {
      if (offset <= scrollTop + clientHeight * 0.3) current = index;
    });
    const checkpoints =
      sections.length > 1
        ? sections.map((section, index) => ({
            id: section.dataset.reportModeSection ?? String(index),
            label:
              section.querySelector("h2")?.textContent?.trim() ||
              section.dataset.reportModeSection ||
              "Section",
            y:
              Math.min(1, Math.max(0, offsets[index] / range)) * travel +
              thumbHeight / 2,
            active: index === current,
          }))
        : [];
    setRail({
      top: box.top + 12,
      left: box.right - 14,
      height,
      thumbTop: travel * progress,
      thumbHeight,
      scrolled: scrollTop > 480,
      checkpoints,
    });
  }, []);

  useEffect(() => {
    const element = scrollerOf(anchor.current);
    scroller.current = element;
    if (!element) return;
    element.dataset.reportRail = "true";
    measure();
    const resize = new ResizeObserver(measure);
    resize.observe(element);
    if (element.firstElementChild) resize.observe(element.firstElementChild);
    // Switching views or tabs changes which sections are visible.
    const mutations = new MutationObserver(measure);
    mutations.observe(element, {
      subtree: true,
      attributes: true,
      attributeFilter: ["hidden"],
    });
    element.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    return () => {
      delete element.dataset.reportRail;
      resize.disconnect();
      mutations.disconnect();
      element.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
    };
  }, [measure]);

  function scrollToRatio(clientY: number) {
    const element = scroller.current;
    if (!element || !rail) return;
    const ratio = Math.min(1, Math.max(0, (clientY - rail.top) / rail.height));
    element.scrollTo({
      top: ratio * (element.scrollHeight - element.clientHeight),
      behavior: "smooth",
    });
  }

  function jumpTo(id: string) {
    scroller.current
      ?.querySelector<HTMLElement>(`section[data-report-mode-section="${id}"]`)
      ?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  return (
    <>
      <span ref={anchor} className={styles.anchor} aria-hidden="true" />
      {rail ? (
        <div
          className={styles.rail}
          style={{ top: rail.top, left: rail.left, height: rail.height }}
          onPointerDown={(event) => {
            if (event.target !== event.currentTarget) return;
            scrollToRatio(event.clientY);
          }}
        >
          <span
            className={styles.thumb}
            aria-hidden="true"
            data-dragging={dragging ? "true" : undefined}
            style={{
              height: rail.thumbHeight,
              transform: `translateY(${rail.thumbTop}px)`,
            }}
            onPointerDown={(event) => {
              const element = scroller.current;
              if (!element) return;
              event.currentTarget.setPointerCapture(event.pointerId);
              drag.current = {
                startY: event.clientY,
                startScroll: element.scrollTop,
              };
              setDragging(true);
            }}
            onPointerMove={(event) => {
              const element = scroller.current;
              const start = drag.current;
              if (!element || !start || !rail) return;
              const travel = rail.height - rail.thumbHeight;
              if (travel <= 0) return;
              const perPixel =
                (element.scrollHeight - element.clientHeight) / travel;
              element.scrollTop =
                start.startScroll + (event.clientY - start.startY) * perPixel;
            }}
            onPointerUp={(event) => {
              drag.current = null;
              setDragging(false);
              event.currentTarget.releasePointerCapture(event.pointerId);
            }}
          />
          {rail.checkpoints.map((checkpoint) => (
            <button
              key={checkpoint.id}
              type="button"
              className={styles.checkpoint}
              data-active={checkpoint.active ? "true" : undefined}
              style={{ top: checkpoint.y }}
              aria-label={`Go to ${checkpoint.label}`}
              aria-current={checkpoint.active ? "location" : undefined}
              onClick={() => jumpTo(checkpoint.id)}
            >
              <span className={styles.checkpointLabel}>{checkpoint.label}</span>
            </button>
          ))}
        </div>
      ) : null}
      {rail?.scrolled ? (
        <button
          type="button"
          className={styles.top}
          style={{ top: rail.top + rail.height - 128, left: rail.left - 40 }}
          aria-label="Back to the top of the report"
          onClick={() =>
            scroller.current?.scrollTo({ top: 0, behavior: "smooth" })
          }
        >
          <ArrowUp size={16} aria-hidden="true" />
        </button>
      ) : null}
    </>
  );
}
