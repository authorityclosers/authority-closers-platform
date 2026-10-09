import { AlertCircle, Clock, FolderOpen, Plus } from "lucide-react";
import Link from "next/link";
import { analysedTrend, isEmptyAccount, minutesLeft } from "./dashboard-data";
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
import { OperationalPanel } from "../ui/operational-panel";
import { MetricBand, MetricCard } from "../ui/metric-card";
import { RecentCallsPanel } from "./recent-calls-panel";
import type { DashboardSnapshot } from "../session-data";
import styles from "./dashboard.module.css";

export function DashboardWidgets({
  summary: summaryState,
  activity: activityState,
  allowance: allowanceState,
  recent: recentState,
}: Omit<DashboardSnapshot, "contextKey">) {
  const summary = summaryState.status === "ready" ? summaryState.value : null;
  const activity =
    activityState.status === "ready" ? activityState.value : null;
  const recent = recentState.status === "ready" ? recentState.value : null;

  const isAccountEmpty = isEmptyAccount(summary, activity, recent);

  const activityAllZero =
    activity !== null && activity.days.every((d) => d.analysed === 0);

  const trend = activity ? analysedTrend(activity) : null;

  return (
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
            allowanceState.status === "ready" && !allowanceState.value.unlimited
              ? undefined
              : Clock
          }
          visual={
            allowanceState.status === "ready" &&
            !allowanceState.value.unlimited ? (
              <MinutesRing allowance={allowanceState.value} />
            ) : undefined
          }
          aside={
            allowanceState.status === "ready" ? (
              <MinutesUsed allowance={allowanceState.value} />
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
            summary ? <AttentionAction count={summary.needsAttention} /> : null
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
              <span className={styles.chartEmptyText}>Not available yet.</span>
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
              <span className={styles.chartEmptyText}>Not available yet.</span>
            </div>
          ) : summary.total === 0 ? (
            <div className={styles.chartEmptyWrap}>
              <span className={styles.chartEmptyText}>No saved calls yet.</span>
            </div>
          ) : (
            <StatusRing summary={summary} />
          )}
        </OperationalPanel>
      </div>

      <RecentCallsPanel
        recentState={recentState}
        isAccountEmpty={isAccountEmpty}
      />
    </div>
  );
}
