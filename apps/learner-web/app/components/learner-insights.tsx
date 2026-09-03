"use client";

import {
  BarChart3,
  Flame,
  Info,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type AnalyticsViewResponse,
  type LearnerApi,
  type LearnerReadOptions,
  type PlanningPeriod,
} from "../lib/learner-api";

const defaultApi = createLearnerApi();

const INSUFFICIENT_SIGNAL_DISCLAIMER =
  "Descriptive product analytics only; never canonical progress, mastery, payment, entitlement, or access state.";

const PERIOD_LABELS: Record<PlanningPeriod, string> = {
  today: "Today",
  week: "This week",
  month: "This month",
};

const PERIODS: PlanningPeriod[] = ["today", "week", "month"];

type InsightsReader = (
  period?: PlanningPeriod,
  options?: LearnerReadOptions,
) => Promise<AnalyticsViewResponse>;

export type LearnerInsightsState =
  | { status: "loading" }
  | { status: "ready"; analytics: AnalyticsViewResponse }
  | { status: "error"; error: unknown };

function insufficientSignal(period: PlanningPeriod): AnalyticsViewResponse {
  return {
    status: "insufficient_signal",
    source: "descriptive_analytics_projection",
    period,
    freshness_as_of: null,
    retained_event_count: 0,
    insights: [],
    disclaimer: INSUFFICIENT_SIGNAL_DISCLAIMER,
  };
}
/**
 * Load only the read-only analytics projection. A missing route in an older
 * staging API is intentionally treated as insufficient signal, never as a
 * numeric zero or as a reason to change canonical progress.
 */
export async function loadLearnerInsightsData(
  api: LearnerApi,
  period: PlanningPeriod,
  signal?: AbortSignal,
): Promise<Extract<LearnerInsightsState, { status: "ready" }>> {
  const reader = (api as LearnerApi & { insights?: InsightsReader }).insights;
  if (typeof reader !== "function") {
    return { status: "ready", analytics: insufficientSignal(period) };
  }

  try {
    const analytics = await reader(period, { signal });
    return { status: "ready", analytics };
  } catch (error) {
    // The route is intentionally additive. If a deployment has not promoted
    // it yet, retain the honest no-signal state while preserving auth and
    // service errors for a distinct UI treatment.
    if (
      error instanceof ApiError &&
      [404, 405, 501].includes(error.status)
    ) {
      return { status: "ready", analytics: insufficientSignal(period) };
    }
    throw error;
  }
}

function freshnessLabel(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return "Freshness unavailable";
  // Keep the source timestamp stable across locales and hydration. The API
  // remains the authority for the exact timestamp if a learner needs it.
  return value.slice(0, 10);
}

function periodLabel(period: PlanningPeriod): string {
  return PERIOD_LABELS[period];
}

function analyticsErrorCopy(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) {
    return "Analytics is unavailable for this learner context.";
  }
  if (error instanceof ApiError && error.status === 401) {
    return "Your session no longer authorizes this analytics view.";
  }
  return "The descriptive analytics service could not be reached. Try again.";
}

function periodButtons(
  period: PlanningPeriod,
  onChange: (next: PlanningPeriod) => void,
) {
  return PERIODS.map((item) => (
    <button
      className={`analytics-period-button${item === period ? " is-active" : ""}`}
      key={item}
      type="button"
      aria-pressed={item === period}
      onClick={() => onChange(item)}
    >
      {periodLabel(item)}
    </button>
  ));
}

function AnalyticsMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="analytics-metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
export function LearnerInsightsPanel({
  state,
  period,
  onPeriodChange,
  onRetry,
}: {
  state: LearnerInsightsState;
  period: PlanningPeriod;
  onPeriodChange: (period: PlanningPeriod) => void;
  onRetry: () => void;
}) {
  const analytics =
    state.status === "ready" ? state.analytics : insufficientSignal(period);
  const hasSignals = Boolean(
    analytics?.status === "available" && analytics.retained_event_count > 0,
  );
  const disclaimer = analytics?.disclaimer || INSUFFICIENT_SIGNAL_DISCLAIMER;

  return (
    <section
      className="analytics-insight-panel"
      aria-labelledby="learner-insights-title"
      data-analytics-scope="descriptive"
    >
      <header className="analytics-insight-panel__header">
        <div>
          <p className="kicker">Descriptive telemetry</p>
          <h2 id="learner-insights-title">Learning rhythm</h2>
          <p className="analytics-insight-panel__lede">
            Activity patterns are presented here without changing your course
            progress or access.
          </p>
        </div>
        <span className="analytics-readonly-badge">
          <BarChart3 size={14} aria-hidden="true" /> Read-only
        </span>
      </header>

      <div className="analytics-insight-panel__toolbar">
        <div
          className="analytics-period-picker"
          role="group"
          aria-label="Analytics period"
        >
          {periodButtons(period, onPeriodChange)}
        </div>
        <span className="analytics-source-label">
          Source: descriptive analytics projection
        </span>
      </div>

      {state.status === "loading" ? (
        <div className="analytics-read-state" role="status" aria-live="polite">
          <span className="analytics-loading-mark" aria-hidden="true">
            <Sparkles size={18} />
          </span>
          <div>
            <strong>Checking your activity signals</strong>
            <p>Only consented descriptive events can appear here.</p>
          </div>
        </div>
      ) : state.status === "error" ? (
        <div className="analytics-read-state analytics-read-state--error" role="alert">
          <span className="analytics-loading-mark" aria-hidden="true">
            <Info size={18} />
          </span>
          <div>
            <strong>Analytics unavailable</strong>
            <p>{analyticsErrorCopy(state.error)}</p>
            <button className="button button--outline" type="button" onClick={onRetry}>
              <RefreshCw size={15} aria-hidden="true" /> Retry
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="analytics-insight-panel__overview">
            <article
              className={`analytics-streak-card${hasSignals ? " analytics-streak-card--available" : ""}`}
              aria-label="Descriptive streak and rhythm preview"
            >
              <span className="analytics-streak-card__icon" aria-hidden="true">
                <Flame size={22} />
              </span>
              <div>
                <p className="analytics-card-kicker">Streak / rhythm</p>
                <strong>{hasSignals ? "Signal available" : "No signal yet"}</strong>
                <p>
                  {hasSignals
                    ? `A descriptive activity signal was observed for ${periodLabel(period).toLowerCase()}.`
                    : "A streak preview appears only when consented activity signals are retained."}
                </p>
              </div>
            </article>

            <dl className="analytics-metric-grid">
              <AnalyticsMetric
                label="Signals observed"
                value={
                  hasSignals
                    ? Math.max(0, Math.round(analytics.retained_event_count)).toLocaleString("en-US")
                    : "—"
                }
              />
              <AnalyticsMetric
                label="Observed through"
                value={freshnessLabel(analytics.freshness_as_of)}
              />
            </dl>
          </div>

          {analytics.insights.length > 0 ? (
            <div className="analytics-insight-list">
              <div className="analytics-insight-list__heading">
                <p className="analytics-card-kicker">What the signal says</p>
                <span>{periodLabel(period)}</span>
              </div>
              <ul>
                {analytics.insights.map((insight) => (
                  <li key={insight.id}>
                    <span className="analytics-insight-list__marker" aria-hidden="true">
                      <Sparkles size={15} />
                    </span>
                    <div>
                      <strong>{insight.title}</strong>
                      <p>{insight.detail}</p>
                      <span className="analytics-insight-list__source">
                        Source events: {insight.source_event_names.join(", ") || "Not reported"}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="analytics-no-signal-copy">
              <span aria-hidden="true">
                <Sparkles size={16} />
              </span>
              <p>
                {hasSignals
                  ? "Signals are present, but no descriptive insight is available for this period."
                  : "No descriptive activity signals are available for this period yet."}
              </p>
            </div>
          )}
        </>
      )}

      <p className="analytics-disclaimer">
        <Info size={14} aria-hidden="true" />
        <span>{disclaimer}</span>
      </p>
    </section>
  );
}

export function LearnerInsightsRuntime({ api = defaultApi }: { api?: LearnerApi }) {
  const [period, setPeriod] = useState<PlanningPeriod>("week");
  const [state, setState] = useState<LearnerInsightsState>({ status: "loading" });
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(
    (requestedPeriod: PlanningPeriod) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const generation = ++generationRef.current;
      const isCurrent = () =>
        mountedRef.current &&
        generationRef.current === generation &&
        !controller.signal.aborted;
      setState({ status: "loading" });
      void loadLearnerInsightsData(api, requestedPeriod, controller.signal).then(
        (ready) => {
          if (isCurrent()) setState(ready);
        },
        (error: unknown) => {
          if (isCurrent() && !isAbortError(error)) {
            setState({ status: "error", error });
          }
        },
      );
    },
    [api],
  );

  useEffect(() => {
    mountedRef.current = true;
    queueMicrotask(() => {
      if (mountedRef.current) load("week");
    });
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      abortRef.current?.abort();
    };
  }, [load]);

  const handlePeriodChange = useCallback(
    (next: PlanningPeriod) => {
      if (next === period) return;
      setPeriod(next);
      load(next);
    },
    [load, period],
  );

  return (
    <LearnerInsightsPanel
      state={state}
      period={period}
      onPeriodChange={handlePeriodChange}
      onRetry={() => load(period)}
    />
  );
}
