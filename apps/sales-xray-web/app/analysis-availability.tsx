"use client";

import { useEffect, useState } from "react";
import { ACQUISITION, ACQUISITION_PAUSED_MESSAGE } from "./acquisition-client";

export function AnalysisAvailability({
  onChange,
}: {
  onChange?: (paused: boolean) => void;
}) {
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    async function refresh() {
      try {
        const response = await fetch(`${ACQUISITION}/availability`, {
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          signal: controller.signal,
        });
        if (!response.ok) return;
        const value: unknown = await response.json();
        if (
          !value ||
          typeof value !== "object" ||
          !("paused" in value) ||
          typeof value.paused !== "boolean" ||
          controller.signal.aborted
        )
          return;
        setPaused(value.paused);
        onChange?.(value.paused);
      } catch {
        /* Server authority still gates every start; keep the last known state. */
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [onChange]);
  return paused ? (
    <aside role="status" className="callout" aria-label="Analysis paused">
      <strong>New analysis is temporarily paused.</strong>
      <p>
        {ACQUISITION_PAUSED_MESSAGE.replace(
          "New analysis is temporarily paused. ",
          "",
        )}
      </p>
      <a href="mailto:admin@authorityclosers.com">Contact the AC team</a>
    </aside>
  ) : null;
}
