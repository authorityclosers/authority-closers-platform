"use client";

/**
 * The Leads list's reads, said in one calm corner card with Retry, as Home's
 * are (persona QA, 31 Oct 2026: "Syncing…" for ever, no error and no Retry).
 *
 * - A refresh that failed over rows already on screen: the card at once.
 * - A read still waiting after 8 s: the card, rows or not.
 * - A failed read with nothing on screen: the list's own Try again says it.
 * - Retry asks again; the card goes once the list is in.
 */

import { useEffect, useRef, useState } from "react";

import { dismissNotice, notify } from "../notice-center";

export const LIST_LOAD_NOTICE = "leads-sync";
export const LIST_SLOW_MS = 8_000;

export function useListLoadWatch({
  question,
  waiting,
  failed,
  showing,
  onRetry,
}: {
  /** What the list asks now: another question waits afresh. */
  question: string;
  /** Its answer is not in yet. */
  waiting: boolean;
  /** Its last read failed. */
  failed: boolean;
  /** Rows are on screen. */
  showing: boolean;
  onRetry: () => void;
}) {
  const [round, setRound] = useState(0);
  const [slow, setSlow] = useState<{ question: string; round: number } | null>(
    null,
  );
  useEffect(() => {
    if (!waiting) return;
    const timer = window.setTimeout(
      () => setSlow({ question, round }),
      LIST_SLOW_MS,
    );
    return () => window.clearTimeout(timer);
  }, [waiting, question, round]);
  const late = waiting && slow?.question === question && slow.round === round;
  const stuck = failed ? showing : late;
  const retry = useRef(onRetry);
  useEffect(() => {
    retry.current = onRetry;
  });
  useEffect(() => {
    if (!stuck) {
      dismissNotice(LIST_LOAD_NOTICE);
      return;
    }
    // Offline over saved rows, it says so and that they update by themselves
    // (Redmi QA, 10 Nov 2026: offline, "Couldn't load" and an inline "isn't
    // answering" said the same thing twice, and never why).
    const offline =
      typeof navigator !== "undefined" && navigator.onLine === false;
    notify({
      id: LIST_LOAD_NOTICE,
      tone: "info",
      noReport: true,
      title: offline ? "You're offline" : "Couldn't load",
      ...(offline
        ? {
            message:
              "Showing what was saved. It updates once you're back online.",
          }
        : {}),
      action: {
        label: "Retry",
        run: () => {
          dismissNotice(LIST_LOAD_NOTICE);
          setRound((count) => count + 1);
          retry.current();
        },
      },
      onDismiss: async () => undefined,
    });
  }, [stuck]);
  useEffect(() => () => dismissNotice(LIST_LOAD_NOTICE), []);
}
