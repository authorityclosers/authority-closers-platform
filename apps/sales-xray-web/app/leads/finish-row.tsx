"use client";

/**
 * An answer is never lost (competitor teardown 3, 1 Nov 2026; Close keeps
 * the seller on the call until it is logged, Exotel's dialer moves on before
 * the answer is saved): a call of mine with nothing saved since stays pinned
 * at the top of Leads, "Finish: Asha · called 4 min ago · How did it go?",
 * until it is answered or put away with "Didn't call". The server says which
 * calls wait (the desk's `unanswered`); "Didn't call" is kept on this device.
 */

import { X } from "lucide-react";
import { useState, useSyncExternalStore } from "react";

import { displayName } from "../display-name";
import { ago, type Unanswered } from "./leads-client";
import styles from "./leads.module.css";

const GONE = "sx-finish-put-away";

function readGone(): string[] {
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
  now = new Date(),
}: {
  calls: readonly Unanswered[] | null | undefined;
  /** Opens the lead on "How did the call go?". */
  onFinish: (leadId: string) => void;
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
    <div className={styles.finish} role="status">
      <button
        type="button"
        className={styles.finishOpen}
        onClick={() => onFinish(call.lead_id)}
      >
        <strong>Finish: {displayName(call.name)}</strong>
        <span>
          {`called ${ago(call.called_at, now)} · How did it go?`}
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
        <X size={16} aria-hidden="true" />
        Didn&rsquo;t call
      </button>
    </div>
  );
}
