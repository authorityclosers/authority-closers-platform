"use client";

/**
 * An answer is never lost (competitor teardown 3, 1 Nov 2026; Close keeps
 * the seller on the call until it is logged, Exotel's dialer moves on before
 * the answer is saved): a call of mine with nothing saved since stays first
 * in Leads' list, a card of two lines, "Finish: Asha" and "Called 4 min ago ·
 * How did it go?", until it is answered or put away with "Didn't call" (Leads
 * L1, 8 Nov 2026: as Home's Pending action, it scrolls away with the list).
 * The server says which calls wait (the desk's `unanswered`); "Didn't call" is
 * kept on this device.
 */

import { useState, useSyncExternalStore } from "react";

import { displayName } from "../display-name";
import { ago, type Unanswered } from "./leads-client";
import styles from "./leads.module.css";

const GONE = "sx-finish-put-away";

/** The calls put away with "Didn't call" on this device (Home's Pending
 *  action leaves them out too). */
export function readGone(): string[] {
  try {
    const kept = JSON.parse(localStorage.getItem(GONE) ?? "[]") as unknown;
    return Array.isArray(kept)
      ? kept.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

function keepGone(ids: string[]) {
  try {
    localStorage.setItem(GONE, JSON.stringify(ids.slice(-20)));
  } catch {
    // Private mode: put away for this page only.
  }
}

const never = () => () => undefined;

/** The newest call still waiting for its answer, as one pinned line. */
export function FinishRow({
  calls,
  onFinish,
  held = false,
  now = new Date(),
}: {
  calls: readonly Unanswered[] | null | undefined;
  /** Opens the lead on "How did the call go?". */
  onFinish: (leadId: string) => void;
  /** A lead is open: unseen, its room kept, so nothing under it moves. */
  held?: boolean;
  now?: Date;
}) {
  const hydrated = useSyncExternalStore(
    never,
    () => true,
    () => false,
  );
  const [gone, setGone] = useState<string[] | null>(null);
  if (hydrated && gone === null) setGone(readGone());
  const waiting = (calls ?? []).filter(
    (call) => !(gone ?? []).includes(call.event_id),
  );
  const call = waiting[0];
  if (!hydrated || !call) return null;
  const more = waiting.length - 1;
  return (
    <div
      className={styles.finish}
      role="status"
      data-held={held || undefined}
      aria-hidden={held || undefined}
    >
      <button
        type="button"
        className={styles.finishOpen}
        onClick={() => onFinish(call.lead_id)}
      >
        <strong>Finish: {displayName(call.name)}</strong>
        <span>
          {/* A dial the phone never showed may not have been placed (phone
              QA, 3 Nov 2026: a back-out from the dialler read "called"). */}
          {call.phone_saw === false
            ? `Dialled ${ago(call.called_at, now)} · Did you call?`
            : `Called ${ago(call.called_at, now)} · How did it go?`}
          {more > 0 ? ` · ${more} more` : ""}
        </span>
      </button>
      <button
        type="button"
        className={styles.finishAway}
        aria-label={`Didn't call ${displayName(call.name)}`}
        onClick={() => {
          const next = [...(gone ?? []), call.event_id];
          setGone(next);
          keepGone(next);
        }}
      >
        Didn&rsquo;t call
      </button>
    </div>
  );
}
