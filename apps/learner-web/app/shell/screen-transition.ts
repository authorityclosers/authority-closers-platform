"use client";

import { useLayoutEffect, useRef, type RefObject } from "react";
/** Adapted from Sales X-Ray's useGlide. Never creates a view-transition overlay. */
export function useGlide(
  container: RefObject<HTMLElement | null>,
  selected: unknown,
) {
  const last = useRef<DOMRect | null>(null);
  useLayoutEffect(() => {
    const pill =
      container.current?.querySelector<HTMLElement>("[data-capsule]");
    const now = pill?.getBoundingClientRect() ?? null;
    const before = last.current;
    last.current = now && now.width > 0 ? now : null;
    if (
      !pill ||
      !now ||
      !before ||
      !now.width ||
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ||
      document.documentElement.dataset.motion === "reduced"
    )
      return;
    const dx = before.left - now.left,
      dy = before.top - now.top;
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
    const frames = [
      {
        transform: `translate(${dx}px, ${dy}px) scale(${before.width / now.width}, ${before.height / now.height})`,
      },
      { transform: "none" },
    ];
    try {
      pill
        .animate?.(frames, {
          duration: 420,
          easing:
            getComputedStyle(pill).getPropertyValue("--sx-spring").trim() ||
            "ease-out",
        })
        .finished?.catch(() => undefined);
    } catch {
      pill
        .animate?.(frames, { duration: 420, easing: "ease-out" })
        .finished?.catch(() => undefined);
    }
  }, [container, selected]);
}
