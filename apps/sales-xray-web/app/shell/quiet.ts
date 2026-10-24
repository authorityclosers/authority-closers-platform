"use client";

/**
 * True once the page has loaded and been quiet for a moment: the frame's
 * overlays that nobody needs in the first second (the bug reporter, feedback,
 * the settings menu, the command bar) mount then, so their code stays out of
 * the start (orchestrator, 24 Oct 2026: mid-tier phones took ~4.7 s to show
 * the first screen).
 */
import { useEffect, useState } from "react";

type IdleWindow = Window & {
  requestIdleCallback?: (
    run: () => void,
    options?: { timeout: number },
  ) => number;
  cancelIdleCallback?: (handle: number) => void;
};

export const QUIET_AFTER_MS = 1_500;

export function useQuiet(after = QUIET_AFTER_MS): boolean {
  const [quiet, setQuiet] = useState(false);
  useEffect(() => {
    const win = window as IdleWindow;
    let idle: number | null = null;
    const timer = window.setTimeout(() => {
      if (win.requestIdleCallback)
        idle = win.requestIdleCallback(() => setQuiet(true), {
          timeout: 2_000,
        });
      else setQuiet(true);
    }, after);
    return () => {
      window.clearTimeout(timer);
      if (idle !== null) win.cancelIdleCallback?.(idle);
    };
  }, [after]);
  return quiet;
}
