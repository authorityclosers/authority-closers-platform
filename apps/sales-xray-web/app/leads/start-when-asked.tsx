"use client";

import { useEffect, useRef } from "react";

/**
 * Start calling asked from outside the list (the command palette's Start
 * calling, a nudge's card) starts Call Next's round once the list is there:
 * To Call's leads one by one, each opening as the lead page. So a lead opens
 * one way, never the old "Start calling" sheet (orchestrator, 9 Nov 2026).
 * Each ask runs once: `served` lives with the list's owner, so the list
 * mounting again (a refresh) starts nothing new.
 */
export function StartWhenAsked({
  asked,
  served,
  onServed,
  onStart,
}: {
  /** How many times Start calling has been asked. */
  asked: number;
  /** How many of those have been started. */
  served: number;
  onServed: (asked: number) => void;
  onStart: () => void;
}) {
  const latest = useRef(onStart);
  useEffect(() => {
    latest.current = onStart;
  });
  useEffect(() => {
    if (asked <= served) return;
    onServed(asked);
    latest.current();
  }, [asked, served, onServed]);
  return null;
}
