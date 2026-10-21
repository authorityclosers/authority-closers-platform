"use client";

/**
 * Back closes the top overlay (owner, 22 Oct 2026: the menu "slides down"
 * and neither the Android back button nor the back gesture closes it).
 *
 * Every open sheet, dialog and hold menu owns one history entry above the
 * page, at the same address, marked with its depth. Back (the browser's, the
 * phone's gesture, the Android key: the app's web view goes back in history)
 * lands one entry lower, and the overlays above it close, one per press.
 * Closing an overlay any other way (X, scrim, swipe, Escape) takes its entry
 * back off, so Back never stops on a page that looks unchanged.
 *
 * All overlays share one stack, settled once per tick: a sheet that closes
 * as the next one opens (the + sheet into Add lead) hands its entry on
 * instead of popping and pushing. A link tapped inside an overlay leaves its
 * entry for the next page to cover (popping now could undo that page);
 * Back later steps over such a leftover by itself. The router's own state is
 * copied into each entry, so Next treats the pop as staying on the page.
 */

import { useEffect, useRef, useState } from "react";

export const OVERLAY_DEPTH_KEY = "sxOverlayDepth";
/** A close this soon after a link tap is that link leaving the page. */
const LEAVE_MS = 400;
/** A pop we asked for and never heard back about stops blocking after this. */
const TRAVEL_MS = 1000;

type Entry = { close: () => void };

const stack: Entry[] = [];
let scheduled = false;
let travelling = false;
let travelTimer = 0;
let leftAt = -Infinity;
let installed = false;

function stateOf(): Record<string, unknown> {
  const state: unknown = window.history.state;
  return state && typeof state === "object"
    ? (state as Record<string, unknown>)
    : {};
}

/** Overlay entries between the page's own entry and this one. */
function depthHere(): number {
  const value = stateOf()[OVERLAY_DEPTH_KEY];
  return typeof value === "number" && value > 0 ? value : 0;
}

function travel(by: number) {
  travelling = true;
  window.clearTimeout(travelTimer);
  travelTimer = window.setTimeout(() => {
    travelling = false;
    schedule();
  }, TRAVEL_MS);
  window.history.go(by);
}

function settle() {
  scheduled = false;
  if (travelling) return;
  const here = depthHere();
  const want = stack.length;
  if (want > here) {
    for (let depth = here + 1; depth <= want; depth += 1)
      window.history.pushState(
        { ...stateOf(), [OVERLAY_DEPTH_KEY]: depth },
        "",
      );
    return;
  }
  // A link is leaving from the overlay: its page takes this entry's place.
  if (want < here && performance.now() - leftAt > LEAVE_MS) travel(want - here);
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(settle);
}

function onPop() {
  if (travelling) {
    travelling = false;
    window.clearTimeout(travelTimer);
    schedule();
    return;
  }
  const here = depthHere();
  if (here < stack.length) {
    // Back: the overlays above this entry close, the top one first.
    const closing = stack.splice(here).reverse();
    for (const entry of closing) entry.close();
    return;
  }
  // An entry a link left behind (no overlay is open there): step over it.
  if (here > stack.length) window.history.back();
}

function onClick(event: MouseEvent) {
  const target = event.target;
  const link =
    target instanceof Element
      ? target.closest<HTMLAnchorElement>("a[href]")
      : null;
  if (!link || link.target === "_blank" || link.hasAttribute("download"))
    return;
  if ((link.getAttribute("href") ?? "").startsWith("#")) return;
  leftAt = performance.now();
}

function install() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("popstate", onPop);
  document.addEventListener("click", onClick, true);
  // A reload with an overlay open keeps its mark on the page's entry.
  if (depthHere() > 0 && stack.length === 0)
    window.history.replaceState({ ...stateOf(), [OVERLAY_DEPTH_KEY]: 0 }, "");
}

/**
 * Code that moves to another page from inside an overlay calls this first,
 * so closing the overlay does not pop the entry the move is about to cover.
 */
export function leavingOverlay() {
  leftAt = performance.now();
}

/** While `open`, Back calls `onClose` instead of leaving the page. */
export function useBackClose(open: boolean, onClose: () => void) {
  const latest = useRef(onClose);
  useEffect(() => {
    latest.current = onClose;
  });
  // A Back its owner refused (kept open, say for unsaved changes) arms again.
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (!open) return;
    install();
    const entry: Entry = {
      close: () => {
        latest.current();
        setRound((value) => value + 1);
      },
    };
    stack.push(entry);
    schedule();
    return () => {
      const index = stack.indexOf(entry);
      if (index >= 0) stack.splice(index, 1);
      schedule();
    };
  }, [open, round]);
}

/** Tests only: forget every overlay and listener. */
export function resetBackCloseForTests() {
  stack.splice(0);
  scheduled = false;
  travelling = false;
  window.clearTimeout(travelTimer);
  leftAt = -Infinity;
  if (installed) {
    window.removeEventListener("popstate", onPop);
    document.removeEventListener("click", onClick, true);
  }
  installed = false;
}
