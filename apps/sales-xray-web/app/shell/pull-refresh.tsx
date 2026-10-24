"use client";

/**
 * Pull a page down at its top to refresh, for any screen (owner, 24 Oct 2026:
 * "replace the ugly pull-to-refresh spinner with a subtle brand-B refresh,
 * plus a haptic"). The mark is the brand's own, small: five bars whose middle
 * one is an i (brand B, Insight). The bars rise with the pull; the phone ticks
 * once when letting go would refresh; while the page reads again the bars
 * breathe, then the mark folds away. Reduced motion: it only fades.
 *
 * The page moves down with the finger and the mark sits in the gap above it,
 * never over the page's own chips (Redmi sweep, 24 Oct 2026). Moves are
 * written straight to the styles, so a pull never re-renders
 * React. Only fingers count, at the very top of the page's scroller; a
 * sideways start, a scrolled page or an open dialog leave it alone.
 */

import { useCallback, useEffect, useRef, type RefObject } from "react";

import { buzz, inPhoneApp } from "../leads/native-phone";
import styles from "./pull-refresh.module.css";

const PULL_TRIGGER = 64;
const PULL_MAX = 96;
/** How far above the page the mark waits (its height and a little more). */
const MARK_HIDDEN = 40;
/** Half the mark's height, to centre it in the gap. */
const MARK_HALF = 14;

/** The pull-to-refresh distance for a finger moved `dy` down (half speed, capped). */
export function pullDistance(dy: number): number {
  return dy <= 0 ? 0 : Math.min(PULL_MAX, dy * 0.5);
}

export const PULL_READY = PULL_TRIGGER;

/**
 * Returns a callback ref for the area that listens (it can appear after a
 * skeleton) and a ref for the mark (PullMark) that drops in from the top.
 */
export function usePullToRefresh(onRefresh: () => Promise<unknown> | void) {
  const spinner = useRef<HTMLDivElement>(null);
  const latest = useRef(onRefresh);
  const detach = useRef<(() => void) | null>(null);
  useEffect(() => {
    latest.current = onRefresh;
  });
  useEffect(() => () => detach.current?.(), []);

  const area = useCallback((host: HTMLDivElement | null) => {
    detach.current?.();
    detach.current = null;
    if (!host) return;
    let start: { x: number; y: number; scroller: Element | null } | null = null;
    let pull = 0;
    let busy = false;
    let ready = false;
    // What moves with the finger: the page's own blocks, not anything pinned.
    let moving: HTMLElement[] = [];

    const still = () =>
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

    const show = (distance: number, mode: "pull" | "busy" | "idle") => {
      const node = spinner.current;
      if (!node) return;
      for (const block of moving) {
        block.style.transition =
          mode === "pull" || still()
            ? "none"
            : "transform var(--lx-dur-move) var(--lx-ease-move)";
        block.style.transform =
          distance > 0 ? `translate3d(0, ${distance}px, 0)` : "";
      }
      if (mode === "idle") moving = [];
      node.dataset.mode = mode;
      node.style.transition = mode === "pull" ? "none" : "";
      // In the middle of the gap the page leaves above itself.
      node.style.transform =
        mode === "idle"
          ? `translate3d(-50%, ${-MARK_HIDDEN}px, 0)`
          : `translate3d(-50%, ${distance / 2 - MARK_HALF}px, 0)`;
      node.style.opacity =
        mode === "idle" ? "0" : String(Math.min(1, distance / PULL_TRIGGER));
      node.style.setProperty(
        "--pull",
        mode === "idle" ? "0" : String(Math.min(1, distance / PULL_TRIGGER)),
      );
    };

    const scrollerOf = (target: EventTarget | null): Element | null => {
      for (
        let node = target as Element | null;
        node && node !== document.body;
        node = node.parentElement
      ) {
        const style = getComputedStyle(node);
        if (
          /(auto|scroll)/.test(style.overflowY) &&
          node.scrollHeight > node.clientHeight
        )
          return node;
      }
      return document.scrollingElement;
    };

    const onStart = (event: TouchEvent) => {
      if (busy || event.touches.length !== 1) return;
      if ((event.target as Element | null)?.closest?.("dialog")) return;
      const scroller = scrollerOf(event.target);
      if (!scroller || scroller.scrollTop > 0) return;
      const touch = event.touches[0];
      start = { x: touch.clientX, y: touch.clientY, scroller };
      moving = Array.from(host.children).filter(
        (child): child is HTMLElement =>
          child instanceof HTMLElement &&
          child !== spinner.current &&
          !/^(fixed|sticky)$/.test(getComputedStyle(child).position),
      );
      pull = 0;
      ready = false;
    };
    const onMove = (event: TouchEvent) => {
      if (!start) return;
      const touch = event.touches[0];
      const dx = touch.clientX - start.x;
      const dy = touch.clientY - start.y;
      if (
        (start.scroller?.scrollTop ?? 0) > 0 ||
        (pull === 0 && Math.abs(dx) > Math.abs(dy))
      ) {
        start = null;
        show(0, "idle");
        return;
      }
      pull = pullDistance(dy);
      if (pull > 0) show(pull, "pull");
      const nowReady = pull >= PULL_TRIGGER;
      if (nowReady !== ready) {
        ready = nowReady;
        // The phone app's haptic; a browser only buzzes on letting go.
        if (ready && inPhoneApp()) buzz("tick");
      }
    };
    const onEnd = () => {
      if (!start) return;
      start = null;
      if (!ready) {
        show(0, "idle");
        return;
      }
      if (!inPhoneApp()) buzz("tick");
      busy = true;
      show(PULL_TRIGGER, "busy");
      void Promise.resolve(latest.current())
        .catch(() => undefined)
        .finally(() => {
          busy = false;
          show(0, "idle");
        });
    };
    host.addEventListener("touchstart", onStart, { passive: true });
    host.addEventListener("touchmove", onMove, { passive: true });
    host.addEventListener("touchend", onEnd, { passive: true });
    host.addEventListener("touchcancel", onEnd, { passive: true });
    detach.current = () => {
      host.removeEventListener("touchstart", onStart);
      host.removeEventListener("touchmove", onMove);
      host.removeEventListener("touchend", onEnd);
      host.removeEventListener("touchcancel", onEnd);
    };
  }, []);

  return { area, spinner };
}

/** The mark that drops in from the top: the first child of the pulled area. */
export function PullMark({ mark }: { mark: RefObject<HTMLDivElement | null> }) {
  return (
    <div ref={mark} className={styles.mark} data-mode="idle" aria-hidden="true">
      <i />
      <i />
      <i data-dot="" />
      <i />
      <i />
    </div>
  );
}
