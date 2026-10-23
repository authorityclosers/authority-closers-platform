"use client";

/**
 * Getting the next screen ready before it is asked for (owner, 20 Oct: "it
 * should be loaded intelligently beforehand understanding the user
 * movements so that its smooth").
 *
 * - Once the app is quiet after a page load, the places one tap away (the
 *   tabs and the rail) are prefetched one at a time: their code and their
 *   loading outline, so a tap shows the right screen at once.
 * - A pointer resting on a link prefetches it (Next.js does this itself
 *   only in production builds; dev is where the owner tests).
 * - Pressing a tab also starts that page's first reads (early-reads.ts),
 *   so its data is on the way before the page asks for it.
 *
 * A device asking to save data (or on 2G) gets none of the idle prefetching.
 */
import { useEffect, useRef } from "react";

import { startEarlyReads } from "../early-reads";
import { useAppRouter } from "./app-router";

/** In the order people move to them most. */
export const PREFETCH_PLACES = [
  "/leads",
  "/analysis/calls",
  "/dashboard",
  "/chats",
  "/analysis/new",
  "/prospects",
  "/coaching",
] as const;

// A link asked for again within this time is still fresh in Next's cache.
const FRESH_MS = 30_000;
const asked = new Map<string, number>();

type Router = { prefetch: (href: string) => void };

function samePage(href: string) {
  return (
    typeof window !== "undefined" &&
    href.split(/[?#]/)[0] === window.location.pathname
  );
}

/** Prefetch an app address once per FRESH_MS; with `warm`, start its reads. */
export function prefetchPlace(router: Router, href: string, warm = false) {
  if (!href.startsWith("/") || href.startsWith("//") || samePage(href)) return;
  const now = Date.now();
  if (now - (asked.get(href) ?? 0) > FRESH_MS) {
    asked.set(href, now);
    try {
      router.prefetch(href);
    } catch {
      // A prefetch is only a head start; the tap still navigates.
    }
  }
  if (warm) startEarlyReads(href.split(/[?#]/)[0]);
}

export function savingData() {
  const connection = (
    navigator as Navigator & {
      connection?: { saveData?: boolean; effectiveType?: string };
    }
  ).connection;
  return (
    connection?.saveData === true ||
    /(^|-)2g$/.test(connection?.effectiveType ?? "")
  );
}

type IdleWindow = Window & {
  requestIdleCallback?: (
    run: () => void,
    options?: { timeout: number },
  ) => number;
  cancelIdleCallback?: (handle: number) => void;
};

/**
 * The frame's idle prefetch of the places one tap away; then `warm`, for
 * the first data those places read (calls-cache.ts warmCallsList).
 */
export function usePlacePrefetch(enabled: boolean, warm?: () => void) {
  const router = useAppRouter();
  const warmRef = useRef(warm);
  useEffect(() => {
    warmRef.current = warm;
  });
  useEffect(() => {
    if (!router || !enabled || process.env.NODE_ENV === "test" || savingData())
      return;
    const win = window as IdleWindow;
    let cancelled = false;
    let idle: number | null = null;
    const whenIdle = (run: () => void) => {
      idle = win.requestIdleCallback
        ? win.requestIdleCallback(run, { timeout: 3_000 })
        : window.setTimeout(run, 300);
    };
    const queue = PREFETCH_PLACES.filter(
      (href) => Date.now() - (asked.get(href) ?? 0) > FRESH_MS,
    );
    const next = () => {
      if (cancelled) return;
      const href = queue.shift();
      if (!href) {
        warmRef.current?.();
        return;
      }
      prefetchPlace(router, href);
      whenIdle(next);
    };
    // After the page itself has settled.
    const start = window.setTimeout(() => whenIdle(next), 1_500);
    return () => {
      cancelled = true;
      window.clearTimeout(start);
      if (idle !== null) {
        if (win.cancelIdleCallback) win.cancelIdleCallback(idle);
        window.clearTimeout(idle);
      }
    };
  }, [enabled, router]);
}

/** A mouse resting on any app link prefetches it (touch: Next.js does it). */
export function useHoverPrefetch(enabled: boolean) {
  const router = useAppRouter();
  useEffect(() => {
    if (!router || !enabled || process.env.NODE_ENV === "test") return;
    let timer: number | null = null;
    const onOver = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      const link = (event.target as Element | null)?.closest?.("a[href]");
      if (!(link instanceof HTMLAnchorElement)) return;
      if (link.target && link.target !== "_self") return;
      if (link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (timer !== null) window.clearTimeout(timer);
      // A short rest, so sweeping across a list prefetches nothing.
      timer = window.setTimeout(
        () => prefetchPlace(router, url.pathname + url.search),
        80,
      );
    };
    const onOut = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    };
    document.addEventListener("pointerover", onOver, { passive: true });
    document.addEventListener("pointerout", onOut, { passive: true });
    return () => {
      onOut();
      document.removeEventListener("pointerover", onOver);
      document.removeEventListener("pointerout", onOut);
    };
  }, [enabled, router]);
}
