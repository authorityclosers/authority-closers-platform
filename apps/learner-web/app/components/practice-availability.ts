"use client";

import { useEffect, useState } from "react";
import { loadPracticeNavigationAvailability } from "../lib/practice-navigation";

/** Presentation only; current canonical API admission still guards all Practice data. */
export function usePracticeNavigationAvailability(scope: string): boolean {
  const [result, setResult] = useState<{
    scope: string;
    available: boolean;
  } | null>(null);
  useEffect(() => {
    let request: AbortController | undefined;
    const refresh = () => {
      request?.abort();
      const controller = new AbortController();
      request = controller;
      void loadPracticeNavigationAvailability(controller.signal).then(
        (available) => {
          if (!controller.signal.aborted) setResult({ scope, available });
        },
      );
    };
    const visible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    refresh();
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visible);
    return () => {
      request?.abort();
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [scope]);
  return result?.scope === scope && result.available;
}
