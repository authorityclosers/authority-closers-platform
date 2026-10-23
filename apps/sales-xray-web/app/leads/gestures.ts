"use client";

/**
 * Touch gestures that make the lead lists feel like an app (UX study, 17 Oct):
 * swipe a row right to call or left to message, hold it for more, and pull the
 * page down to refresh (shell/pull-refresh.tsx, for every screen since 24 Oct
 * 2026). Only fingers count; a mouse keeps plain clicks (and a
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

export {
  PULL_READY,
  pullDistance,
  usePullToRefresh,
} from "../shell/pull-refresh";

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
