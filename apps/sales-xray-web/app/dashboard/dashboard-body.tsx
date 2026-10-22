"use client";

import { AlertCircle, Plus } from "lucide-react";
import Link from "next/link";
import {
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from "react";

import type { Allowance, LibrarySubmission } from "../acquisition-client";
import { Delta, Meter, Spark } from "../ui/kit";
import { SectionBoundary } from "../ui/section-boundary";
import { useWorkspaceAccess } from "../workspace-access";
import {
  isEmptyAccount,
  type CallActivity,
  type CallSummary,
  type ReadResult,
} from "./dashboard-data";
import { DashboardGreeting } from "./dashboard-greeting";
import {
  AttentionAction,
  DayBars,
  DayBarsSkeleton,
  StatusSplit,
  StatusSplitSkeleton,
} from "./dashboard-visuals";
import { RecentCallsList, RecentCallsSkeleton } from "./recent-calls";
import styles from "./dashboard.module.css";
import type { SandboxFacts } from "./dashboard-data";

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
const subscribeNothing = () => () => {};

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
  /** The fictional AC Sandbox's contents, when this workspace is the sandbox. */
  sandbox?: SandboxFacts | null;
  summary?: ReadState<CallSummary | null>;
  activity?: ReadState<CallActivity | null>;
  allowance?: ReadState<Allowance>;
  recent?: ReadState<LibrarySubmission[]>;
  viewerId?: string | null;
  hiddenRecent?: number;
  onHiddenChange?: (count: number) => void;
  /** The page's one loading state: the loaded layout with placeholders. */
  skeleton?: boolean;
  /**
   * In an organisation, Home starts with sales (owner, 22 Oct 2026): this
   * block comes first. Managers still see call analysis after it; a seller
   * sees only their recent calls after it.
   */
  sales?: ReactNode;
  salesRole?: "manager" | "seller" | null;
};

/**
 * The dashboard's blocks. Its skeleton is this same tree with placeholders,
 * so the route's loading screen, the page while it reads, and the loaded
 * page share every line and edge: nothing moves when the numbers arrive.
 */
export function DashboardBody({
  team,
  sandbox = null,
  summary: summaryState = LOADING,
  activity: activityState = LOADING,
  allowance: allowanceState = LOADING,
  recent: recentState = LOADING,
  viewerId = null,
  hiddenRecent = 0,
  onHiddenChange,
  skeleton = false,
  sales = null,
  salesRole = null,
}: DashboardBodyProps) {
  const summary = summaryState.status === "ready" ? summaryState.value : null;
  const activity =
    activityState.status === "ready" ? activityState.value : null;
  const recent = recentState.status === "ready" ? recentState.value : null;
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
  const hydrated = useSyncExternalStore(
    subscribeNothing,
    () => true,
    () => false,
  );
  const label = (teamText: string, ownText: string, width: string) =>
    team === null ? <Ph w={width} /> : team ? teamText : ownText;

  const content = (
    <>
      {/* One steady heading; New analysis lives in the shell, not here too.
          The workspace is named in the bar above, so the line stays put. */}
      {sales ?? (
        <header className={styles.header}>
          <DashboardGreeting
            placeholder={skeleton}
            subtitle="Last 30 days, India time"
          />
        </header>
      )}

      {sandbox?.sandbox ? <SandboxCard facts={sandbox} /> : null}

      {showGetStarted && !sales ? (
        <GetStarted />
      ) : (
        <>
          {/* Sales first, call analysis second (owner, 22 Oct 2026); a
              seller's Home keeps only their recent calls below today. */}
          {salesRole === "seller" ? null : (
            <>
              {sales ? (
                <h2 className={styles.partTitle}>Call analysis</h2>
              ) : null}
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
                    summary === null ? null : team === null ? (
                      <Ph w="9em" />
                    ) : (
                      `of ${summary.total} ${team ? "team" : "saved"} ${summary.total === 1 ? "call" : "calls"}`
                    )
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
                {/* No Minutes left here (owner, 19 Oct 2026: end users never see minutes, prices or validity; metering lives in Admin). */}
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
                    <span className={styles.wideMeta}>
                      Last 30 days, India time
                    </span>
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
            </>
          )}

          <section
            className={styles.section}
            aria-labelledby="panel-recent-calls"
          >
            <div className={styles.sectionHead}>
              <h2 id="panel-recent-calls">
                {sales ? "Calls analysed" : "Recent calls"}
              </h2>
              {recent && recent.length > 0 ? (
                <Link className={styles.textLink} href="/analysis/calls">
                  View all calls
                  {hiddenRecent > 0 ? ` (+${hiddenRecent})` : ""}
                </Link>
              ) : null}
            </div>
            <div className={styles.surface} data-flush="">
              {/* Rows carry dates and names in the browser's own language
                  and time zone, so a page rendered on the server (dev) draws
                  them once the app starts, in the rows' own boxes. */}
              {recentState.status === "loading" || !hydrated ? (
                <RecentCallsSkeleton />
              ) : recentState.status === "error" ? (
                <NotLoaded />
              ) : recent === null || recent.length === 0 ? (
                <Quiet
                  text="No calls yet."
                  action={{ href: "/analysis/new", label: "Analyse a call" }}
                />
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

/** Nothing to show yet; where it is a list's first use, one way to start. */
function Quiet({
  text,
  action,
}: {
  text: string;
  action?: { href: string; label: string };
}) {
  return (
    <p className={styles.quiet}>
      {text}
      {action ? (
        <Link className={styles.textLink} href={action.href}>
          {action.label}
        </Link>
      ) : null}
    </p>
  );
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
/** Why there is a made-up team here, what it holds, and where to look at it. */
function SandboxCard({ facts }: { facts: SandboxFacts }) {
  const n = (value: number) => value.toLocaleString("en-IN");
  return (
    <section className={styles.sandbox} aria-labelledby="sandbox-title">
      <div className={styles.sandboxCopy}>
        <p className={styles.sandboxEyebrow}>
          Fictional AC Sandbox · only you and your admins see it
        </p>
        <h2 id="sandbox-title">
          A made-up sales team, so you can see Sales Xray at scale
        </h2>
        <p>
          Nobody here is real. Every call has a report, coaching and a recorded
          outcome, so you can show team analytics to investors, check People and
          Insights with full numbers, read coaching examples, and test the
          pipeline without touching customer data.
        </p>
      </div>
      <dl className={styles.sandboxFacts} aria-label="What the sandbox holds">
        <div>
          <dt>Fictional businesses</dt>
          <dd>{n(facts.businesses)}</dd>
        </div>
        <div>
          <dt>Fictional reps</dt>
          <dd>{n(facts.representatives)}</dd>
        </div>
        <div>
          <dt>Calls with reports</dt>
          <dd>{n(facts.calls)}</dd>
        </div>
        <div>
          <dt>Recorded outcomes</dt>
          <dd>{n(facts.outcomes)}</dd>
        </div>
        {facts.historySummaries > 0 ? (
          <div>
            <dt>Call history since 2017</dt>
            <dd>{n(facts.historySummaries)}</dd>
          </div>
        ) : null}
      </dl>
      <nav className={styles.sandboxLinks} aria-label="Sandbox views">
        <Link href="/organisation/insights?range=all">Insights, all time</Link>
        <Link href="/coaching?view=team">Team coaching</Link>
        <Link href="/organisation?tab=members">People</Link>
        <Link href="/analysis/calls">All calls</Link>
      </nav>
    </section>
  );
}

function GetStarted() {
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
      </div>
    </section>
  );
}
