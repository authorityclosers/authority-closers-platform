"use client";

import { AlertCircle, ArrowRight, Clock, FolderOpen, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { type Allowance, type LibrarySubmission } from "../acquisition-client";
import { LightboxShell } from "../shell/lightbox-shell";
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
import { MinutesRing, MonthWave, StatusRing } from "./dashboard-visuals";
import { RecentCallsList } from "./recent-calls";
import styles from "./dashboard.module.css";

type ReadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error" };

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
      .catch(() => setSummaryState({ status: "error" }));
  }, []);

  const loadActivity = useCallback((signal?: AbortSignal) => {
    readCallActivity(signal)
      .then((value) => setActivityState({ status: "ready", value }))
      .catch(() => setActivityState({ status: "error" }));
  }, []);

  const loadAllowance = useCallback((signal?: AbortSignal) => {
    readAllowance(signal)
      .then((value) => setAllowanceState({ status: "ready", value }))
      .catch(() => setAllowanceState({ status: "error" }));
  }, []);

  const loadRecent = useCallback((signal?: AbortSignal) => {
    readRecentCalls(signal)
      .then((value) => setRecentState({ status: "ready", value }))
      .catch(() => setRecentState({ status: "error" }));
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
              {trend && (
                <span
                  className={`${styles.trendBadge} ${
                    trend.direction === "up"
                      ? styles.trendUp
                      : trend.direction === "down"
                        ? styles.trendDown
                        : styles.trendNeutral
                  }`}
                >
                  {trend.direction === "up" && "↑ "}
                  {trend.direction === "down" && "↓ "}
                  {trend.text}
                </span>
              )}
            </div>
            <div className={styles.kpiValue}>
              {activityState.status === "loading"
                ? "—"
                : activityState.status === "error"
                  ? "—"
                  : activity === null
                    ? "—"
                    : activity.analysedLast30Days}
            </div>
            <div className={styles.kpiLabel}>Calls analysed · last 30 days</div>
            <div className={styles.kpiSubtext}>
              {activityState.status === "loading" ? (
                " "
              ) : activityState.status === "error" ? (
                <button
                  type="button"
                  className={styles.retryAction}
                  onClick={() => {
                    setActivityState({ status: "loading" });
                    loadActivity();
                  }}
                >
                  Couldn&apos;t load · Retry
                </button>
              ) : activity === null ? (
                "Not available yet"
              ) : (
                " "
              )}
            </div>
          </div>

          {/* Card 2: Reports ready */}
          <div className={styles.kpiCard}>
            <div className={styles.kpiTop}>
              <div className={styles.kpiIconWrap}>
                <FolderOpen size={18} aria-hidden="true" />
              </div>
            </div>
            <div className={styles.kpiValue}>
              {summaryState.status === "loading"
                ? "—"
                : summaryState.status === "error"
                  ? "—"
                  : summary === null
                    ? "—"
                    : summary.completed}
            </div>
            <div className={styles.kpiLabel}>Reports ready</div>
            <div className={styles.kpiSubtext}>
              {summaryState.status === "loading" ? (
                " "
              ) : summaryState.status === "error" ? (
                <button
                  type="button"
                  className={styles.retryAction}
                  onClick={() => {
                    setSummaryState({ status: "loading" });
                    loadSummary();
                  }}
                >
                  Couldn&apos;t load · Retry
                </button>
              ) : summary === null ? (
                "Not available yet"
              ) : (
                `of ${summary.total} saved calls`
              )}
            </div>
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
              {allowanceState.status === "loading"
                ? "—"
                : allowanceState.status === "error"
                  ? "—"
                  : minutesLeft(allowanceState.value).value}
            </div>
            <div className={styles.kpiLabel}>Minutes left</div>
            <div className={styles.kpiSubtext}>
              {allowanceState.status === "loading" ? (
                " "
              ) : allowanceState.status === "error" ? (
                <button
                  type="button"
                  className={styles.retryAction}
                  onClick={() => {
                    setAllowanceState({ status: "loading" });
                    loadAllowance();
                  }}
                >
                  Couldn&apos;t load · Retry
                </button>
              ) : (
                minutesLeft(allowanceState.value).subtext
              )}
            </div>
          </div>

          {/* Card 4: Needs attention */}
          <div className={styles.kpiCard}>
            <div className={styles.kpiTop}>
              <div className={styles.kpiIconWrapAmber}>
                <AlertCircle size={18} aria-hidden="true" />
              </div>
            </div>
            <div className={styles.kpiValue}>
              {summaryState.status === "loading"
                ? "—"
                : summaryState.status === "error"
                  ? "—"
                  : summary === null
                    ? "—"
                    : summary.needsAttention}
            </div>
            <div className={styles.kpiLabel}>Needs attention</div>
            <div className={styles.kpiSubtext}>
              {summaryState.status === "loading" ? (
                " "
              ) : summaryState.status === "error" ? (
                <button
                  type="button"
                  className={styles.retryAction}
                  onClick={() => {
                    setSummaryState({ status: "loading" });
                    loadSummary();
                  }}
                >
                  Couldn&apos;t load · Retry
                </button>
              ) : summary === null ? (
                "Not available yet"
              ) : (
                "Calls to check"
              )}
            </div>
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
              <div className={styles.chartEmptyWrap}>
                <span className={styles.chartEmptyText}>—</span>
              </div>
            ) : activityState.status === "error" ? (
              <div className={styles.chartEmptyWrap}>
                <button
                  type="button"
                  className={styles.retryAction}
                  onClick={() => {
                    setActivityState({ status: "loading" });
                    loadActivity();
                  }}
                >
                  Couldn&apos;t load · Retry
                </button>
              </div>
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
              <div className={styles.chartEmptyWrap}>
                <span className={styles.chartEmptyText}>—</span>
              </div>
            ) : summaryState.status === "error" ? (
              <div className={styles.chartEmptyWrap}>
                <button
                  type="button"
                  className={styles.retryAction}
                  onClick={() => {
                    setSummaryState({ status: "loading" });
                    loadSummary();
                  }}
                >
                  Couldn&apos;t load · Retry
                </button>
              </div>
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
                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            )}
          </div>

          {recentState.status === "loading" ? (
            <div className={styles.chartEmptyWrap}>
              <span className={styles.chartEmptyText}>—</span>
            </div>
          ) : recentState.status === "error" ? (
            <div className={styles.chartEmptyWrap}>
              <button
                type="button"
                className={styles.retryAction}
                onClick={() => {
                  setRecentState({ status: "loading" });
                  loadRecent();
                }}
              >
                Couldn&apos;t load · Retry
              </button>
            </div>
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
            <RecentCallsList calls={recent} />
          )}
        </div>
      </div>
    </LightboxShell>
  );
}
