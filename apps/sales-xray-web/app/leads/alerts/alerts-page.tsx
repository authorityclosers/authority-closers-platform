"use client";

/**
 * /leads/alerts?kind=…: what an owner alert is about, now (competitor teardown
 * 19, 1 Nov 2026: each alert opens its exact list). Enquiries not called in
 * time, missed calls not returned, Interested leads with no follow-up, sellers
 * with no call for 45 minutes; the longest waiting first. A lead opens on
 * Leads, a seller on their People page. Owners and admins only.
 */

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import {
  ALERT_KINDS,
  OwnerAlertsError,
  readAlertList,
  type AlertKind,
  type AlertList,
} from "../../dashboard/owner-alerts-client";
import { displayName } from "../../display-name";
import { SignedOutWelcome } from "../../shell/signed-out-welcome";
import { PageHeader, Segmented, SkeletonRow } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import { handOverLead } from "../lead-handoff";
import styles from "./alerts.module.css";

// One word each, so four fit one line at 360 px; the heading below says it in full.
const TABS: Record<AlertKind, string> = {
  first_call: "Waiting",
  missed_call: "Missed",
  no_follow_up: "Quiet",
  seller_idle: "Idle",
};

const kindFrom = (value: string | null): AlertKind =>
  ALERT_KINDS.find((kind) => kind === value) ?? "missed_call";

const CLOCK = new Intl.DateTimeFormat("en-IN", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});

/** "4:30 pm" today, "28 Oct" before. */
function sinceWords(iso: string, now = Date.now()): string {
  const at = new Date(iso);
  const day = (time: number) =>
    new Date(time).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  return day(at.getTime()) === day(now) ? CLOCK.format(at) : DAY.format(at);
}

const LINE: Record<AlertKind, string> = {
  first_call: "Came in",
  missed_call: "Called",
  no_follow_up: "Last spoken to",
  seller_idle: "Last call",
};

export function AlertsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <PageHeader title="Alerts" titleInBar />
      {Array.from({ length: 6 }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </AcquisitionShell>
  );
}

type Read =
  | { state: "loading" }
  | { state: "ready"; list: AlertList }
  | { state: "denied" }
  | { state: "failed" };

export function AlertsView({ initialKind }: { initialKind: AlertKind }) {
  const router = useRouter();
  const [kind, setKind] = useState<AlertKind>(initialKind);
  const [round, setRound] = useState(0);
  // An answer belongs to the kind and try it was read for; any other shows
  // as loading, so a switch never shows the last kind's rows.
  const asked = `${kind}:${round}`;
  const [answer, setAnswer] = useState<{ asked: string; read: Read } | null>(
    null,
  );
  const read: Read =
    answer?.asked === asked ? answer.read : { state: "loading" };
  useEffect(() => {
    const controller = new AbortController();
    readAlertList(kind, controller.signal).then(
      (list) => setAnswer({ asked, read: { state: "ready", list } }),
      (error) => {
        if (controller.signal.aborted) return;
        setAnswer({
          asked,
          read:
            error instanceof OwnerAlertsError && error.status === 403
              ? { state: "denied" }
              : { state: "failed" },
        });
      },
    );
    return () => controller.abort();
  }, [asked, kind]);
  const choose = (next: AlertKind) => {
    setKind(next);
    window.history.replaceState(null, "", `/leads/alerts?kind=${next}`);
  };
  return (
    <div className={styles.page}>
      <Segmented<AlertKind>
        label="Alert"
        items={ALERT_KINDS.map((key) => ({ key, label: TABS[key] }))}
        value={kind}
        onChange={choose}
      />
      {read.state === "loading" ? (
        <div aria-busy="true">
          {Array.from({ length: 4 }, (_, index) => (
            <SkeletonRow key={index} />
          ))}
        </div>
      ) : read.state === "denied" ? (
        <p className={styles.empty}>Only owners and admins see alerts.</p>
      ) : read.state === "failed" ? (
        <div className={styles.empty}>
          <p>The list didn’t load.</p>
          <button
            type="button"
            className={styles.retry}
            onClick={() => setRound((value) => value + 1)}
          >
            Try again
          </button>
        </div>
      ) : (
        <>
          <h2 className={styles.title}>{read.list.title}</h2>
          {read.list.items.length ? (
            <ul className={styles.list}>
              {read.list.items.map((item) => {
                const name = displayName(item.name);
                const line = [
                  item.seller ? displayName(item.seller) : null,
                  `${LINE[kind]} ${sinceWords(item.since)}`,
                ]
                  .filter(Boolean)
                  .join(" · ");
                const body = (
                  <>
                    <span className={styles.text}>
                      <strong>{name}</strong>
                      <small>{line}</small>
                    </span>
                    <ChevronRight size={16} aria-hidden="true" />
                  </>
                );
                return (
                  <li key={item.lead_id ?? item.person_id ?? name}>
                    {item.lead_id ? (
                      <button
                        type="button"
                        onClick={() => {
                          handOverLead(item.lead_id!);
                          router.push("/leads");
                        }}
                      >
                        {body}
                      </button>
                    ) : (
                      <Link
                        href={`/organisation/people/${encodeURIComponent(item.person_id ?? "")}`}
                      >
                        {body}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className={styles.empty}>
              <p>Nothing here right now.</p>
              <Link className={styles.retry} href="/leads">
                Open Leads
              </Link>
            </div>
          )}
          {read.list.more ? (
            <p className={styles.more}>And {read.list.more} more.</p>
          ) : null}
        </>
      )}
    </div>
  );
}

export function AlertsRoute() {
  const access = useWorkspaceAccess();
  const kind = kindFrom(useSearchParams().get("kind"));
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <AlertsSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="leads"
      >
        <SignedOutWelcome
          title="Sign in to see your alerts"
          text="What needs your eye on the team's leads, as it happens."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="leads">
      <PageHeader
        title="Alerts"
        titleInBar
        back={{ href: "/leads", label: "Leads" }}
      />
      <AlertsView
        key={`${access.context?.personId}:${access.context?.tenantId}`}
        initialKind={kind}
      />
    </AcquisitionShell>
  );
}
