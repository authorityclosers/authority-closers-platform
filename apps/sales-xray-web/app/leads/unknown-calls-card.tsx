"use client";

/**
 * "Save as a lead?" (Salestrail row, after item 5). Inside the phone app, a
 * real conversation on the work SIM with a number that isn't one of the
 * seller's leads, or their missed call, is kept on the phone for a week. This
 * card lists the newest few: Save opens Add lead with the number filled in,
 * and only then does the number reach Sales Xray; Not a lead stops asking.
 */

import { UserPlus } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../ui/kit";
import { clockTime } from "./phone-call-text";
import { displayPhone, when } from "./leads-client";
import {
  ignoreNumber,
  inPhoneApp,
  onPhoneSignal,
  unknownCalls,
  type UnknownCall,
} from "./native-phone";
import styles from "./leads.module.css";

const SHOWN = 3;

/** "3:12 · today 10:42 AM", "Missed · today 10:42 AM", plus "· 2 calls". */
export function unknownLine(call: UnknownCall, now: Date = new Date()): string {
  const what =
    call.direction === "missed"
      ? "Missed"
      : `${call.direction === "incoming" ? "They called" : "You called"} · ${clockTime(call.seconds)}`;
  const many = call.count > 1 ? ` · ${call.count} calls` : "";
  return `${what} · ${when(new Date(call.lastMs).toISOString(), now)}${many}`;
}

export function UnknownCallsCard({
  onSave,
}: {
  /** Opens Add lead with this number. */
  onSave: (number: string) => void;
}) {
  const [calls, setCalls] = useState<UnknownCall[]>([]);

  useEffect(() => {
    if (!inPhoneApp()) return;
    let alive = true;
    const read = () =>
      void unknownCalls().then((next) => {
        if (alive) setCalls(next);
      });
    read();
    const stop = onPhoneSignal((event) => {
      if (event === "resume" || event === "calls") read();
    });
    return () => {
      alive = false;
      stop();
    };
  }, []);

  if (!calls.length) return null;

  return (
    <section className={styles.unknownCard} aria-label="Save as a lead?">
      <header>
        <UserPlus size={18} aria-hidden="true" />
        <span>
          <strong>Save as a lead?</strong>
          <small>Work calls that aren&apos;t leads stay on your phone.</small>
        </span>
      </header>
      <ul>
        {calls.slice(0, SHOWN).map((call) => (
          <li key={call.number}>
            <span>
              <strong>{displayPhone(call.number)}</strong>
              <small>{unknownLine(call)}</small>
            </span>
            <Button onClick={() => onSave(call.number)}>Save</Button>
            <Button
              variant="ghost"
              onClick={() =>
                void ignoreNumber(call.number).then((next) => setCalls(next))
              }
            >
              Not a lead
            </Button>
          </li>
        ))}
      </ul>
      {calls.length > SHOWN ? (
        <p className={styles.hint}>And {calls.length - SHOWN} more.</p>
      ) : null}
    </section>
  );
}
