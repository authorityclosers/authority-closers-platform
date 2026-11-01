"use client";

/**
 * /leads/summary: today so far, per seller (competitor teardown 20, 1 Nov
 * 2026), the page the 7 PM summary opens. Calls tried and connected, talk
 * time and follow-ups done count as each seller's own Home counts them; wins
 * and calls without a recording as Performance does. Owners and admins only.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import {
  OwnerAlertsError,
  readDaySummary,
  type DaySummary,
} from "../../dashboard/owner-alerts-client";
import { displayName } from "../../display-name";
import { SignedOutWelcome } from "../../shell/signed-out-welcome";
import { PageHeader, SkeletonRow } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import styles from "../alerts/alerts.module.css";

const COUNT = new Intl.NumberFormat("en-IN");

/** "24 min", "1 h 5 min". */
export function talk(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60
    ? `${Math.floor(minutes / 60)} h ${minutes % 60} min`
    : `${minutes} min`;
}

const plural = (count: number, one: string, many: string) =>
  `${COUNT.format(count)} ${count === 1 ? one : many}`;

export function SummarySkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <PageHeader title="Today’s summary" titleInBar />
      {Array.from({ length: 6 }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </AcquisitionShell>
  );
}

type Read =
  | { state: "loading" }
  | { state: "ready"; summary: DaySummary }
  | { state: "denied" }
  | { state: "failed" };

export function SummaryView() {
  const [read, setRead] = useState<Read>({ state: "loading" });
  const [round, setRound] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    readDaySummary(controller.signal).then(
      (summary) => setRead({ state: "ready", summary }),
      (error) => {
        if (controller.signal.aborted) return;
        setRead(
          error instanceof OwnerAlertsError && error.status === 403
            ? { state: "denied" }
            : { state: "failed" },
        );
      },
    );
    return () => controller.abort();
  }, [round]);
  if (read.state === "loading")
    return (
      <div aria-busy="true">
        {Array.from({ length: 5 }, (_, index) => (
          <SkeletonRow key={index} />
        ))}
      </div>
    );
  if (read.state === "denied")
    return (
      <p className={styles.empty}>Only owners and admins see the summary.</p>
    );
  if (read.state === "failed")
    return (
      <div className={styles.empty}>
        <p>The summary didn’t load.</p>
        <button
          type="button"
          className={styles.retry}
          onClick={() => {
            setRead({ state: "loading" });
            setRound((value) => value + 1);
          }}
        >
          Try again
        </button>
      </div>
    );
  const { summary } = read;
  return (
    <div className={styles.page}>
      <div className={styles.totals} aria-label="Today, the whole team">
        <div>
          <span>Tried</span>
          <strong>{COUNT.format(summary.totals.tried)}</strong>
        </div>
        <div>
          <span>Connected</span>
          <strong>{COUNT.format(summary.totals.connected)}</strong>
        </div>
        <div>
          <span>Wins</span>
          <strong>{COUNT.format(summary.totals.wins)}</strong>
        </div>
      </div>
      {summary.sellers.length ? (
        <ul className={styles.sellers} aria-label="Each seller today">
          {summary.sellers.map((seller) => (
            <li key={seller.person_id}>
              <strong>{displayName(seller.name)}</strong>
              <span className={styles.figures}>
                <span>{plural(seller.tried, "tried", "tried")}</span>
                <span>
                  {plural(seller.connected, "connected", "connected")}
                </span>
                <span>{talk(seller.talk_seconds)} talk</span>
                <span>
                  {plural(seller.follow_ups_done, "follow-up", "follow-ups")}
                </span>
                <span>{plural(seller.wins, "win", "wins")}</span>
                {seller.no_recording ? (
                  <span data-tone="warn">
                    {plural(
                      seller.no_recording,
                      "call without a recording",
                      "calls without a recording",
                    )}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.empty}>
          <p>No sellers in this workspace yet.</p>
          <Link className={styles.retry} href="/organisation?tab=team">
            Invite your team
          </Link>
        </div>
      )}
    </div>
  );
}

export function SummaryRoute() {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <SummarySkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="leads"
      >
        <SignedOutWelcome
          title="Sign in to see today’s summary"
          text="Each seller’s day, in one place."
        />
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="leads">
      <PageHeader
        title="Today’s summary"
        titleInBar
        back={{ href: "/leads", label: "Leads" }}
      />
      <SummaryView
        key={`${access.context?.personId}:${access.context?.tenantId}`}
      />
    </AcquisitionShell>
  );
}
