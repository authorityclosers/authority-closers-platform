"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { AcquisitionError } from "../acquisition-client";
import {
  callTime,
  DayBars,
  DayBarsSkeleton,
} from "../dashboard/dashboard-visuals";
import {
  readReceiptActivity,
  type OrgMember,
  type ReceiptActivity,
} from "./organisation-api";
import styles from "./organisation.module.css";

type State =
  | { status: "loading" }
  | { status: "off" }
  | { status: "denied" }
  | { status: "error" }
  | { status: "ready"; value: ReceiptActivity };

const plural = (count: number, word: string) =>
  `${count} ${word}${count === 1 ? "" : "s"}`;

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
}

/** "+2 on the previous 30 days"; nothing when neither window has analyses. */
function trend({
  analysedLast30Days: now,
  analysedPrevious30Days: before,
}: ReceiptActivity) {
  if (now === 0 && before === 0) return null;
  if (before === 0) return "None in the previous 30 days";
  const delta = now - before;
  return delta === 0
    ? `Same as the previous 30 days (${before})`
    : `${delta > 0 ? "+" : ""}${delta} on the previous 30 days (${before})`;
}

/**
 * Calls analysed for the whole organisation (AUT-1616), from finished-analysis
 * receipts: owners and admins only. Mount it with `key={tenantId}` so a
 * workspace switch starts empty instead of showing the old organisation.
 */
export function ReceiptActivitySection({
  members,
  onAccessLost,
}: {
  members: OrgMember[] | null;
  onAccessLost: () => void;
}) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  // The access refresh changes identity on every context update; a ref keeps
  // a 403 from re-running this read in a loop.
  const accessLost = useRef(onAccessLost);
  useEffect(() => {
    accessLost.current = onAccessLost;
  }, [onAccessLost]);

  useEffect(() => {
    const controller = new AbortController();
    readReceiptActivity(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setState(
          value === null ? { status: "off" } : { status: "ready", value },
        );
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (
          error instanceof AcquisitionError &&
          (error.status === 401 || error.status === 403)
        ) {
          setState({ status: "denied" });
          accessLost.current();
          return;
        }
        setState({ status: "error" });
      });
    return () => controller.abort();
  }, [attempt]);

  // A server without this read gets one quiet line, never a promise card.
  if (state.status === "denied") return null;
  if (state.status === "off")
    return (
      <p className={styles.quietLine}>
        Calls analysed across the organisation show here once this server has
        the latest update.
      </p>
    );

  const value = state.status === "ready" ? state.value : null;
  const change = value ? trend(value) : null;
  return (
    <section className={styles.section} aria-labelledby="org-analysed">
      <div className={styles.sectionHead}>
        <h2 id="org-analysed">
          Calls analysed
          {value ? (
            <span className={styles.count}>{value.analysedLast30Days}</span>
          ) : null}
        </h2>
        <span>{change ?? "Last 30 days, India time"}</span>
      </div>
      <div className={styles.surface}>
        {state.status === "loading" ? (
          <div className={styles.receipts} aria-label="Loading calls analysed">
            <div className={styles.receiptChart}>
              <DayBarsSkeleton />
            </div>
          </div>
        ) : state.status === "error" || value === null ? (
          <div className={styles.empty}>
            <b>Calls analysed could not be loaded</b>
            <p>The rest of this page is up to date.</p>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => {
                setState({ status: "loading" });
                setAttempt((count) => count + 1);
              }}
            >
              <RefreshCw size={14} aria-hidden="true" />
              Try again
            </button>
          </div>
        ) : (
          <div className={styles.receipts}>
            <div className={styles.receiptChart}>
              {value.analysedLast30Days === 0 ? (
                <p className={styles.receiptQuiet}>
                  No calls analysed in the last 30 days.
                </p>
              ) : (
                <DayBars days={value.days} />
              )}
            </div>
            <ReceiptPeople value={value} members={members} />
          </div>
        )}
        <p className={styles.footnote}>
          Counts finished analyses by India date, including people who have
          left, so it can differ from the saved calls above.
        </p>
      </div>
    </section>
  );
}

function ReceiptPeople({
  value,
  members,
}: {
  value: ReceiptActivity;
  members: OrgMember[] | null;
}) {
  if (value.people.length === 0)
    return (
      <p className={styles.receiptQuiet}>
        Nobody in the organisation has a finished analysis in the last 60 days.
      </p>
    );
  const emails = new Map(
    (members ?? []).map((member) => [member.personId, member.email]),
  );
  const names = new Map<string, number>();
  for (const person of value.people)
    names.set(person.name, (names.get(person.name) ?? 0) + 1);
  return (
    <div
      className={styles.receiptTable}
      role="table"
      aria-label="Calls analysed by person"
    >
      <div className={styles.receiptHead} role="row">
        <span role="columnheader">Person</span>
        <span role="columnheader" className={styles.num}>
          Calls
        </span>
        <span role="columnheader" className={styles.num}>
          Time
        </span>
        <span role="columnheader" className={styles.num}>
          Previous
        </span>
      </div>
      {value.people.map((person) => {
        const current = members !== null && emails.has(person.personId);
        const hint =
          (names.get(person.name) ?? 0) > 1
            ? current
              ? emails.get(person.personId)
              : members !== null
                ? "Former member"
                : null
            : null;
        return (
          <div
            key={person.personId}
            className={styles.receiptRow}
            role="row"
            data-quiet={person.analysed === 0 ? "" : undefined}
          >
            <span role="cell" className={styles.receiptPerson}>
              <i className={styles.avatar} aria-hidden="true">
                {initials(person.name)}
              </i>
              <span className={styles.personName}>
                <b>
                  <span className={styles.nameText}>{person.name}</span>
                </b>
                {hint ? <small>{hint}</small> : null}
              </span>
            </span>
            <span
              role="cell"
              className={styles.num}
              aria-label={
                plural(person.analysed, "call") + " in the last 30 days"
              }
            >
              {person.analysed}
            </span>
            <span role="cell" className={`${styles.num} ${styles.muted}`}>
              {callTime(person.analysedSeconds)}
            </span>
            <span
              role="cell"
              className={`${styles.num} ${styles.muted}`}
              aria-label={
                plural(person.previous, "call") + " in the previous 30 days"
              }
            >
              {person.previous}
            </span>
          </div>
        );
      })}
    </div>
  );
}
