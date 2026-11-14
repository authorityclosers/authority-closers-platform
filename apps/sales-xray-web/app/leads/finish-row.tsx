"use client";

/**
 * An answer is never lost (competitor teardown 3, 1 Nov 2026; Close keeps
 * the seller on the call until it is logged, Exotel's dialer moves on before
 * the answer is saved): a call of mine with nothing saved since stays first
 * in Leads' list, a card of two lines, "Finish: Asha" and "Called 4 min ago ·
 * How did it go?", until it is answered or put away with "Didn't call" (Leads
 * L1, 8 Nov 2026: as Home's Pending action, it scrolls away with the list).
 * The server says which calls wait (the desk's `unanswered`); "Didn't call" is
 * kept on this device and tells the server the dial was never placed. A corner
 * card says so, with Undo, as Done does (Redmi QA on production 1.57, 13 Nov
 * 2026: it said nothing and couldn't be taken back); Undo reverses it on the
 * server too, and the call counts and waits again.
 */

import { useState, useSyncExternalStore } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import {
  ago,
  LeadsError,
  markDialNotPlaced,
  undoDialNotPlaced,
  type Unanswered,
} from "./leads-client";
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

/** A call taken back from "Didn't call": off this phone's put-away list. */
function bringBack(eventId: string): string[] {
  const next = readGone().filter((id) => id !== eventId);
  keepGone(next);
  return next;
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

  // Undo: the server reverses the marking, so the call counts and waits again.
  const undo = async (eventId: string) => {
    try {
      await undoDialNotPlaced(eventId);
    } catch (reason) {
      if (!(reason instanceof LeadsError && reason.kept)) {
        notify({
          id: `dial-undo-${eventId}`,
          tone: "error",
          title: "Not undone",
          message: reason instanceof LeadsError ? reason.message : "Try again.",
        });
        return;
      }
    }
    setGone(bringBack(eventId));
  };

  const putAway = async (away: Unanswered) => {
    const next = [...(gone ?? []), away.event_id];
    setGone(next);
    keepGone(next);
    const title = `Didn't call: ${displayName(away.name)}`;
    try {
      // Not a call at all: it leaves the counts, Calls and Home's Pending
      // action everywhere, not only on this phone (Redmi QA, 13 Nov 2026).
      await markDialNotPlaced(away.event_id);
    } catch (reason) {
      if (reason instanceof LeadsError && reason.kept) {
        // Kept on this phone and sent when it is back online.
        notify({
          id: `dial-away-${away.event_id}`,
          tone: "info",
          title,
          message: reason.message,
        });
        return;
      }
      // Refused (the phone logged it, so it was placed) or failed: the call
      // waits for its answer again.
      setGone(bringBack(away.event_id));
      notify({
        id: `dial-away-failed-${away.event_id}`,
        tone: "error",
        title: "Not put away",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
      return;
    }
    notify({
      id: `dial-away-${away.event_id}`,
      tone: "success",
      title,
      message: "Not counted as a call.",
      action: { label: "Undo", run: () => void undo(away.event_id) },
      timeout: 6000,
    });
  };

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
        onClick={() => void putAway(call)}
      >
        Didn&rsquo;t call
      </button>
    </div>
  );
}
