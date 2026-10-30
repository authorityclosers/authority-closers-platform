"use client";

/**
 * Team: who has set up call capture, and why not (owner, 30 Oct 2026: "the
 * organisation owner sees who hasn't set it up"). Owners, admins and managers;
 * the sellers who still need it come first. A seller's line never shows a phone
 * number, only the phone's model.
 */

import { useEffect, useState } from "react";

import {
  readCaptureTeam,
  type CaptureTeamRow,
  type CaptureTeamState,
} from "../capture-setup/capture-setup-client";
import own from "../capture-setup/capture-setup.module.css";
import { named } from "../capture-setup/product-name";
import { PersonDisplayName } from "./people/person-display-name";
import styles from "./seats.module.css";

const BADGE: Record<CaptureTeamState, string> = {
  set_up: "Set up",
  phone_pending: "Phone not set up",
  declined: "Said not now",
  turned_off: "Turned off",
  consent_changed: "Asked again",
  not_started: "Not set up",
};

function day(at: string | null): string | null {
  if (!at) return null;
  const moment = new Date(at);
  return Number.isNaN(moment.getTime())
    ? null
    : moment.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        timeZone: "Asia/Kolkata",
      });
}

/** The one line under a seller's name. */
export function captureLine(row: CaptureTeamRow): string {
  const on = day(row.at);
  switch (row.state) {
    case "set_up":
      return [row.phone, on ? `since ${on}` : null].filter(Boolean).join(" · ");
    case "phone_pending":
      return "Agreed, but hasn't opened the app on a phone yet";
    case "declined":
      return on ? `Said not now on ${on}. Asked again daily.` : "Said not now";
    case "turned_off":
      return on
        ? `Turned call capture off on ${on}`
        : "Turned call capture off";
    case "consent_changed":
      return "The terms changed: needs to agree again";
    case "not_started":
      return "Sees the setup the next time they open Sales X-Ray";
  }
}

export function CaptureSetupPanel() {
  const [rows, setRows] = useState<CaptureTeamRow[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    readCaptureTeam(controller.signal).then(setRows, () => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => controller.abort();
  }, []);

  if (failed || (rows && !rows.length)) return null;
  const missing = rows?.filter((row) => row.state !== "set_up").length ?? 0;
  return (
    <section className={styles.section} aria-labelledby="org-capture-setup">
      <div className={styles.head}>
        <h2 id="org-capture-setup" className={styles.title}>
          Call capture
        </h2>
        <span className={styles.summary}>
          {!rows
            ? "Checking…"
            : missing
              ? `${missing} of ${rows.length} not set up`
              : "Everyone is set up"}
        </span>
      </div>
      <div className={styles.card} data-list="">
        {!rows ? (
          <span className={styles.skeletonLine} />
        ) : (
          <ul className={own.team} aria-label="Call capture, not set up first">
            {rows.map((row) => (
              <li key={row.person_id}>
                <span>
                  <strong>
                    <PersonDisplayName name={row.name} />
                  </strong>
                  <small>{named(captureLine(row))}</small>
                </span>
                <span className={own.badge} data-state={row.state}>
                  {BADGE[row.state]}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
