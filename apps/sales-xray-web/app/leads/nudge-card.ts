"use client";

/**
 * The nudge, in the app (owner program, 25 Oct 2026, section 3; Lead OS's
 * nudges): opened from a nudge's alert (its link carries ?nudge=1), Leads
 * shows the nudge's words as the urgent centre card, once, with Start calling.
 * The phone's own alert plays the sound; this is what the seller sees inside.
 */

import { useEffect, useRef } from "react";

import { raiseAlert } from "../ui/alerts";
import { readNudge } from "./team-engine-client";

export const NUDGE_PARAM = "nudge";

export function useNudgeCard(start: (() => void) | null) {
  const latest = useRef(start);
  useEffect(() => {
    latest.current = start;
  });
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get(NUDGE_PARAM) !== "1") return;
    const controller = new AbortController();
    readNudge(controller.signal)
      .then((words) => {
        if (controller.signal.aborted) return;
        // Once: a refresh or Back doesn't raise it again.
        params.delete(NUDGE_PARAM);
        const query = params.toString();
        window.history.replaceState(
          window.history.state,
          "",
          `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
        );
        raiseAlert({
          id: "nudge",
          level: "urgent",
          title: words.title,
          message: words.body,
          action: { label: "Start calling", run: () => latest.current?.() },
          laterLabel: "In a minute",
        });
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
}
