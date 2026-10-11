"use client";

/**
 * Keyboard-first queue: J / ↓ and K / ↑ move between calls, Enter opens one.
 * Only while the queue has focus or nothing else does; typing in a field
 * never triggers it.
 */
import { useEffect } from "react";

export const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable ||
    ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName));

export function QueueKeys() {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        typing(event.target)
      )
        return;
      const down = event.key === "j" || event.key === "ArrowDown";
      const up = event.key === "k" || event.key === "ArrowUp";
      if (!down && !up) return;
      const links = Array.from(
        document.querySelectorAll<HTMLAnchorElement>("a[data-call-link]"),
      ).filter((link) => link.getClientRects().length > 0);
      if (!links.length) return;
      event.preventDefault();
      const at = links.indexOf(document.activeElement as HTMLAnchorElement);
      const next =
        at < 0
          ? 0
          : Math.max(0, Math.min(links.length - 1, at + (down ? 1 : -1)));
      links[next]?.focus();
      links[next]?.scrollIntoView({ block: "nearest" });
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  return null;
}
