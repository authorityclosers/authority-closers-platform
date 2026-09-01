"use client";

import { ArrowRight, BarChart3, LockKeyhole } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  type LearningResponse,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import {
  activityLockReason,
  identityState,
  LearningActivityNavigation,
} from "./learner-runtime";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";

type ProgressState =
  | { status: "loading" }
  | {
      status: "ready";
      membershipAvailable: boolean;
      learning?: LearningResponse;
    }
  | { status: "error"; error: unknown };

export function ProgressRuntime() {
  const [state, setState] = useState<ProgressState>({ status: "loading" });

  function load() {
    setState({ status: "loading" });
    void identityState(createLearnerApi()).then(
      (identity) =>
        setState({
          status: "ready",
          membershipAvailable: hasMembershipRole(identity.me),
          learning: identity.learning,
        }),
      (error: unknown) => setState({ status: "error", error }),
    );
  }

  useEffect(() => {
    queueMicrotask(load);
  }, []);

  if (state.status === "loading") {
    return (
      <div className="surface-state" role="status">
        <h1>Loading your progress…</h1>
      </div>
    );
  }

  if (state.status === "error") {
    const sessionExpired =
      state.error instanceof ApiError && state.error.status === 401;
    return (
      <div className="surface-state" role="alert">
        <h1>Progress could not load.</h1>
        <p>
          {sessionExpired
            ? "Your session has expired. Sign in again to continue."
            : "The progress service could not be reached. Try again."}
        </p>
        {sessionExpired ? (
          <Link className="button button--ink" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        ) : (
          <button
            className="button button--outline"
            type="button"
            onClick={load}
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!state.membershipAvailable) {
    return <MembershipUnavailable />;
  }

  if (!state.learning) {
    return (
      <section className="progress-empty" aria-labelledby="progress-title">
        <span className="progress-empty__icon" aria-hidden="true">
          <BarChart3 size={24} />
        </span>
        <p className="eyebrow">Progress</p>
        <h1 id="progress-title">Start the Free Course to track progress.</h1>
        <p>
          Progress appears after the enrollment service authorizes your course.
        </p>
        <Link
          className="button button--ink"
          href={`${ROUTES.learnerHome}#continue-learning`}
        >
          Go to Free Course <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </section>
    );
  }

  const learning = state.learning;
  const percentage = Math.round(
    Math.min(1, Math.max(0, learning.projection.percentage)) * 100,
  );

  return (
    <>
      <header className="progress-heading">
        <p className="eyebrow">Your progress</p>
        <h1>{learning.program_title}</h1>
        <p>
          Completion and access below reflect your current enrolled course
          version.
        </p>
      </header>
      <section
        className="progress-summary"
        aria-label="Course progress summary"
      >
        <div className="progress-summary__number">
          <strong>{percentage}%</strong>
          <span>complete</span>
        </div>
        <dl>
          <div>
            <dt>Completed</dt>
            <dd>{learning.projection.completed_count}</dd>
          </div>
          <div>
            <dt>Required</dt>
            <dd>{learning.projection.denominator}</dd>
          </div>
          <div>
            <dt>Course version</dt>
            <dd>{learning.version_number}</dd>
          </div>
        </dl>
        <Link
          className="button button--ink"
          href={ROUTES.programLearning(learning.program_slug)}
        >
          Open course <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </section>
      <section
        className="progress-modules"
        aria-labelledby="module-progress-title"
      >
        <div className="course-outline__heading">
          <div>
            <p className="kicker">Module detail</p>
            <h2 id="module-progress-title">Activity progress</h2>
          </div>
        </div>
        {learning.modules.map((module) => {
          const completed = module.activities.filter(
            (activity) => activity.state.toLowerCase() === "completed",
          ).length;
          const firstLocked = module.activities.find(
            (activity) => activity.state.toLowerCase() === "locked",
          );
          return (
            <article className="progress-card" key={module.id}>
              <div className="progress-card__heading">
                <div>
                  <p className="kicker">Module {module.position}</p>
                  <h2>{module.title}</h2>
                </div>
                <strong>
                  {completed}/{module.activities.length}
                </strong>
              </div>
              {module.activities.length > 0 ? (
                <ol className="activity-list">
                  {module.activities.map((activity) => (
                    <LearningActivityNavigation
                      activity={activity}
                      key={activity.id}
                    />
                  ))}
                </ol>
              ) : (
                <p className="module-card__empty">
                  No activities are published in this module yet.
                </p>
              )}
              {firstLocked ? (
                <p className="progress-card__lock">
                  <LockKeyhole size={14} aria-hidden="true" />
                  {activityLockReason(firstLocked)}
                </p>
              ) : null}
            </article>
          );
        })}
      </section>
    </>
  );
}
