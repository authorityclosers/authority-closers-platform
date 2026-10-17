"use client";

/**
 * Touch gestures that make the lead lists feel like an app (UX study, 17 Oct):
 * swipe a row right to call or left to message, hold it for more, and pull the
 * page down to refresh. Only fingers count; a mouse keeps plain clicks (and a
 * right-click opens the same menu as a long-press).
 *
 * Moves are written straight to the element's style, so a drag never re-renders
 * React; the decision ("swipe", "scroll" or "hold") is made in the first 10 px.
 */

import {
  useCallback,
  useEffect,
  useRef,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { buzz } from "./native-phone";

const SLOP = 10;
const HOLD_MS = 480;
const SWIPE_MIN = 84;
const SWIPE_SHARE = 0.26;
const PULL_TRIGGER = 64;
const PULL_MAX = 96;

/** Where a drag of `dx` ends up: free to the trigger, then a soft pull. */
export function swipeOffset(dx: number, width: number): number {
  const trigger = Math.max(SWIPE_MIN, width * SWIPE_SHARE);
  const sign = Math.sign(dx);
  const size = Math.abs(dx);
  return size <= trigger
    ? dx
    : sign * (trigger + Math.min(60, (size - trigger) * 0.35));
}

/** Whether letting go after `dx` fires the swipe's action. */
export function swipeFires(dx: number, width: number): boolean {
  return Math.abs(dx) >= Math.max(SWIPE_MIN, width * SWIPE_SHARE);
}

/** The pull-to-refresh distance for a finger moved `dy` down (half speed, capped). */
export function pullDistance(dy: number): number {
  return dy <= 0 ? 0 : Math.min(PULL_MAX, dy * 0.5);
}

export const PULL_READY = PULL_TRIGGER;

type RowHandlers = {
  /** Swipe right: call. */
  onSwipeRight?: () => void;
  /** Swipe left: message. */
  onSwipeLeft?: () => void;
  /** Hold, or right-click: more actions. */
  onHold?: () => void;
};

/**
 * Binds swipe and hold to a list row. `row` is the element that carries
 * data-swipe ("right"/"left" while dragging, for the coloured backing) and
 * `face` is the part that moves.
 */
export function useRowGestures(handlers: RowHandlers) {
  const row = useRef<HTMLLIElement>(null);
  const face = useRef<HTMLDivElement>(null);
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  const state = useRef<{
    id: number;
    x: number;
    y: number;
    mode: "pending" | "swipe" | "scroll" | "held";
    dx: number;
    timer: number;
    armed: boolean;
  } | null>(null);
  const swallow = useRef(false);

  const paint = (dx: number, animate: boolean) => {
    const node = face.current;
    const host = row.current;
    if (!node || !host) return;
    node.style.transition = animate
      ? "transform 220ms cubic-bezier(.2,.8,.2,1)"
      : "none";
    node.style.transform = dx ? `translate3d(${dx}px,0,0)` : "";
    host.dataset.swipe = dx > 0 ? "right" : dx < 0 ? "left" : "";
  };

  const end = useCallback(() => {
    const current = state.current;
    if (current) window.clearTimeout(current.timer);
    state.current = null;
  }, []);

  useEffect(() => end, [end]);

  const onPointerDown = (event: ReactPointerEvent<HTMLLIElement>) => {
    if (event.pointerType !== "touch" || !event.isPrimary) return;
    swallow.current = false;
    const timer = window.setTimeout(() => {
      const current = state.current;
      if (!current || current.mode !== "pending" || !latest.current.onHold)
        return;
      current.mode = "held";
      swallow.current = true;
      buzz("press");
      latest.current.onHold();
    }, HOLD_MS);
    state.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      mode: "pending",
      dx: 0,
      timer,
      armed: false,
    };
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLLIElement>) => {
    const current = state.current;
    if (!current || current.id !== event.pointerId) return;
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (current.mode === "pending") {
      if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return;
      window.clearTimeout(current.timer);
      const sideways = Math.abs(dx) > Math.abs(dy) * 1.2;
      const wanted =
        dx > 0 ? latest.current.onSwipeRight : latest.current.onSwipeLeft;
      if (!sideways || !wanted) {
        current.mode = "scroll";
        return;
      }
      current.mode = "swipe";
      swallow.current = true;
      row.current?.setPointerCapture?.(event.pointerId);
    }
    if (current.mode !== "swipe") return;
    const width = row.current?.offsetWidth ?? 360;
    const allowed =
      (dx > 0 && latest.current.onSwipeRight) ||
      (dx < 0 && latest.current.onSwipeLeft);
    current.dx = allowed ? dx : 0;
    paint(swipeOffset(current.dx, width), false);
    const armed = swipeFires(current.dx, width);
    if (armed !== current.armed) {
      current.armed = armed;
      if (armed) buzz("tick");
      if (row.current) row.current.dataset.armed = armed ? "true" : "";
    }
  };

  const finish = (
    event: ReactPointerEvent<HTMLLIElement>,
    cancelled: boolean,
  ) => {
    const current = state.current;
    if (!current || current.id !== event.pointerId) return;
    const width = row.current?.offsetWidth ?? 360;
    const fire =
      !cancelled && current.mode === "swipe" && swipeFires(current.dx, width);
    const dx = current.dx;
    end();
    paint(0, true);
    if (row.current) row.current.dataset.armed = "";
    if (fire) {
      (dx > 0 ? latest.current.onSwipeRight : latest.current.onSwipeLeft)?.();
    }
  };

  return {
    row,
    face,
    bind: {
      onPointerDown,
      onPointerMove,
      onPointerUp: (event: ReactPointerEvent<HTMLLIElement>) =>
        finish(event, false),
      onPointerCancel: (event: ReactPointerEvent<HTMLLIElement>) =>
        finish(event, true),
      onContextMenu: (event: ReactMouseEvent<HTMLLIElement>) => {
        if (!latest.current.onHold) return;
        event.preventDefault();
        // A long-press already opened the menu; a right-click opens it now.
        if (state.current?.mode === "held" || swallow.current) return;
        end();
        latest.current.onHold();
      },
      onClickCapture: (event: ReactMouseEvent<HTMLLIElement>) => {
        if (!swallow.current) return;
        swallow.current = false;
        event.preventDefault();
        event.stopPropagation();
      },
    },
  };
}

/**
 * Pull the page down at its top to refresh. Returns a callback ref for the
 * area that listens (it can appear after a skeleton) and a ref for the round
 * indicator that drops in from the top.
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

    const show = (distance: number, mode: "pull" | "busy" | "idle") => {
      const node = spinner.current;
      if (!node) return;
      node.dataset.mode = mode;
      node.style.transition = mode === "pull" ? "none" : "";
      node.style.transform = `translate3d(-50%, ${distance - 44}px, 0) rotate(${distance * 3}deg)`;
      node.style.opacity =
        mode === "idle" ? "0" : String(Math.min(1, distance / PULL_TRIGGER));
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
        if (ready) buzz("tick");
      }
    };
    const onEnd = () => {
      if (!start) return;
      start = null;
      if (!ready) {
        show(0, "idle");
        return;
      }
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
