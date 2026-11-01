"use client";

/**
 * Notifications, one place (competitor teardown 26, 1 Nov 2026; Privyr's
 * per-type alerts and test button, HubSpot's per-type switches): what reaches
 * this person's phone and when. New enquiry, Follow-up due (at the time, 15
 * minutes or an hour before), Missed follow-up, and for owners and admins Team
 * alerts and the Daily summary. Quiet hours follow the team's working hours.
 * "Send me a test notification" proves the phone hears.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  readOwnerAlerts,
  saveOwnerAlerts,
  summaryWhen,
  type OwnerAlerts,
} from "../dashboard/owner-alerts-client";
import { inPhoneApp } from "../leads/native-phone";
import { notify } from "../notice-center";
import { Panel, Skeleton } from "../ui/kit";
import {
  NotifyError,
  noPhoneWords,
  readNotify,
  saveNotify,
  testNotify,
  type DueLead,
  type NotifyPrefs,
} from "./notifications-client";
import styles from "./notification-prefs.module.css";

type Switch =
  | "new_enquiry"
  | "follow_up_due"
  | "missed_follow_up"
  | "team_alerts"
  | "quiet";

const LEADS: { minutes: DueLead; label: string }[] = [
  { minutes: 0, label: "At the time" },
  { minutes: 15, label: "15 min before" },
  { minutes: 60, label: "1 h before" },
];
const WORK_WEEK = [0, 1, 2, 3, 4, 5];

const failed = (error: unknown) =>
  notify({
    id: "notification-prefs",
    tone: "error",
    title: "That wasn’t saved",
    message:
      error instanceof NotifyError && error.status < 500
        ? error.message
        : "Check your connection and try again.",
  });

function Toggle({
  label,
  on,
  disabled,
  onChange,
}: {
  label: string;
  on: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
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

function Row({
  title,
  line,
  children,
}: {
  title: string;
  /** Words, or the row's own choices (the follow-up's timing). */
  line: ReactNode;
  children: ReactNode;
}) {
  return (
    <li className={styles.row}>
      <span className={styles.text}>
        <strong>{title}</strong>
        {typeof line === "string" ? <small>{line}</small> : line}
      </span>
      {children}
    </li>
  );
}

/** A seller's rows while the panel reads, each at its own height. */
const READING: { title: string; line: ReactNode }[] = [
  { title: "New enquiry", line: <Skeleton width={170} height={18} /> },
  {
    title: "Follow-up due",
    line: (
      <span className={styles.chips}>
        {[96, 114, 88].map((width) => (
          <Skeleton key={width} width={width} height={32} radius="pill" />
        ))}
      </span>
    ),
  },
  { title: "Missed follow-up", line: <Skeleton width={170} height={18} /> },
  {
    title: "Quiet outside working hours",
    line: <Skeleton width={170} height={18} />,
  },
];

/**
 * The panel's place while it reads: Phone & alerts drew nothing here until
 * the read answered, then the panel pushed everything below it down 471 px
 * (the test robot, 1 Nov 2026: report 853, 0.10 at 1440).
 */
function Reading() {
  return (
    <Panel title="Notifications">
      <ul className={styles.list} aria-busy="true">
        {READING.map((row) => (
          <Row key={row.title} title={row.title} line={row.line}>
            <span className={styles.bone}>
              <Skeleton width={52} height={32} radius="pill" />
            </span>
          </Row>
        ))}
      </ul>
      <div className={styles.foot}>
        <Skeleton width={232} height={44} radius="pill" />
      </div>
    </Panel>
  );
}

export function NotificationPrefs() {
  const [prefs, setPrefs] = useState<NotifyPrefs | null>(null);
  const [owner, setOwner] = useState<OwnerAlerts | null>(null);
  // No Leads in this workspace: the panel stays away.
  const [away, setAway] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  // Held from the first tap: two taps before the button greys out sent two
  // tests (the test robot, 1 Nov 2026: 14836c51).
  const sending = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    readNotify(signal).then(
      async (value) => {
        // An owner's Daily summary is read first, so the panel arrives
        // whole and never grows a row under the page (report 853).
        if (value.manager)
          await readOwnerAlerts(signal).then(setOwner, () => {
            // Without it the panel shows the rest.
          });
        if (!signal.aborted) setPrefs(value);
      },
      () => {
        // Not in a workspace with Leads: the panel stays away.
        if (!signal.aborted) setAway(true);
      },
    );
    return () => controller.abort();
  }, []);
  if (away) return null;
  if (!prefs) return <Reading />;

  const save = async (change: Partial<NotifyPrefs>) => {
    const next = { ...prefs, ...change };
    setBusy(true);
    try {
      setPrefs(
        await saveNotify({
          new_enquiry: next.new_enquiry,
          follow_up_due: next.follow_up_due,
          missed_follow_up: next.missed_follow_up,
          team_alerts: next.team_alerts,
          due_lead_minutes: next.due_lead_minutes,
          quiet: next.quiet,
        }),
      );
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  };
  const summary = async (on: boolean) => {
    if (!owner) return;
    setBusy(true);
    try {
      setOwner(
        await saveOwnerAlerts({
          first_call: owner.first_call,
          missed_call: owner.missed_call,
          no_follow_up: owner.no_follow_up,
          seller_idle: owner.seller_idle,
          summary_days: on ? WORK_WEEK : [],
        }),
      );
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    if (sending.current) return;
    sending.current = true;
    setTesting(true);
    try {
      const sent = await testNotify();
      notify(
        !sent.ready
          ? {
              id: "notification-test",
              tone: "info",
              title: "Phone alerts aren’t set up here yet",
            }
          : sent.phones === 0
            ? {
                id: "notification-test",
                tone: "info",
                title: "No phone yet",
                message: noPhoneWords(inPhoneApp()),
              }
            : {
                id: "notification-test",
                tone: "success",
                title:
                  sent.sent > 1
                    ? `Sent to your ${sent.sent} phones`
                    : "Sent to your phone",
              },
      );
    } catch (error) {
      failed(error);
    } finally {
      sending.current = false;
      setTesting(false);
    }
  };
  const flip = (key: Switch, label: string, on = prefs[key]) => (
    <Toggle
      label={label}
      on={on}
      disabled={busy}
      onChange={(next) => void save({ [key]: next })}
    />
  );

  return (
    <Panel title="Notifications">
      <ul className={styles.list}>
        <Row title="New enquiry" line="A lead given to you, at once">
          {flip("new_enquiry", "New enquiry")}
        </Row>
        <Row
          title="Follow-up due"
          line={
            prefs.follow_up_due ? (
              <span
                className={styles.chips}
                role="radiogroup"
                aria-label="When"
              >
                {LEADS.map((lead) => (
                  <button
                    key={lead.minutes}
                    type="button"
                    role="radio"
                    aria-checked={prefs.due_lead_minutes === lead.minutes}
                    className={styles.chip}
                    disabled={busy}
                    onClick={() =>
                      void save({ due_lead_minutes: lead.minutes })
                    }
                  >
                    {lead.label}
                  </button>
                ))}
              </span>
            ) : (
              "Off"
            )
          }
        >
          {flip("follow_up_due", "Follow-up due")}
        </Row>
        <Row title="Missed follow-up" line="What is late, at 12, 2, 4 and 6">
          {flip("missed_follow_up", "Missed follow-up")}
        </Row>
        {prefs.manager ? (
          <Row
            title="Team alerts"
            line="As they happen, chosen in Team controls"
          >
            {flip("team_alerts", "Team alerts")}
          </Row>
        ) : null}
        {prefs.manager && owner ? (
          <Row title="Daily summary" line={summaryWhen(owner.summary_days)}>
            <Toggle
              label="Daily summary"
              on={owner.summary_days.length > 0}
              disabled={busy}
              onChange={(next) => void summary(next)}
            />
          </Row>
        ) : null}
        <Row
          title="Quiet outside working hours"
          line={
            prefs.working_hours
              ? `Working hours: ${prefs.working_hours}. Follow-ups you set still reach you.`
              : "The team has no working hours yet, so every hour counts."
          }
        >
          {flip("quiet", "Quiet outside working hours")}
        </Row>
      </ul>
      <div className={styles.foot}>
        <button
          type="button"
          className={styles.test}
          disabled={testing}
          onClick={() => void test()}
        >
          {testing ? "Sending…" : "Send me a test notification"}
        </button>
        {prefs.phones === 0 ? (
          <small>{noPhoneWords(inPhoneApp())}</small>
        ) : null}
      </div>
    </Panel>
  );
}
