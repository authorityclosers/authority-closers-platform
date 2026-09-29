"use client";

import { AlertCircle, ArrowRight, Clock, FolderOpen, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  callHref,
  type Allowance,
  type LibrarySubmission,
} from "../acquisition-client";
import { callTone, submissionState } from "../calls-library";
import { formatClock } from "../lightbox/time";
import { LightboxShell } from "../shell/lightbox-shell";
import { useWorkspaceAccess } from "../workspace-access";
import {
  analysedTrend,
  isEmptyAccount,
  minutesLeft,
  otherSavedCalls,
  readAllowance,
  readCallActivity,
  readCallSummary,
  readRecentCalls,
  type CallActivity,
  type CallSummary,
} from "./dashboard-data";
import { DashboardGreeting } from "./dashboard-greeting";
import styles from "./dashboard.module.css";

type ReadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error" };

function formatCreatedDate(createdAt: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
    new Date(createdAt),
  );
}

function formatDuration(durationSeconds: number): string {
  return `About ${formatClock(durationSeconds * 1000)}`;
}

function formatDayLabel(dateStr: string): string {
  const parts = dateStr.split("-");
  const day = parseInt(parts[2], 10);
  const monthIdx = parseInt(parts[1], 10) - 1;
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  return `${day} ${months[monthIdx]}`;
}

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

  const [hoveredPoint, setHoveredPoint] = useState<number | null>(null);

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

  // SVG dimensions for 30-day Activity Chart
  const svgWidth = 600;
  const svgHeight = 180;
  const padLeft = 36;
  const padRight = 20;
  const padTop = 20;
  const padBottom = 30;
  const chartW = svgWidth - padLeft - padRight;
  const chartH = svgHeight - padTop - padBottom;

  const highestAnalysed =
    activity && activity.days.length > 0
      ? Math.max(...activity.days.map((d) => d.analysed))
      : 0;
  const maxY = Math.max(1, highestAnalysed);

  // Whole number grid line ticks
  const yTicks: number[] = [];
  if (maxY <= 3) {
    for (let i = 0; i <= maxY; i += 1) yTicks.push(i);
  } else {
    yTicks.push(0, Math.round(maxY / 2), maxY);
  }

  const points =
    activity && activity.days.length > 0
      ? activity.days.map((item, i) => {
          const x = padLeft + (i / (activity.days.length - 1)) * chartW;
          const y = padTop + (1 - item.analysed / maxY) * chartH;
          return {
            x,
            y,
            analysed: item.analysed,
            analysedSeconds: item.analysedSeconds,
            date: item.date,
          };
        })
      : [];

  const pathD =
    points.length > 0
      ? points.reduce((acc, p, i) => {
          if (i === 0) return `M ${p.x} ${p.y}`;
          const prev = points[i - 1];
          const cx1 = prev.x + (p.x - prev.x) / 2;
          const cy1 = prev.y;
          const cx2 = prev.x + (p.x - prev.x) / 2;
          const cy2 = p.y;
          return `${acc} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${p.x} ${p.y}`;
        }, "")
      : "";

  const areaD =
    points.length > 0
      ? `${pathD} L ${points[points.length - 1].x} ${padTop + chartH} L ${points[0].x} ${padTop + chartH} Z`
      : "";

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
                <Clock size={18} aria-hidden="true" />
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
                <h3 className={styles.cardTitle}>Calls analysed per day</h3>
                <p className={styles.cardSubtitle}>
                  Completed analyses per day, last 30 days (India time)
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
              <div className={styles.chartContainer}>
                <svg
                  viewBox={`0 0 ${svgWidth} ${svgHeight}`}
                  className={styles.chartSvg}
                  preserveAspectRatio="none"
                >
                  <defs>
                    <linearGradient
                      id="activityAreaGrad"
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="0%"
                        stopColor="var(--lx-teal)"
                        stopOpacity="0.18"
                      />
                      <stop
                        offset="100%"
                        stopColor="var(--lx-teal)"
                        stopOpacity="0.0"
                      />
                    </linearGradient>
                  </defs>

                  {/* Horizontal grid lines */}
                  {yTicks.map((val) => {
                    const y = padTop + (1 - val / maxY) * chartH;
                    return (
                      <g key={val}>
                        <line
                          x1={padLeft}
                          y1={y}
                          x2={svgWidth - padRight}
                          y2={y}
                          className={styles.chartGridLine}
                        />
                        <text
                          x={padLeft - 8}
                          y={y + 4}
                          className={styles.chartYLabel}
                        >
                          {val}
                        </text>
                      </g>
                    );
                  })}

                  {/* Gradient area */}
                  <path d={areaD} fill="url(#activityAreaGrad)" />

                  {/* Line path */}
                  <path
                    d={pathD}
                    fill="none"
                    stroke="var(--lx-teal)"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />

                  {/* Data Points */}
                  {points.map((p, idx) => (
                    <g key={p.date}>
                      <circle
                        cx={p.x}
                        cy={p.y}
                        r={hoveredPoint === idx ? 5 : 3.5}
                        fill="#ffffff"
                        stroke="var(--lx-teal)"
                        strokeWidth="2"
                        style={{
                          cursor: "pointer",
                          transition: "all 120ms ease",
                        }}
                        onMouseEnter={() => setHoveredPoint(idx)}
                        onMouseLeave={() => setHoveredPoint(null)}
                      >
                        <title>{`${p.analysed} calls · ${Math.round(p.analysedSeconds / 60)} min`}</title>
                      </circle>
                      {idx % 7 === 0 && (
                        <text
                          x={p.x}
                          y={svgHeight - 8}
                          className={styles.chartLabel}
                        >
                          {formatDayLabel(p.date)}
                        </text>
                      )}
                    </g>
                  ))}
                </svg>
                {hoveredPoint !== null && points[hoveredPoint] && (
                  <div
                    className={styles.chartTooltip}
                    style={{
                      left: `${(points[hoveredPoint].x / svgWidth) * 100}%`,
                      top: `${(points[hoveredPoint].y / svgHeight) * 100}%`,
                    }}
                  >
                    {`${points[hoveredPoint].analysed} calls · ${Math.round(points[hoveredPoint].analysedSeconds / 60)} min`}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right 1/3: Call status */}
          <div className={styles.skillsCard}>
            <div className={styles.cardHeader}>
              <div>
                <h3 className={styles.cardTitle}>Call status</h3>
                <p className={styles.cardSubtitle}>
                  Saved calls by processing status
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
              <div className={styles.skillsList}>
                {/* 1. Report ready */}
                <div className={styles.skillItem}>
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillName}>Report ready</span>
                    <span className={styles.skillScore}>
                      {summary.completed}
                    </span>
                  </div>
                  <div className={styles.progressBarTrack}>
                    <div
                      className={`${styles.progressBarFill} ${styles.barMinor}`}
                      style={{
                        width: `${summary.total > 0 ? (summary.completed / summary.total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </div>

                {/* 2. In progress */}
                <div className={styles.skillItem}>
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillName}>In progress</span>
                    <span className={styles.skillScore}>
                      {summary.processing}
                    </span>
                  </div>
                  <div className={styles.progressBarTrack}>
                    <div
                      className={`${styles.progressBarFill} ${styles.barModerate}`}
                      style={{
                        width: `${summary.total > 0 ? (summary.processing / summary.total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </div>

                {/* 3. Needs attention */}
                <div className={styles.skillItem}>
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillName}>Needs attention</span>
                    <span className={styles.skillScore}>
                      {summary.needsAttention}
                    </span>
                  </div>
                  <div className={styles.progressBarTrack}>
                    <div
                      className={`${styles.progressBarFill} ${styles.barCritical}`}
                      style={{
                        width: `${summary.total > 0 ? (summary.needsAttention / summary.total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </div>

                {/* 4. Other saved calls */}
                <div className={styles.skillItem}>
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillName}>Other saved calls</span>
                    <span className={styles.skillScore}>
                      {otherSavedCalls(summary)}
                    </span>
                  </div>
                  <div className={styles.progressBarTrack}>
                    <div
                      className={`${styles.progressBarFill} ${styles.barNeutral}`}
                      style={{
                        width: `${summary.total > 0 ? (otherSavedCalls(summary) / summary.total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </div>
              </div>
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
            <div className={styles.tableWrap}>
              <table className={styles.callsTable}>
                <thead>
                  <tr>
                    <th>Call</th>
                    <th>Date</th>
                    <th>Length</th>
                    <th>Status</th>
                    <th>Open</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((call) => {
                    const tone = callTone(call);
                    const statusText = submissionState(call);
                    const statusClass =
                      tone === "ready"
                        ? styles.statusCompleted
                        : tone === "active"
                          ? styles.statusProcessing
                          : tone === "attention"
                            ? styles.statusAttention
                            : styles.statusNeutral;
                    const durationStr =
                      Number.isFinite(call.durationSeconds) &&
                      call.durationSeconds > 0
                        ? formatDuration(call.durationSeconds)
                        : "—";

                    return (
                      <tr key={call.id} className={styles.callRow}>
                        <td>
                          <div className={styles.callNameWrap}>
                            <span className={styles.callName}>
                              {call.label?.displayName ?? "Untitled call"}
                            </span>
                          </div>
                        </td>
                        <td>{formatCreatedDate(call.createdAt)}</td>
                        <td>{durationStr}</td>
                        <td>
                          <span
                            className={`${styles.statusPill} ${statusClass}`}
                          >
                            {statusText}
                          </span>
                        </td>
                        <td>
                          <Link
                            href={callHref(call.id)}
                            className={styles.openLink}
                          >
                            <span>Open</span>
                            <ArrowRight size={14} aria-hidden="true" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </LightboxShell>
  );
}
