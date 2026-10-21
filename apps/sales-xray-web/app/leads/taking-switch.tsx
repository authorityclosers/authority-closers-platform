"use client";

/**
 * "Taking new leads" (UX study item 8, 18 Oct): a seller's own switch, like
 * Privyr's duty status and TeleCRM's On leave. While it is off the lead rules
 * give them nothing new and their open leads stay with them. It is the same
 * flag a manager sets on Team ("Takes leads"). On Leads it is a small chip
 * beside the stage tabs (owner, 22 Oct: wide rows "waste space once ticked").
 */

import { useState } from "react";

import { notify } from "../notice-center";
import { LeadsError, setTaking, when } from "./leads-client";
import styles from "./leads.module.css";

export function TakingSwitch({
  initial,
  place,
  onChanged,
  pausedUntil = null,
}: {
  initial: boolean;
  place: "header" | "row" | "chip";
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
      const message =
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.";
      // The chip has no room under it: a corner card says so.
      if (place === "chip")
        notify({
          id: "taking-leads",
          tone: "error",
          title: "Taking new leads didn't change",
          message,
        });
      else setProblem(message);
    } finally {
      setBusy(false);
    }
  };

  if (place === "chip")
    return (
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Taking new leads"
        className={styles.statusChip}
        data-on={on && !pausedUntil ? "" : undefined}
        data-tone={on ? undefined : "warn"}
        disabled={busy}
        title={
          !on
            ? "New leads go to others. Your open leads stay with you. Tap to take leads again."
            : pausedUntil
              ? `Outside work hours. New leads wait until ${when(pausedUntil)}.`
              : "New leads can come to you. Tap when you are away."
        }
        onClick={() => void flip()}
      >
        <span className={styles.statusDot} aria-hidden="true" />
        {!on
          ? "Not taking leads"
          : pausedUntil
            ? "Paused, after hours"
            : "Taking leads"}
      </button>
    );

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
