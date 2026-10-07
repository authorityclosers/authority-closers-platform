"use client";

import { AlertCircle, ArrowRight, Clock, FolderOpen, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  AcquisitionError,
  type Allowance,
  type LibrarySubmission,
} from "../acquisition-client";
import { ConnectionNotice } from "../connection-notice";
import { PolicyFooter } from "../policy-footer";
import { LightboxShell } from "../shell/lightbox-shell";
import { getShellState } from "../shell/shell-store";
import { WorkspaceNoAccess } from "../workspace-no-access";
import { useWorkspaceAccess } from "../workspace-access";
import {
  analysedTrend,
  isEmptyAccount,
  minutesLeft,
  readAllowance,
  readCallActivity,
  readCallSummary,
  readRecentCalls,
  type CallActivity,
  type CallSummary,
} from "./dashboard-data";
import { DashboardGreeting } from "./dashboard-greeting";
import {
  AttentionAction,
  MonthWaveSkeleton,
  StatusRingSkeleton,
  MinutesRing,
  MinutesUsed,
  MonthWave,
  ShareRing,
  StatusRing,
  TrendChip,
} from "./dashboard-visuals";
import { RecentCallsList, RecentCallsSkeleton } from "./recent-calls";
import { OperationalEmpty, OperationalPanel } from "../ui/operational-panel";
import { MetricBand, MetricCard } from "../ui/metric-card";
import styles from "./dashboard.module.css";

type ReadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; forbidden: boolean };

const isForbidden = (error: unknown) =>
  error instanceof AcquisitionError && error.status === 403;

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

  const loadSummary = useCallback((signal?: AbortSignal) => {
    readCallSummary(signal)
      .then((value) => setSummaryState({ status: "ready", value }))
      .catch((error) =>
        setSummaryState({ status: "error", forbidden: isForbidden(error) }),
      );
  }, []);

  const loadActivity = useCallback((signal?: AbortSignal) => {
    readCallActivity(signal)
      .then((value) => setActivityState({ status: "ready", value }))
      .catch((error) =>
        setActivityState({ status: "error", forbidden: isForbidden(error) }),
      );
  }, []);

  const loadAllowance = useCallback((signal?: AbortSignal) => {
    readAllowance(signal)
      .then((value) => setAllowanceState({ status: "ready", value }))
      .catch((error) =>
        setAllowanceState({ status: "error", forbidden: isForbidden(error) }),
      );
  }, []);

  const loadRecent = useCallback((signal?: AbortSignal) => {
    readRecentCalls(signal)
      .then((value) => setRecentState({ status: "ready", value }))
      .catch((error) =>
        setRecentState({ status: "error", forbidden: isForbidden(error) }),
      );
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadSummary(controller.signal);
    loadActivity(controller.signal);
    loadAllowance(controller.signal);
    loadRecent(controller.signal);
    return () => controller.abort();
  }, [loadSummary, loadActivity, loadAllowance, loadRecent]);

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

  return (
    <LightboxShell
      active="dashboard"
      authenticated={access?.authenticated === true}
      homeHref="/dashboard"
    >
      <div className={styles.dashboardRoot}>
        {/* Top greeting / actions */}
        <div className={styles.dashboardHeader}>
          <DashboardGreeting />
          <Link href="/analysis/new" className={styles.primaryAction}>
            <Plus size={16} aria-hidden="true" />
            <span>New analysis</span>
          </Link>
        </div>

        {/* 1. Metric band with explicit units and context */}
        <MetricBand label="Operational call and allowance summary" columns={4}>
          <MetricCard
            id="metric-analysed"
            label="Calls analysed"
            value={activity?.analysedLast30Days}
            unit={activity !== null ? "calls" : undefined}
            context={
              activityState.status === "loading"
                ? undefined
                : activityState.status === "error"
                  ? undefined
                  : activity === null
                    ? "Not available yet"
                    : "Last 30 days, India time"
            }
            status={activityState.status}
            icon={FolderOpen}
            iconTone="teal"
            aside={
              trend ? (
                <TrendChip direction={trend.direction} text={trend.text} />
              ) : null
            }
          />

          <MetricCard
            id="metric-reports-ready"
            label="Reports ready"
            value={summary?.completed}
            unit={summary !== null ? "reports" : undefined}
            context={
              summaryState.status === "loading"
                ? undefined
                : summaryState.status === "error"
                  ? undefined
                  : summary === null
                    ? "Not available yet"
                    : `of ${summary.total} saved calls`
            }
            status={summaryState.status}
            icon={FolderOpen}
            aside={
              summary && summary.total > 0 ? (
                <ShareRing part={summary.completed} total={summary.total} />
              ) : null
            }
          />

          <MetricCard
            id="metric-minutes-left"
            label="Minutes left"
            value={
              allowanceState.status === "ready"
                ? minutesLeft(allowanceState.value).value
                : null
            }
            context={
              allowanceState.status === "loading"
                ? undefined
                : allowanceState.status === "error"
                  ? undefined
                  : minutesLeft(allowanceState.value).subtext
            }
            status={allowanceState.status}
            icon={
              allowanceState.status === "ready" &&
              !allowanceState.value.unlimited
                ? undefined
                : Clock
            }
            aside={
              allowanceState.status === "ready" ? (
                !allowanceState.value.unlimited ? (
                  <MinutesRing allowance={allowanceState.value} />
                ) : (
                  <MinutesUsed allowance={allowanceState.value} />
                )
              ) : null
            }
          />

          <MetricCard
            id="metric-needs-attention"
            label="Needs attention"
            value={summary?.needsAttention}
            unit={summary !== null ? "calls" : undefined}
            context={
              summaryState.status === "loading"
                ? undefined
                : summaryState.status === "error"
                  ? undefined
                  : summary === null
                    ? "Not available yet"
                    : "Calls to check"
            }
            status={summaryState.status}
            icon={AlertCircle}
            iconTone="amber"
            aside={
              summary ? (
                <AttentionAction count={summary.needsAttention} />
              ) : null
            }
          />
        </MetricBand>

        {/* 2. Left 2/3 Calls analysed per day + Right 1/3 Call status */}
        <div className={styles.analyticsGrid}>
          {/* Left 2/3: Calls analysed per day */}
          <OperationalPanel
            id="panel-last-30-days"
            title="Last 30 days"
            sub="Calls and call time analysed each day, India time"
            className={styles.chartCard}
          >
            {activityState.status === "loading" ? (
              <MonthWaveSkeleton />
            ) : activityState.status === "error" ? (
              <MonthWaveSkeleton />
            ) : activity === null ? (
              <div className={styles.chartEmptyWrap}>
                <span className={styles.chartEmptyText}>
                  Not available yet.
                </span>
              </div>
            ) : activityAllZero ? (
              <div className={styles.chartEmptyWrap}>
                <span className={styles.chartEmptyText}>
                  No analysed calls in the last 30 days.
                </span>
              </div>
            ) : (
              <MonthWave days={activity.days} />
            )}
          </OperationalPanel>

          {/* Right 1/3: Call status */}
          <OperationalPanel
            id="panel-call-status"
            title="Call status"
            sub="Where your saved calls are now"
            className={styles.skillsCard}
          >
            {summaryState.status === "loading" ? (
              <StatusRingSkeleton />
            ) : summaryState.status === "error" ? (
              <StatusRingSkeleton />
            ) : summary === null ? (
              <div className={styles.chartEmptyWrap}>
                <span className={styles.chartEmptyText}>
                  Not available yet.
                </span>
              </div>
            ) : summary.total === 0 ? (
              <div className={styles.chartEmptyWrap}>
                <span className={styles.chartEmptyText}>
                  No saved calls yet.
                </span>
              </div>
            ) : (
              <StatusRing summary={summary} />
            )}
          </OperationalPanel>
        </div>

        {/* 3. Full width Recent Calls Table / Empty State */}
        <OperationalPanel
          id="panel-recent-calls"
          title="Recent calls"
          sub="Latest processed audio recordings and evaluations"
          action={
            recent && recent.length > 0
              ? {
                  href: "/analysis/calls",
                  label: "View all calls",
                  badge: hiddenRecent > 0 ? `+${hiddenRecent}` : undefined,
                }
              : undefined
          }
          className={styles.tableCard}
        >
          {recentState.status === "loading" ? (
            <RecentCallsSkeleton />
          ) : recentState.status === "error" ? (
            <RecentCallsSkeleton />
          ) : recent === null || recent.length === 0 ? (
            <OperationalEmpty
              icon={FolderOpen}
              title={
                isAccountEmpty ? "Analyse your first call" : "No calls yet"
              }
              description={
                isAccountEmpty
                  ? "Upload a sales call to start your analysis."
                  : "No calls yet"
              }
              action={
                <Link href="/analysis/new" className={styles.primaryAction}>
                  <Plus size={16} aria-hidden="true" />
                  <span>New analysis</span>
                </Link>
              }
            />
          ) : (
            <RecentCallsList calls={recent} onHiddenChange={setHiddenRecent} />
          )}
        </OperationalPanel>
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
