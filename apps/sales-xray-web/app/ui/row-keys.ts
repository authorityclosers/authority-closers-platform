"use client";

/**
 * Keys for a list on a computer (slice 9 of the new map, owner, 22 Oct 2026),
 * as Superhuman and Linear do it:
 *   J or ↓   the next row          K or ↑   the previous row
 *   Enter/E  open it               C        its call step ("Call <name>")
 *   L        log how its call went
 * C never dials by itself: it opens the same step a tap on Call opens.
 *
 * A row marks itself `data-row-key="<id>"` (and stays reachable by Tab or is
 * given tabindex -1 here). Keys are left alone while someone types, with
 * Ctrl, ⌘ or Alt held, while an overlay is open, on touch screens, and when
 * the list is not on screen.
 *
 *   const list = useRef<HTMLUListElement>(null);
 *   useRowKeys(list, { open: openLead, call: callLead, log: logCall });
 */

import { useEffect, useRef, type RefObject } from "react";

export type RowKeyActions = {
  open?: (id: string) => void;
  call?: (id: string) => void;
  log?: (id: string) => void;
};

const TYPING =
  "input, textarea, select, [contenteditable=''], [contenteditable='true']";

/** Which step a key asks for, or null when the key is not ours. */
export function rowKeyStep(
  key: string,
): "next" | "previous" | "open" | "call" | "log" | null {
  switch (key) {
    case "j":
    case "J":
    case "ArrowDown":
      return "next";
    case "k":
    case "K":
    case "ArrowUp":
      return "previous";
    case "Enter":
    case "e":
    case "E":
      return "open";
    case "c":
    case "C":
      return "call";
    case "l":
    case "L":
      return "log";
    default:
      return null;
  }
}

export function useRowKeys(
  list: RefObject<HTMLElement | null>,
  actions: RowKeyActions,
  enabled = true,
) {
  // The latest actions, without re-binding the listener on every render.
  const latest = useRef(actions);
  useEffect(() => {
    latest.current = actions;
  });

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const onKeyDown = (event: KeyboardEvent) => {
      const root = list.current;
      const step = rowKeyStep(event.key);
      if (!root || !step || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (window.matchMedia?.("(pointer: coarse)").matches) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest(TYPING)) return;
      if (document.querySelector("dialog[open]")) return;
      if (!root.isConnected || root.getClientRects().length === 0) return;
      const rows = [...root.querySelectorAll<HTMLElement>("[data-row-key]")];
      if (!rows.length) return;
      const here = target?.closest<HTMLElement>("[data-row-key]");
      const at = here && root.contains(here) ? rows.indexOf(here) : -1;
      if (step === "next" || step === "previous") {
        // Arrow keys belong to whatever has focus outside the list.
        if (at < 0 && event.key.startsWith("Arrow") && target !== document.body)
          return;
        const next =
          at < 0
            ? step === "next"
              ? 0
              : rows.length - 1
            : Math.min(
                rows.length - 1,
                Math.max(0, at + (step === "next" ? 1 : -1)),
              );
        const row = rows[next];
        if (!row.hasAttribute("tabindex") && row.tabIndex < 0)
          row.setAttribute("tabindex", "-1");
        row.focus();
        row.scrollIntoView?.({ block: "nearest" });
        event.preventDefault();
        return;
      }
      if (at < 0) return;
      const id = rows[at].dataset.rowKey!;
      const run = latest.current[step];
      if (!run) return;
      event.preventDefault();
      run(id);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, list]);
}
