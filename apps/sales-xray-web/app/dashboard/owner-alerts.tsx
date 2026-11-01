"use client";

/**
 * Team controls' "Alert me when…" and "Daily summary" (competitor teardown 19
 * and 20, 1 Nov 2026). Three alerts are on until an owner turns them off: an
 * enquiry not called in time, a missed call not returned in 30 minutes, an
 * Interested lead with no follow-up for 7 days. A seller with no call for 45
 * minutes is offered, off. Each reaches the owners' and admins' phones and
 * opens its exact list. The day's summary goes at 7 PM to each owner or admin
 * who turns theirs on, on the days they pick, never to anyone else.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import { waCall, type Sla } from "../leads/whatsapp-client";
import {
  OwnerAlertsError,
  readOwnerAlerts,
  saveOwnerAlerts,
  sendTestSummary,
  type AlertKind,
  type OwnerAlerts,
} from "./owner-alerts-client";
import styles from "./team-controls.module.css";
import own from "./owner-alerts.module.css";

/** The switches and this person's summary days, read when the sheet opens. */
export function useOwnerAlerts(open: boolean, round: number) {
  const [view, setView] = useState<OwnerAlerts | null>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    readOwnerAlerts(controller.signal).then(setView, () => {
      // Not an owner or admin, or not here: the cards keep their own words.
    });
    return () => controller.abort();
  }, [open, round]);
  return [view, setView] as const;
}

function Toggle({
  label,
  on,
  onChange,
  disabled = false,
}: {
  label: string;
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      className={styles.toggle}
      onClick={() => onChange(!on)}
    >
      <span aria-hidden="true" />
    </button>
  );
}

const failed = (title: string, error?: unknown) =>
  notify({
    id: "owner-alerts",
    tone: "error",
    title,
    message:
      error instanceof OwnerAlertsError && error.status !== 500
        ? error.message
        : "Someone may have changed it just now. Try again.",
  });

const KIND_WORDS: Record<AlertKind, (minutes: number) => string> = {
  first_call: (minutes) => `An enquiry isn’t called in ${minutes} min`,
  missed_call: () => "A missed call isn’t returned in 30 min",
  no_follow_up: () => "An Interested lead has no follow-up for 7 days",
  seller_idle: () => "A seller makes no call for 45 min",
};

export function OwnerAlertsDetail({
  view,
  onView,
  sla,
  onSla,
}: {
  view: OwnerAlerts;
  onView: (next: OwnerAlerts) => void;
  /** The first-call target: when it is on, its own alert is the first switch. */
  sla: Sla | null;
  onSla: (next: Sla) => void;
}) {
  const [busy, setBusy] = useState(false);
  const byTarget = !!sla?.on;
  const minutes = byTarget ? sla!.minutes : view.first_call_minutes;
  const save = async (kind: AlertKind, next: boolean) => {
    setBusy(true);
    try {
      if (kind === "first_call" && byTarget && sla) {
        onSla(
          await waCall<Sla>("/sla", {
            method: "PUT",
            body: JSON.stringify({
              on: sla.on,
              minutes: sla.minutes,
              alertManagers: next,
            }),
          }),
        );
      } else {
        onView(
          await saveOwnerAlerts({
            first_call: view.first_call,
            missed_call: view.missed_call,
            no_follow_up: view.no_follow_up,
            seller_idle: view.seller_idle,
            summary_days: view.summary_days,
            [kind]: next,
          }),
        );
      }
    } catch (error) {
      failed("The alert wasn’t changed", error);
    } finally {
      setBusy(false);
    }
  };
  const on: Record<AlertKind, boolean> = {
    first_call: byTarget ? !!sla?.alertManagers : view.first_call,
    missed_call: view.missed_call,
    no_follow_up: view.no_follow_up,
    seller_idle: view.seller_idle && view.work_hours,
  };
  return (
    <div className={styles.detail}>
      {(Object.keys(KIND_WORDS) as AlertKind[]).map((kind) => {
        const label = KIND_WORDS[kind](minutes);
        const idleWithoutHours = kind === "seller_idle" && !view.work_hours;
        return (
          <div key={kind} className={styles.row}>
            <span className={own.alertText}>
              <span className={styles.rowLabel}>{label}</span>
              {idleWithoutHours ? (
                <small className={own.alertNote}>
                  Set working hours first: idle counts only inside them.
                </small>
              ) : (
                <Link
                  className={own.alertLink}
                  href={`/leads/alerts?kind=${kind}`}
                >
                  See who now
                </Link>
              )}
            </span>
            <Toggle
              label={label}
              on={on[kind]}
              disabled={busy || idleWithoutHours}
              onChange={(next) => void save(kind, next)}
            />
          </div>
        );
      })}
      {view.phones === 0 ? (
        <p className={styles.hint}>
          Alerts reach the Sales X-Ray app. Sign in to it on your phone to get
          them.
        </p>
      ) : null}
    </div>
  );
}

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WORK_WEEK = [0, 1, 2, 3, 4, 5];

export function DailySummaryDetail({
  view,
  onView,
}: {
  view: OwnerAlerts;
  onView: (next: OwnerAlerts) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const days = view.summary_days;
  const save = async (next: number[]) => {
    setBusy(true);
    try {
      onView(
        await saveOwnerAlerts({
          first_call: view.first_call,
          missed_call: view.missed_call,
          no_follow_up: view.no_follow_up,
          seller_idle: view.seller_idle,
          summary_days: [...next].sort((a, b) => a - b),
        }),
      );
    } catch (error) {
      failed("The summary wasn’t changed", error);
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    setTesting(true);
    try {
      const sent = await sendTestSummary();
      notify(
        !sent.ready
          ? {
              id: "summary-test",
              tone: "info",
              title: "Phone alerts aren’t set up here yet",
            }
          : sent.phones === 0
            ? {
                id: "summary-test",
                tone: "info",
                title: "No phone yet",
                message: "Sign in to the Sales X-Ray app on your phone first.",
              }
            : {
                id: "summary-test",
                tone: "success",
                title:
                  sent.sent > 1
                    ? `Sent to your ${sent.sent} phones`
                    : "Sent to your phone",
              },
      );
    } catch (error) {
      failed("The test didn’t go", error);
    } finally {
      setTesting(false);
    }
  };
  return (
    <div className={styles.detail}>
      <div className={styles.row}>
        <span className={styles.rowLabel}>
          Send me the day’s summary at 7 PM
        </span>
        <Toggle
          label="Send me the day’s summary at 7 PM"
          on={days.length > 0}
          disabled={busy}
          onChange={(next) => void save(next ? WORK_WEEK : [])}
        />
      </div>
      {days.length ? (
        <div className={styles.days} role="group" aria-label="Days">
          {DAY_NAMES.map((name, day) => (
            <button
              key={name}
              type="button"
              className={styles.day}
              aria-pressed={days.includes(day)}
              disabled={busy || (days.length === 1 && days.includes(day))}
              onClick={() =>
                void save(
                  days.includes(day)
                    ? days.filter((item) => item !== day)
                    : [...days, day],
                )
              }
            >
              {name}
            </button>
          ))}
        </div>
      ) : null}
      <p className={styles.hint}>
        Per seller: calls tried and connected, talk time, follow-ups done, wins
        and calls without a recording. Only you get yours.
      </p>
      <div className={own.summaryActions}>
        <button
          type="button"
          className={own.test}
          disabled={testing}
          onClick={() => void test()}
        >
          {testing ? "Sending…" : "Send a test now"}
        </button>
        <Link className={own.alertLink} href="/leads/summary">
          See today’s summary
        </Link>
      </div>
    </div>
  );
}
