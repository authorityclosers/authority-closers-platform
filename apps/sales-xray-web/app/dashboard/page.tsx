"use client";

import { AlertCircle, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import type { Allowance, LibrarySubmission } from "../acquisition-client";
import { ConnectionNotice } from "../connection-notice";
import { PolicyFooter } from "../policy-footer";
import { LightboxShell } from "../shell/lightbox-shell";
import { getShellState } from "../shell/shell-store";
import { WorkspaceNoAccess } from "../workspace-no-access";
import { SectionBoundary } from "../ui/section-boundary";
import { useWorkspaceAccess } from "../workspace-access";
import {
  analysedTrend,
  isEmptyAccount,
  minutesLeft,
  readAllowance,
  readCallActivity,
  readCallSummary,
  readRecentCalls,
  settle,
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
import { CALL_LABEL_EVENT, type CallLabelChange } from "../call-label-client";
import styles from "./dashboard.module.css";

type ReadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; forbidden: boolean };

/** 403 means this workspace has no Sales Xray: said once, not per panel. */
const toState = <T,>(result: ReadResult<T>): ReadState<T> =>
  result.ok
    ? { status: "ready", value: result.value }
    : { status: "error", forbidden: result.status === 403 };

export default function DashboardPage() {
  const access = useWorkspaceAccess();
  if (access?.authenticated !== false) return <DashboardDetails />;
  return (
    <LightboxShell
      active="dashboard"
      authenticated={false}
      homeHref="/dashboard"
    >
      <section className={styles.emptyCard} aria-labelledby="dashboard-signin">
        <h2 id="dashboard-signin" className={styles.emptyTitle}>
          Sign in to see your dashboard
        </h2>
        <p className={styles.emptyDescription}>
          Your saved calls, reports and minutes appear after you sign in.
        </p>
        <Link
          className={styles.primaryAction}
          href="/login"
          onClick={(event) => {
            if (access.requestAccountSignIn) {
              event.preventDefault();
              access.requestAccountSignIn();
            }
          }}
        >
          Sign in
        </Link>
        <Link className={styles.guestAction} href="/analysis/new">
          Or analyse a call without an account
        </Link>
      </section>
      <PolicyFooter />
    </LightboxShell>
  );
}

function DashboardDetails() {
  const access = useWorkspaceAccess();

  const [hiddenRecent, setHiddenRecent] = useState(0);
  const [retryCount, setRetryCount] = useState(0);
  const [summaryState, setSummaryState] = useState<
    ReadState<CallSummary | null>
  >({ status: "loading" });
  const [activityState, setActivityState] = useState<
    ReadState<CallActivity | null>
  >({ status: "loading" });
  const [allowanceState, setAllowanceState] = useState<ReadState<Allowance>>({
    status: "loading",
  });
  const [recentState, setRecentState] = useState<
    ReadState<LibrarySubmission[]>
  >({ status: "loading" });

  // A cancelled read (unmount, or a re-run of the effect) must not paint
  // "Not loaded": only the live request may change a panel.
  const loadSummary = useCallback(
    (signal?: AbortSignal) =>
      void settle(readCallSummary(signal)).then((result) => {
        if (!signal?.aborted) setSummaryState(toState(result));
      }),
    [],
  );

  const loadActivity = useCallback(
    (signal?: AbortSignal) =>
      void settle(readCallActivity(signal)).then((result) => {
        if (!signal?.aborted) setActivityState(toState(result));
      }),
    [],
  );

  const loadAllowance = useCallback(
    (signal?: AbortSignal) =>
      void settle(readAllowance(signal)).then((result) => {
        if (!signal?.aborted) setAllowanceState(toState(result));
      }),
    [],
  );

  const loadRecent = useCallback(
    (signal?: AbortSignal) =>
      void settle(readRecentCalls(signal, 5, true)).then((result) => {
        if (!signal?.aborted) setRecentState(toState(result));
      }),
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    loadSummary(controller.signal);
    loadActivity(controller.signal);
    loadAllowance(controller.signal);
    loadRecent(controller.signal);
    return () => controller.abort();
  }, [loadSummary, loadActivity, loadAllowance, loadRecent]);

  // A rename in the sidebar or a report shows in Recent calls at once.
  useEffect(() => {
    const onLabel = (event: Event) => {
      const { submissionId, label } = (event as CustomEvent<CallLabelChange>)
        .detail;
      setRecentState((state) =>
        state.status === "ready"
          ? {
              ...state,
              value: state.value.map((call) =>
                call.id === submissionId &&
                (!call.label || call.label.revision < label.revision)
                  ? { ...call, label }
                  : call,
              ),
            }
          : state,
      );
    };
    window.addEventListener(CALL_LABEL_EVENT, onLabel);
    return () => window.removeEventListener(CALL_LABEL_EVENT, onLabel);
  }, []);

  const summary = summaryState.status === "ready" ? summaryState.value : null;
  const activity =
    activityState.status === "ready" ? activityState.value : null;
  const recent = recentState.status === "ready" ? recentState.value : null;

  const isAccountEmpty = isEmptyAccount(summary, activity, recent);

  const activityAllZero =
    activity !== null && activity.days.every((d) => d.analysed === 0);

  const trend = activity ? analysedTrend(activity) : null;

  // 403: this workspace has no Sales Xray access. Say so once, clearly.
  const states = [summaryState, activityState, allowanceState, recentState];
  const forbidden = states.some(
    (state) => state.status === "error" && state.forbidden,
  );
  const failing = states.some(
    (state) => state.status === "error" && !state.forbidden,
  );
  const retryFailed = () => {
    if (summaryState.status === "error") {
      setSummaryState({ status: "loading" });
      loadSummary();
    }
    if (activityState.status === "error") {
      setActivityState({ status: "loading" });
      loadActivity();
    }
    if (allowanceState.status === "error") {
      setAllowanceState({ status: "loading" });
      loadAllowance();
    }
    if (recentState.status === "error") {
      setRecentState({ status: "loading" });
      loadRecent();
    }
  };
  if (forbidden) {
    const shell = getShellState();
    const workspace =
      shell.workspaces.find(
        (item) => item.tenant_id === access?.context?.tenantId,
      )?.name ?? null;
    return (
      <LightboxShell
        active="dashboard"
        authenticated={access?.authenticated === true}
        homeHref="/dashboard"
      >
        <WorkspaceNoAccess workspace={workspace} />
      </LightboxShell>
    );
  }

  const shell = getShellState();
  const workspaceName =
    shell.workspaces.find(
      (item) => item.tenant_id === access?.context?.tenantId,
    )?.name ?? null;
  // Owners and admins: saved-call counts and the list cover the whole team,
  // while analysed-per-day is the viewer's own. Each label says which.
  const current = access?.workspaces?.find(
    (item) => item.tenant_id === access?.context?.tenantId,
  );
  const team =
    current?.kind === "organisation" &&
    (current.role === "owner" || current.role === "admin");
  const settled =
    summaryState.status !== "loading" &&
    activityState.status !== "loading" &&
    recentState.status === "ready";
  const showGetStarted = settled && !failing && isAccountEmpty;
  const allowance =
    allowanceState.status === "ready" ? allowanceState.value : null;

  return (
    <LightboxShell
      active="dashboard"
      authenticated={access?.authenticated === true}
      homeHref="/dashboard"
    >
      <div className={styles.page}>
        {/* One steady heading; New analysis lives in the shell, not here too. */}
        <header className={styles.header}>
          <DashboardGreeting
            subtitle={
              workspaceName
                ? `${workspaceName} · last 30 days, India time`
                : "Last 30 days, India time"
            }
          />
        </header>

        {showGetStarted ? (
          <GetStarted allowance={allowance} />
        ) : (
          <>
            <dl className={styles.strip} aria-label="Dashboard figures">
              <Figure
                id="metric-analysed"
                label={team ? "Your calls analysed" : "Calls analysed"}
                status={activityState.status}
                value={activity?.analysedLast30Days}
                context={
                  activity === null
                    ? null
                    : trend
                      ? trend.text
                      : "in the last 30 days"
                }
                tone={trend?.direction}
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
                label="Needs attention"
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
                    {team
                      ? "Your calls analysed per day"
                      : "Calls analysed per day"}
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
                    {team ? "Everyone in the organisation" : "All saved calls"}
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
                      viewerId={access?.context?.personId ?? null}
                      onHiddenChange={setHiddenRecent}
                    />
                  </SectionBoundary>
                )}
              </div>
            </section>
          </>
        )}
      </div>
      {failing ? (
        <ConnectionNotice
          title="Some numbers did not load"
          message="Some dashboard numbers could not load. The rest of the page still works."
          failures={retryCount + 1}
          onRetry={() => {
            setRetryCount((count) => count + 1);
            retryFailed();
          }}
        />
      ) : null}
    </LightboxShell>
  );
}

/** One figure: label, value (or why there is none), one line of context. */
function Figure({
  id,
  label,
  status,
  value,
  context,
  accessory,
  tone,
}: {
  id: string;
  label: string;
  status: "loading" | "ready" | "error";
  value: number | string | null | undefined;
  context: ReactNode;
  accessory?: ReactNode;
  tone?: "up" | "down" | "flat";
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
          <b>{value}</b>
        )}
        {status === "ready" ? accessory : null}
      </dd>
      <dd className={styles.kpiContext} data-tone={tone}>
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
