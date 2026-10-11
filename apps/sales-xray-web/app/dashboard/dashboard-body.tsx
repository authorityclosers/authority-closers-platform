"use client";

import { AlertCircle, Plus } from "lucide-react";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import type { Allowance, LibrarySubmission } from "../acquisition-client";
import { Delta, Meter, Spark } from "../ui/kit";
import { SectionBoundary } from "../ui/section-boundary";
import { useWorkspaceAccess } from "../workspace-access";
import {
  isEmptyAccount,
  minutesLeft,
  type CallActivity,
  type CallSummary,
  type ReadResult,
} from "./dashboard-data";
import { DashboardGreeting } from "./dashboard-greeting";
import {
  AttentionAction,
  DayBars,
  DayBarsSkeleton,
  MinutesRing,
  MinutesUsed,
  StatusSplit,
  StatusSplitSkeleton,
} from "./dashboard-visuals";
import { RecentCallsList, RecentCallsSkeleton } from "./recent-calls";
import styles from "./dashboard.module.css";

export type ReadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; forbidden: boolean };

/** 403 means this workspace has no Sales Xray: said once, not per panel. */
export const toState = <T,>(result: ReadResult<T>): ReadState<T> =>
  result.ok
    ? { status: "ready", value: result.value }
    : { status: "error", forbidden: result.status === 403 };

const LOADING = { status: "loading" } as const;

/**
 * Owners and admins of an organisation see team-wide counts (labels say so).
 * Null while the workspace list is still loading: labels wait as placeholders,
 * so no label changes its words after the page appears.
 */
export function useDashboardTeam(): boolean | null {
  const access = useWorkspaceAccess();
  if (!access || access.status === "loading") return null;
  const current = access.workspaces?.find(
    (item) => item.tenant_id === access.context?.tenantId,
  );
  return (
    current?.kind === "organisation" &&
    (current.role === "owner" || current.role === "admin")
  );
}

/** A word-shaped placeholder inside a line of text, so the line keeps its height. */
function Ph({ w }: { w: string }) {
  return (
    <i
      className={styles.ph}
      style={{ "--w": w } as CSSProperties}
      aria-hidden="true"
    />
  );
}

type DashboardBodyProps = {
  team: boolean | null;
  summary?: ReadState<CallSummary | null>;
  activity?: ReadState<CallActivity | null>;
  allowance?: ReadState<Allowance>;
  recent?: ReadState<LibrarySubmission[]>;
  viewerId?: string | null;
  hiddenRecent?: number;
  onHiddenChange?: (count: number) => void;
  /** The page's one loading state: the loaded layout with placeholders. */
  skeleton?: boolean;
};

/**
 * The dashboard's blocks. Its skeleton is this same tree with placeholders,
 * so the route's loading screen, the page while it reads, and the loaded
 * page share every line and edge: nothing moves when the numbers arrive.
 */
export function DashboardBody({
  team,
  summary: summaryState = LOADING,
  activity: activityState = LOADING,
  allowance: allowanceState = LOADING,
  recent: recentState = LOADING,
  viewerId = null,
  hiddenRecent = 0,
  onHiddenChange,
  skeleton = false,
}: DashboardBodyProps) {
  const summary = summaryState.status === "ready" ? summaryState.value : null;
  const activity =
    activityState.status === "ready" ? activityState.value : null;
  const recent = recentState.status === "ready" ? recentState.value : null;
  const allowance =
    allowanceState.status === "ready" ? allowanceState.value : null;
  const failing = [summaryState, activityState, allowanceState, recentState]
    .map((state) => state.status)
    .includes("error");
  const settled =
    summaryState.status !== "loading" &&
    activityState.status !== "loading" &&
    recentState.status === "ready";
  const showGetStarted =
    !skeleton &&
    settled &&
    !failing &&
    isEmptyAccount(summary, activity, recent);
  const activityAllZero =
    activity !== null && activity.days.every((d) => d.analysed === 0);
  // The tile's sparkline: the last two weeks of the daily chart, today lit.
  const lastTwoWeeks = activity?.days.slice(-14).map((day) => day.analysed);
  const label = (teamText: string, ownText: string, width: string) =>
    team === null ? <Ph w={width} /> : team ? teamText : ownText;

  const content = (
    <>
      {/* One steady heading; New analysis lives in the shell, not here too.
          The workspace is named in the bar above, so the line stays put. */}
      <header className={styles.header}>
        <DashboardGreeting
          placeholder={skeleton}
          subtitle="Last 30 days, India time"
        />
      </header>

      {showGetStarted ? (
        <GetStarted allowance={allowance} />
      ) : (
        <>
          <dl className={styles.strip} aria-label="Dashboard figures">
            <Figure
              id="metric-analysed"
              label={label("Your calls analysed", "Calls analysed", "8em")}
              status={activityState.status}
              value={activity?.analysedLast30Days}
              delta={
                activity &&
                (activity.analysedLast30Days ||
                  activity.analysedPrevious30Days) ? (
                  <Delta
                    value={activity.analysedLast30Days}
                    previous={activity.analysedPrevious30Days}
                  />
                ) : null
              }
              context={
                activity === null
                  ? null
                  : activity.analysedPrevious30Days ||
                      activity.analysedLast30Days
                    ? `${activity.analysedPrevious30Days} in the 30 days before`
                    : "in the last 30 days"
              }
              accessory={
                lastTwoWeeks ? (
                  <span className={styles.figureSpark}>
                    <Spark
                      values={lastTwoWeeks}
                      label={`Calls analysed per day, last 14 days: ${lastTwoWeeks.join(", ")}`}
                    />
                  </span>
                ) : null
              }
            />
            <Figure
              id="metric-reports-ready"
              label="Reports ready"
              status={summaryState.status}
              value={summary?.completed}
              context={
                summary === null
                  ? null
                  : `of ${summary.total} ${team ? "team" : "saved"} ${summary.total === 1 ? "call" : "calls"}`
              }
              accessory={
                summary && summary.total > 0 ? (
                  <span className={styles.figureShare}>
                    <Meter
                      value={summary.completed}
                      max={summary.total}
                      label={`${Math.round((summary.completed / summary.total) * 100)}% of saved calls have a ready report`}
                    />
                  </span>
                ) : null
              }
            />
            <Figure
              id="metric-minutes-left"
              label="Minutes left"
              status={allowanceState.status}
              value={allowance ? minutesLeft(allowance).value : null}
              context={
                allowance ? (
                  <>
                    {minutesLeft(allowance).subtext}
                    {allowance.unlimited ? null : (
                      <span className={styles.used}>
                        {" · "}
                        <MinutesUsed allowance={allowance} />
                      </span>
                    )}
                  </>
                ) : null
              }
              accessory={
                allowance ? <MinutesRing allowance={allowance} /> : null
              }
            />
            <Figure
              id="metric-needs-attention"
              label={
                summary && summary.needsAttention > 0 ? (
                  <>
                    <span className={styles.warnDot} aria-hidden="true" />
                    Needs attention
                  </>
                ) : (
                  "Needs attention"
                )
              }
              status={summaryState.status}
              value={summary?.needsAttention}
              context={
                summary === null ? null : (
                  <AttentionAction count={summary.needsAttention} />
                )
              }
            />
          </dl>

          <div className={styles.columns}>
            <section
              className={styles.section}
              aria-labelledby="panel-last-30-days"
            >
              <div className={styles.sectionHead}>
                <h2 id="panel-last-30-days">
                  {label(
                    "Your calls analysed per day",
                    "Calls analysed per day",
                    "13em",
                  )}
                </h2>
                <span>Last 30 days, India time</span>
              </div>
              <div className={styles.surface}>
                {activityState.status === "loading" ? (
                  <DayBarsSkeleton />
                ) : activityState.status === "error" ? (
                  <NotLoaded />
                ) : activity === null ? (
                  <Quiet text="Daily numbers are not available yet." />
                ) : activityAllZero ? (
                  <Quiet text="No calls analysed in the last 30 days." />
                ) : (
                  <SectionBoundary name="The daily chart">
                    <DayBars days={activity.days} />
                  </SectionBoundary>
                )}
              </div>
            </section>

            <section
              className={styles.section}
              aria-labelledby="panel-call-status"
            >
              <div className={styles.sectionHead}>
                <h2 id="panel-call-status">Call status</h2>
                <span>
                  {label(
                    "Everyone in the organisation",
                    "All saved calls",
                    "10em",
                  )}
                </span>
              </div>
              <div className={styles.surface}>
                {summaryState.status === "loading" ? (
                  <StatusSplitSkeleton />
                ) : summaryState.status === "error" ? (
                  <NotLoaded />
                ) : summary === null ? (
                  <Quiet text="Call status is not available yet." />
                ) : summary.total === 0 ? (
                  <Quiet text="No saved calls yet." />
                ) : (
                  <SectionBoundary name="Call status">
                    <StatusSplit summary={summary} />
                  </SectionBoundary>
                )}
              </div>
            </section>
          </div>

          <section
            className={styles.section}
            aria-labelledby="panel-recent-calls"
          >
            <div className={styles.sectionHead}>
              <h2 id="panel-recent-calls">Recent calls</h2>
              {recent && recent.length > 0 ? (
                <Link className={styles.textLink} href="/analysis/calls">
                  View all calls
                  {hiddenRecent > 0 ? ` (+${hiddenRecent})` : ""}
                </Link>
              ) : null}
            </div>
            <div className={styles.surface} data-flush="">
              {recentState.status === "loading" ? (
                <RecentCallsSkeleton />
              ) : recentState.status === "error" ? (
                <NotLoaded />
              ) : recent === null || recent.length === 0 ? (
                <Quiet text="No calls yet." />
              ) : (
                <SectionBoundary name="Recent calls">
                  <RecentCallsList
                    calls={recent}
                    viewerId={viewerId}
                    onHiddenChange={onHiddenChange}
                  />
                </SectionBoundary>
              )}
            </div>
          </section>
        </>
      )}
    </>
  );

  return skeleton ? (
    <div
      className={styles.page}
      role="status"
      aria-busy="true"
      aria-label="Loading your dashboard"
    >
      {content}
    </div>
  ) : (
    <div className={styles.page}>{content}</div>
  );
}

/** One figure: label, value (or why there is none), one line of context. */
function Figure({
  id,
  label,
  status,
  value,
  delta,
  context,
  accessory,
}: {
  id: string;
  label: ReactNode;
  status: "loading" | "ready" | "error";
  value: number | string | null | undefined;
  /** Change against the period before, beside the value (kit Delta). */
  delta?: ReactNode;
  context: ReactNode;
  /** A sparkline, share bar or ring at the row's end. */
  accessory?: ReactNode;
}) {
  return (
    <div className={styles.kpi} id={id}>
      <dt>{label}</dt>
      <dd>
        {status === "loading" ? (
          <i className={styles.skeletonValue} aria-hidden="true" />
        ) : status === "error" ? (
          <span className={styles.unknown}>Not loaded</span>
        ) : value === null || value === undefined ? (
          <span className={styles.unknown}>Not available yet</span>
        ) : (
          <span className={styles.valueLine}>
            <b>{value}</b>
            {delta}
          </span>
        )}
        {status === "ready" ? accessory : null}
      </dd>
      <dd className={styles.kpiContext}>
        {status === "loading" ? (
          <i className={styles.skeletonContext} aria-hidden="true" />
        ) : status === "ready" ? (
          context
        ) : null}
      </dd>
    </div>
  );
}

function Quiet({ text }: { text: string }) {
  return <p className={styles.quiet}>{text}</p>;
}

/** A failed read says so in place; the corner card offers the retry. */
function NotLoaded() {
  return (
    <p className={styles.quiet}>
      <AlertCircle size={14} aria-hidden="true" /> Not loaded. It retries by
      itself.
    </p>
  );
}

/** A brand-new account: one panel in place of zero figures and empty charts. */
function GetStarted({ allowance }: { allowance: Allowance | null }) {
  return (
    <section className={styles.getStarted} aria-labelledby="get-started">
      <div className={styles.getStartedCopy}>
        <h2 id="get-started">Analyse your first call</h2>
        <p>
          Upload a recording of a real sales call. Sales Xray transcribes it and
          writes a report on what happened and what to do next.
        </p>
      </div>
      <ol className={styles.steps}>
        <li>
          <b>1</b>
          <span>
            <strong>Upload a recording</strong>
            An audio file from your phone or computer.
          </span>
        </li>
        <li>
          <b>2</b>
          <span>
            <strong>We analyse it</strong>
            The call is transcribed and read for you.
          </span>
        </li>
        <li>
          <b>3</b>
          <span>
            <strong>Read your report</strong>
            What happened on the call and the next step.
          </span>
        </li>
      </ol>
      <div className={styles.getStartedFoot}>
        <Link className={styles.primaryAction} href="/analysis/new">
          <Plus size={16} aria-hidden="true" />
          <span>Analyse a call</span>
        </Link>
        {allowance ? (
          <span className={styles.muted}>
            {allowance.unlimited
              ? "Unlimited analysis time"
              : `${minutesLeft(allowance).value} ${minutesLeft(allowance).subtext}`}
          </span>
        ) : null}
      </div>
    </section>
  );
}
