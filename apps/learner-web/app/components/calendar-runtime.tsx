"use client";

import { ArrowRight, CalendarDays, Check, Clock3 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type CalendarResponse,
  type LearnerApi,
  type LearningPlanResponse,
  type PlanningPeriod,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";

const defaultApi = createLearnerApi();
const PERIODS: PlanningPeriod[] = ["today", "week", "month"];
const PERIOD_LABELS: Record<PlanningPeriod, string> = {
  today: "Today",
  week: "This week",
  month: "This month",
};

function explicitDateLabel(value: string | null): string {
  return value ? `Planned for ${value}` : "No date assigned";
}

function PlanCard({ plan }: { plan: LearningPlanResponse }) {
  return (
    <section
      className="calendar-period-card card"
      aria-labelledby={`calendar-${plan.period}-title`}
    >
      <div className="calendar-period-card__header">
        <div>
          <span className="card-badge card-badge--neutral">
            {PERIOD_LABELS[plan.period]}
          </span>
          <h2 id={`calendar-${plan.period}-title`}>
            {plan.status === "available"
              ? `${plan.items.length} planned ${plan.items.length === 1 ? "item" : "items"}`
              : "No plan configured"}
          </h2>
        </div>
        <CalendarDays size={22} aria-hidden="true" />
      </div>

      {plan.status === "available" ? (
        <ul className="calendar-plan-list">
          {plan.items.map((item) => (
            <li className="calendar-plan-item" key={item.id}>
              <span
                className={`calendar-plan-item__icon${item.state === "completed" ? " is-complete" : ""}`}
                aria-hidden="true"
              >
                {item.state === "completed" ? (
                  <Check size={14} />
                ) : (
                  <Clock3 size={14} />
                )}
              </span>
              <div className="calendar-plan-item__copy">
                <strong>{item.title}</strong>
                <span>{explicitDateLabel(item.planned_for)}</span>
              </div>
              {item.activity_id ? (
                <Link
                  className="button button--small button--outline"
                  href={ROUTES.activity(item.activity_id)}
                >
                  Open <ArrowRight size={14} aria-hidden="true" />
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="calendar-period-card__empty" role="status">
          {plan.message ?? "No explicit learning plan items are available."}
        </p>
      )}
    </section>
  );
}

export function CalendarRuntime({ api = defaultApi }: { api?: LearnerApi }) {
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const mountedRef = useRef(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const result = await api.calendar({ signal });
        if (!mountedRef.current) return;
        setData(result);
      } catch (err) {
        if (isAbortError(err) || !mountedRef.current) return;
        setError(err);
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [api],
  );

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    void load(controller.signal);
    return () => {
      mountedRef.current = false;
      controller.abort();
    };
  }, [load]);

  if (loading) {
    return (
      <div className="calendar-loading" role="status">
        Loading your calendar…
      </div>
    );
  }

  if (error) {
    const is401 = error instanceof ApiError && error.status === 401;
    const is403 = error instanceof ApiError && error.status === 403;
    return (
      <div className="surface-state surface-state--error-terminal" role="alert">
        <h1>
          {is401
            ? "Sign in to view your calendar"
            : is403
              ? "Calendar access is unavailable"
              : "Calendar could not load"}
        </h1>
        <p>
          {is401
            ? "Your session has expired. Sign in again to view explicit plan items."
            : is403
              ? "This account is not authorized to view this learner calendar."
              : userFacingRequestError(
                  error,
                  "The calendar service could not be reached.",
                )}
        </p>
        {is401 ? (
          <Link className="button button--ink" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        ) : (
          <button
            className="button button--outline"
            type="button"
            onClick={() => void load()}
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="calendar-view">
      <header className="calendar-header" aria-labelledby="calendar-title">
        <div>
          <p className="eyebrow">Planning workspace</p>
          <h1 id="calendar-title">Calendar</h1>
          <p>
            Review only the learning plan items explicitly published for your
            learner workspace.
          </p>
        </div>
        <CalendarDays size={42} aria-hidden="true" />
      </header>

      <div className="calendar-disclaimer" role="note">
        {data.disclaimer}
      </div>

      <div className="calendar-period-grid">
        {PERIODS.map((period) => (
          <PlanCard key={period} plan={data.periods[period]} />
        ))}
      </div>
    </div>
  );
}
