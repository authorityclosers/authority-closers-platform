"use client";

import { useEffect, useState } from "react";

import type { LatestCall } from "./prospect-brief-model";
import type { ProspectCall } from "./prospects-client";
import { preloadSavedReport } from "./report-preload";

export type LatestCallState = "none" | "loading" | "ready" | "unavailable";

/** The newest call on this prospect that has a finished Report. */
export function latestAnalysedCall(calls: ProspectCall[]) {
  return (
    [...calls]
      .filter((call) => call.has_report)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null
  );
}

async function read(path: string, signal: AbortSignal) {
  const response = await fetch(path, {
    credentials: "same-origin",
    redirect: "error",
    headers: { accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new Error("latest_call_unavailable");
  return response.json();
}

/**
 * Reads the latest analysed call's Report once per prospect page, bounded by
 * the saved-report reader's own deadline. A missing or private call is an
 * honest "unavailable", never an error page.
 */
export function useLatestCallReport(calls: ProspectCall[], enabled: boolean) {
  const target = enabled ? latestAnalysedCall(calls) : null;
  const callId = target?.submission_id ?? null;
  const [loaded, setLoaded] = useState<{
    callId: string;
    latest: LatestCall | null;
  } | null>(null);
  useEffect(() => {
    if (!callId) return;
    const controller = new AbortController();
    void preloadSavedReport(callId, read, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setLoaded({
        callId,
        latest:
          result.state === "ready"
            ? {
                callId,
                report: result.result.report,
                transcript: result.result.transcript,
              }
            : null,
      });
    });
    return () => controller.abort();
  }, [callId]);
  if (!callId) return { state: "none" as const, latest: undefined };
  if (loaded?.callId !== callId)
    return { state: "loading" as const, latest: undefined };
  return loaded.latest
    ? { state: "ready" as const, latest: loaded.latest }
    : { state: "unavailable" as const, latest: undefined };
}
