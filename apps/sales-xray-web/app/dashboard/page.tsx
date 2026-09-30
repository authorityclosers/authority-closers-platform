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

        {/* 1. Row of 4 KPI cards */}
        <div className={styles.kpiGrid}>
          {/* Card 1: Calls analysed */}
          <div className={styles.kpiCard}>
            <div className={styles.kpiTop}>
              <div className={styles.kpiIconWrapTeal}>
                <FolderOpen size={18} aria-hidden="true" />
              </div>
            </div>
            <div className={styles.kpiValue}>
              {activityState.status === "loading" ? (
                <span className={styles.valueSkeleton} aria-label="Loading" />
              ) : activityState.status === "error" ? (
                <span className={styles.valueSkeleton} aria-hidden="true" />
              ) : activity === null ? (
                "—"
              ) : (
                activity.analysedLast30Days
              )}
            </div>
            <div className={styles.kpiLabel}>Calls analysed</div>
            <div className={styles.kpiSubtext}>
              {activityState.status === "loading"
                ? " "
                : activityState.status === "error"
                  ? " "
                  : activity === null
                    ? "Not available yet"
                    : " "}
            </div>
            {trend && (
              <div className={styles.kpiAside}>
                <TrendChip direction={trend.direction} text={trend.text} />
              </div>
            )}
          </div>

          {/* Card 2: Reports ready */}
          <div className={styles.kpiCard}>
            <div className={styles.kpiTop}>
              <div className={styles.kpiIconWrap}>
                <FolderOpen size={18} aria-hidden="true" />
              </div>
            </div>
            <div className={styles.kpiValue}>
              {summaryState.status === "loading" ? (
                <span className={styles.valueSkeleton} aria-label="Loading" />
              ) : summaryState.status === "error" ? (
                <span className={styles.valueSkeleton} aria-hidden="true" />
              ) : summary === null ? (
                "—"
              ) : (
                summary.completed
              )}
            </div>
            <div className={styles.kpiLabel}>Reports ready</div>
            <div className={styles.kpiSubtext}>
              {summaryState.status === "loading"
                ? " "
                : summaryState.status === "error"
                  ? " "
                  : summary === null
                    ? "Not available yet"
                    : `of ${summary.total} saved calls`}
            </div>
            {summary && summary.total > 0 && (
              <div className={styles.kpiAside}>
                <ShareRing part={summary.completed} total={summary.total} />
              </div>
            )}
          </div>

          {/* Card 3: Minutes left */}
          <div className={styles.kpiCard}>
            <div className={styles.kpiTop}>
              <div className={styles.kpiIconWrap}>
                {allowanceState.status === "ready" &&
                !allowanceState.value.unlimited ? (
                  <MinutesRing allowance={allowanceState.value} />
                ) : (
                  <Clock size={18} aria-hidden="true" />
                )}
              </div>
            </div>
            <div className={styles.kpiValue}>
              {allowanceState.status === "loading" ? (
                <span className={styles.valueSkeleton} aria-label="Loading" />
              ) : allowanceState.status === "error" ? (
                <span className={styles.valueSkeleton} aria-hidden="true" />
              ) : (
                minutesLeft(allowanceState.value).value
              )}
            </div>
            <div className={styles.kpiLabel}>Minutes left</div>
            <div className={styles.kpiSubtext}>
              {allowanceState.status === "loading"
                ? " "
                : allowanceState.status === "error"
                  ? " "
                  : minutesLeft(allowanceState.value).subtext}
            </div>
            {allowanceState.status === "ready" && (
              <div className={styles.kpiAside}>
                <MinutesUsed allowance={allowanceState.value} />
              </div>
            )}
          </div>

          {/* Card 4: Needs attention */}
          <div className={styles.kpiCard}>
            <div className={styles.kpiTop}>
              <div className={styles.kpiIconWrapAmber}>
                <AlertCircle size={18} aria-hidden="true" />
              </div>
            </div>
            <div className={styles.kpiValue}>
              {summaryState.status === "loading" ? (
                <span className={styles.valueSkeleton} aria-label="Loading" />
              ) : summaryState.status === "error" ? (
                <span className={styles.valueSkeleton} aria-hidden="true" />
              ) : summary === null ? (
                "—"
              ) : (
                summary.needsAttention
              )}
            </div>
            <div className={styles.kpiLabel}>Needs attention</div>
            <div className={styles.kpiSubtext}>
              {summaryState.status === "loading"
                ? " "
                : summaryState.status === "error"
                  ? " "
                  : summary === null
                    ? "Not available yet"
                    : "Calls to check"}
            </div>
            {summary && (
              <div className={styles.kpiAside}>
                <AttentionAction count={summary.needsAttention} />
              </div>
            )}
          </div>
        </div>

        {/* 2. Left 2/3 Calls analysed per day + Right 1/3 Call status */}
        <div className={styles.analyticsGrid}>
          {/* Left 2/3: Calls analysed per day */}
          <div className={styles.chartCard}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Last 30 days</h3>
                <p className={styles.cardSubtitle}>
                  Calls and call time analysed each day, India time
                </p>
              </div>
            </div>

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
          </div>

          {/* Right 1/3: Call status */}
          <div className={styles.skillsCard}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Call status</h3>
                <p className={styles.cardSubtitle}>
                  Where your saved calls are now
                </p>
              </div>
            </div>

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
          </div>
        </div>

        {/* 3. Full width Recent Calls Table / Empty State */}
        <div className={styles.tableCard}>
          <div className={styles.cardHeader}>
            <div>
              <h3 className={styles.cardTitle}>Recent calls</h3>
              <p className={styles.cardSubtitle}>
                Latest processed audio recordings and evaluations
              </p>
            </div>
            {recent && recent.length > 0 && (
              <Link href="/analysis/calls" className={styles.viewAllLink}>
                <span>View all calls</span>
                {hiddenRecent > 0 ? (
                  <span className={styles.moreChip}>+{hiddenRecent}</span>
                ) : null}
                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            )}
          </div>

          {recentState.status === "loading" ? (
            <RecentCallsSkeleton />
          ) : recentState.status === "error" ? (
            <RecentCallsSkeleton />
          ) : recent === null || recent.length === 0 ? (
            <div className={styles.emptyCard}>
              <div className={styles.emptyIcon}>
                <FolderOpen size={24} aria-hidden="true" />
              </div>
              <h4 className={styles.emptyTitle}>
                {isAccountEmpty ? "Analyse your first call" : "No calls yet"}
              </h4>
              <p className={styles.emptyDescription}>
                {isAccountEmpty
                  ? "Upload a sales call to start your analysis."
                  : "No calls yet"}
              </p>
              <Link href="/analysis/new" className={styles.primaryAction}>
                <Plus size={16} aria-hidden="true" />
                <span>New analysis</span>
              </Link>
            </div>
          ) : (
            <RecentCallsList calls={recent} onHiddenChange={setHiddenRecent} />
          )}
        </div>
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
