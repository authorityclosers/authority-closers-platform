"use client";

/**
 * Figures that slide by themselves, one at a time, with page dots (owner,
 * 25 Oct 2026: "Calls analysed" and "Reports ready" as an auto-sliding widget,
 * Apple style). On a phone the track snaps a slide at a time and moves on every
 * 6 s; a finger, the pointer or focus inside holds it, a hidden page holds it,
 * and reduced motion turns it off. Wider screens show the slides side by side
 * and the dots go.
 */

import {
  Children,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import styles from "./slides.module.css";

const REDUCED = "(prefers-reduced-motion: reduce)";
const onReduced = (change: () => void) => {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia(REDUCED);
  query.addEventListener("change", change);
  return () => query.removeEventListener("change", change);
};
const readReduced = () =>
  typeof window.matchMedia === "function" && window.matchMedia(REDUCED).matches;

export const SLIDE_EVERY_MS = 6_000;

export function Slides({
  label,
  names,
  children,
}: {
  label: string;
  /** Each slide's name, for its dot and for screen readers. */
  names: string[];
  children: ReactNode;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  const [held, setHeld] = useState(false);
  const reduced = useSyncExternalStore(onReduced, readReduced, () => true);
  const slides = Children.toArray(children);
  const count = slides.length;

  const go = useCallback(
    (next: number) => {
      const node = track.current;
      if (!node || !node.clientWidth) return;
      node.scrollTo({
        left: next * node.clientWidth,
        behavior: reduced ? "auto" : "smooth",
      });
      setIndex(next);
    },
    [reduced],
  );

  useEffect(() => {
    if (held || reduced || count < 2) return;
    const timer = window.setInterval(() => {
      const node = track.current;
      // Side by side on a wide screen there is nothing to slide.
      if (document.hidden || !node || node.scrollWidth <= node.clientWidth + 1)
        return;
      go((Math.round(node.scrollLeft / node.clientWidth) + 1) % count);
    }, SLIDE_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [count, go, held, reduced]);

  return (
    <div
      className={styles.slides}
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") setHeld(true);
      }}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") setHeld(false);
      }}
      onTouchStart={() => setHeld(true)}
      onTouchEnd={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
    >
      <div
        ref={track}
        className={styles.track}
        role="group"
        aria-roledescription="carousel"
        aria-label={label}
        onScroll={(event) => {
          const node = event.currentTarget;
          if (node.clientWidth)
            setIndex(Math.round(node.scrollLeft / node.clientWidth));
        }}
      >
        {slides.map((slide, at) => (
          <div
            key={names[at] ?? at}
            className={styles.slide}
            role="group"
            aria-roledescription="slide"
            aria-label={`${at + 1} of ${count}: ${names[at] ?? ""}`}
          >
            {slide}
          </div>
        ))}
      </div>
      {count > 1 ? (
        <div className={styles.dots}>
          {names.map((name, at) => (
            <button
              key={name}
              type="button"
              className={styles.dot}
              aria-label={`Show ${name}`}
              aria-current={at === index ? "true" : undefined}
              onClick={() => go(at)}
            >
              <span aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
