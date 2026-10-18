"use client";

/**
 * "Taking new leads" (UX study item 8, 18 Oct): a seller's own switch, like
 * Privyr's duty status and TeleCRM's On leave. While it is off the lead rules
 * give them nothing new and their open leads stay with them. It is the same
 * flag a manager sets on Team ("Takes leads"). Desktop: in the Leads header.
 * Phones: a slim row under the next call.
 */

import { useState } from "react";

import { LeadsError, setTaking, when } from "./leads-client";
import styles from "./leads.module.css";

export function TakingSwitch({
  initial,
  place,
  onChanged,
  pausedUntil = null,
}: {
  initial: boolean;
  place: "header" | "row";
  onChanged?: () => void;
  /** Outside the team's work hours, new leads wait until this time. */
  pausedUntil?: string | null;
}) {
  const [on, setOn] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const flip = async () => {
    const next = !on;
    setBusy(true);
    setProblem(null);
    setOn(next);
    try {
      const me = await setTaking(next);
      setOn(me.taking_leads ?? next);
      onChanged?.();
    } catch (reason) {
      setOn(!next);
      setProblem(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.taking} data-place={place}>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        className={styles.takingSwitch}
        disabled={busy}
        title={
          on
            ? "New leads can come to you. Switch off when you are away."
            : "New leads go to others. Your open leads stay with you."
        }
        onClick={() => void flip()}
      >
        <span className={styles.takingTrack} aria-hidden="true">
          <span />
        </span>
        <span className={styles.takingLabel}>
          <strong>{on ? "Taking new leads" : "Not taking new leads"}</strong>
          {place === "row" ? (
            <small>
              {!on
                ? "New leads go to others. Your open leads stay with you."
                : pausedUntil
                  ? `Outside work hours. New leads wait until ${when(pausedUntil)}.`
                  : "New leads can come to you"}
            </small>
          ) : null}
        </span>
      </button>
      {problem ? (
        <p className={styles.error} role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
