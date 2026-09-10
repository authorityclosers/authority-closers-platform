"use client";

import { ArrowRight, BarChart3, ChevronDown, LockKeyhole } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type LearningCollectionResponse,
  type LearningResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
  type OfflineReadMetadata,
} from "../lib/offline-read-cache";
import { ROUTES } from "../lib/routes";
import {
  activityLockReason,
  identityState,
  LearningActivityNavigation,
  useInvalidateDraftsWithoutMembership,
} from "./learner-runtime";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";
import { LearnerInsightsRuntime } from "./learner-insights";
import { ProgressScopePanel } from "./progress-momentum";
import { ProgressSkeleton } from "./skeletons";
import styles from "./progress-runtime.module.css";

type ProgressState =
  | { status: "loading" }
  | {
      status: "ready";
      membershipAvailable: boolean;
      personId: string;
      learning?: LearningResponse;
      learningCollection?: LearningCollectionResponse;
      offlineRead?: OfflineReadMetadata;
    }
  | { status: "error"; error: unknown };

const defaultApi = createLearnerApi();

function isUnsupportedLearningCollectionError(error: unknown): boolean {
  return error instanceof ApiError && [404, 405, 501].includes(error.status);
}

export function shouldIgnoreProgressLoadError(error: unknown): boolean {
  return isAbortError(error);
}

export async function loadProgressData(
  api: LearnerApi,
  signal?: AbortSignal,
): Promise<Extract<ProgressState, { status: "ready" }>> {
  const identity = await identityState(api, undefined, signal);

  let learningCollection: LearningCollectionResponse | undefined;

  if (hasMembershipRole(identity.me)) {
    try {
      learningCollection = await api.learningCollection(50, { signal });
    } catch (error) {
      if (isAbortError(error)) throw error;
      // A not-yet-promoted collection route is optional. Authentication,
      // authorization, service, and network failures remain actionable route
      // errors so the controlled recovery UI can preserve their meaning.
      if (!isUnsupportedLearningCollectionError(error)) throw error;
    }
  }

  return {
    status: "ready",
    membershipAvailable: hasMembershipRole(identity.me),
    personId: identity.me.person_id,
    learning: identity.learning,
    learningCollection,
    offlineRead:
      getEarliestOfflineReadMetadata(
        identity.me,
        identity.programs,
        identity.learning,
        learningCollection,
      ) ?? undefined,
  };
}

export function ProgressRuntime({ api = defaultApi }: { api?: LearnerApi }) {
  const [state, setState] = useState<ProgressState>({ status: "loading" });
  const [showInsights, setShowInsights] = useState(false);
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const membershipKnown = state.status === "ready";
  const membershipAvailable =
    state.status === "ready" && state.membershipAvailable;
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    membershipKnown,
    membershipAvailable,
    state.status === "ready" ? state.personId : null,
  );

  const load = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const generation = ++generationRef.current;
    const isCurrent = () =>
      mountedRef.current &&
      generationRef.current === generation &&
      !controller.signal.aborted;
    setState({ status: "loading" });
    void loadProgressData(api, controller.signal).then(
      (ready) => {
        if (isCurrent()) setState(ready);
      },
      (error: unknown) => {
        if (isCurrent() && !shouldIgnoreProgressLoadError(error)) {
          setState({ status: "error", error });
        }
      },
    );
  }, [api]);

  useEffect(() => {
    mountedRef.current = true;
    queueMicrotask(() => {
      if (mountedRef.current) load();
    });
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      abortRef.current?.abort();
    };
  }, [load]);

  if (state.status === "loading") {
    return <ProgressSkeleton />;
  }

  if (state.status === "error") {
    const sessionExpired =
      state.error instanceof ApiError && state.error.status === 401;
    const accessUnavailable =
      state.error instanceof ApiError && state.error.status === 403;
    return (
      <div className="surface-state surface-state--error-terminal" role="alert">
        <h1>
          {sessionExpired
            ? "Sign in to view your progress"
            : accessUnavailable
              ? "Progress access is unavailable"
              : "Progress could not load"}
        </h1>
        <p>
          {sessionExpired
            ? "Your session has expired. Sign in again to continue."
            : accessUnavailable
              ? "This account is not authorized to view learner progress."
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
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }

  if (!state.learning) {
    return (
      <section className="progress-empty" aria-labelledby="progress-title">
        {state.offlineRead ? (
          <div
            className="offline-read-notice"
            id="progress-offline-read"
            role="status"
          >
            {offlineReadNotice(state.offlineRead)}
          </div>
        ) : null}
        <span className="progress-empty__icon" aria-hidden="true">
          <BarChart3 size={24} />
        </span>
        <p className="eyebrow">Progress</p>
        <h1 id="progress-title">Start the Free Course to track progress.</h1>
        <p>
          Join a course to see the steps you’ve completed and what comes next.
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

  return (
    <>
      {state.offlineRead ? (
        <div
          className="offline-read-notice"
          id="progress-offline-read"
          role="status"
        >
          {offlineReadNotice(state.offlineRead)}
        </div>
      ) : null}
      <header className="progress-heading">
        <p className="eyebrow">Your learning</p>
        <h1>Every step moves you forward.</h1>
        <p>See what you’ve completed. Find your next step.</p>
      </header>
      <ProgressScopePanel
        learning={learning}
        collection={state.learningCollection}
      />
      <section
        className="progress-modules"
        aria-labelledby="module-progress-title"
      >
        <div className="course-outline__heading">
          <div>
            <h2 id="module-progress-title">Your course path</h2>
            <p className={styles.subtitle}>Open a module to see each step.</p>
          </div>
        </div>
        {learning.modules.map((module, index) => {
          const completed = module.activities.filter(
            (activity) => activity.state.toLowerCase() === "completed",
          ).length;
          const firstLocked = module.activities.find(
            (activity) => activity.state.toLowerCase() === "locked",
          );
          return (
            <details
              className={`progress-card ${styles.module}`}
              key={module.id}
              open={index === 0}
            >
              <summary
                className={`progress-card__heading ${styles.moduleSummary}`}
              >
                <div>
                  <p className="kicker">Module {module.position}</p>
                  <h3>{module.title}</h3>
                </div>
                <strong>
                  {module.activities.length
                    ? `${completed}/${module.activities.length}`
                    : "Coming soon"}
                </strong>
                <ChevronDown
                  size={18}
                  className={styles.chevron}
                  aria-hidden="true"
                />
              </summary>
              {module.activities.length > 0 ? (
                <ol className="activity-list">
                  {module.activities.map((activity) => (
                    <LearningActivityNavigation
                      activity={activity}
                      disabled={Boolean(state.offlineRead)}
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
            </details>
          );
        })}
      </section>
      <section className={styles.insights}>
        <button
          type="button"
          className={styles.insightToggle}
          aria-expanded={showInsights}
          aria-controls="progress-activity-insights"
          onClick={() => setShowInsights(!showInsights)}
        >
          <BarChart3 size={19} aria-hidden="true" />
          <span>
            Activity insights
            <small>
              Explore your learning activity separately from course completion.
            </small>
          </span>
          <ChevronDown size={18} aria-hidden="true" />
        </button>
        <div id="progress-activity-insights" hidden={!showInsights}>
          {showInsights ? <LearnerInsightsRuntime api={api} /> : null}
        </div>
      </section>
    </>
  );
}
