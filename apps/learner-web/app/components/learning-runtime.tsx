"use client";

import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  FileText,
  LockKeyhole,
  PencilLine,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityRow,
  ModuleCard,
  NextActionCard,
  ProgressMeter,
  RouteHeader,
} from "@ac/ui";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type LearningResponse,
  type MeResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
  type OfflineReadMetadata,
} from "../lib/offline-read-cache";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";
import { useInvalidateDraftsWithoutMembership } from "./learner-runtime";
import { LearningSkeleton } from "./skeletons";

const defaultApi = createLearnerApi();
export const FREE_COURSE_SLUG = "authority-closers-free-course";

function activityKindIcon(kind: string) {
  const k = kind.toLowerCase();
  if (k.includes("video") || k.includes("watch"))
    return <Play size={18} aria-hidden="true" />;
  if (k.includes("reflect")) return <PencilLine size={18} aria-hidden="true" />;
  if (k.includes("implement") || k.includes("challenge"))
    return <Sparkles size={18} aria-hidden="true" />;
  if (k.includes("review")) return <ShieldCheck size={18} aria-hidden="true" />;
  if (k.includes("improve")) return <RotateCcw size={18} aria-hidden="true" />;
  return <FileText size={18} aria-hidden="true" />;
}

export function isActivityActionable(
  activity: LearningResponse["modules"][number]["activities"][number],
): boolean {
  const state = activity.state.toLowerCase();
  return (
    (state === "in_progress" || state === "available") &&
    activity.allowed_actions.length > 0
  );
}

function activityStateLabel(state: string): string {
  return state
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export async function loadLearningData(
  api: LearnerApi,
  signal?: AbortSignal,
): Promise<{
  me: MeResponse;
  learning: LearningResponse | null;
  offlineRead?: OfflineReadMetadata;
}> {
  const me = await api.me({ signal });
  if (!hasMembershipRole(me)) {
    return {
      me,
      learning: null,
      offlineRead: getEarliestOfflineReadMetadata(me) ?? undefined,
    };
  }

  const programs = await api.listPrograms(50, { signal });
  const freeCourse = programs.items.find((p) => p.slug === FREE_COURSE_SLUG);
  if (!freeCourse) {
    return {
      me,
      learning: null,
      offlineRead: getEarliestOfflineReadMetadata(me, programs) ?? undefined,
    };
  }

  try {
    const learning = await api.learning(freeCourse.id, undefined, { signal });
    return {
      me,
      learning,
      offlineRead:
        getEarliestOfflineReadMetadata(me, programs, learning) ?? undefined,
    };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return {
        me,
        learning: null,
        offlineRead: getEarliestOfflineReadMetadata(me, programs) ?? undefined,
      };
    }
    throw err;
  }
}

export function LearningViewRuntime({
  api = defaultApi,
}: {
  api?: LearnerApi;
}) {
  const [learning, setLearning] = useState<LearningResponse | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [offlineRead, setOfflineRead] = useState<
    OfflineReadMetadata | undefined
  >();
  const [activeModuleId, setActiveModuleId] = useState<string | null>(null);
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const membershipKnown = me !== null;
  const membershipAvailable = me !== null && hasMembershipRole(me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    membershipKnown,
    membershipAvailable,
    me?.person_id ?? null,
  );

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const generation = ++generationRef.current;
    const isCurrent = () =>
      mountedRef.current &&
      generationRef.current === generation &&
      !controller.signal.aborted;

    setLoading(true);
    setError(null);
    setLearning(null);
    setOfflineRead(undefined);
    setActiveModuleId(null);
    try {
      const result = await loadLearningData(api, controller.signal);
      if (!isCurrent()) return;
      setMe(result.me);
      setLearning(result.learning);
      setOfflineRead(result.offlineRead);
      setActiveModuleId(result.learning?.modules[0]?.id ?? null);
    } catch (err) {
      if (isAbortError(err) || !isCurrent()) return;
      setError(err);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    mountedRef.current = true;
    void Promise.resolve().then(() => {
      if (mountedRef.current) void load();
    });
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      abortRef.current?.abort();
    };
  }, [load]);

  if (loading) {
    return <LearningSkeleton />;
  }

  if (error) {
    const is401 = error instanceof ApiError && error.status === 401;
    const is403 = error instanceof ApiError && error.status === 403;
    return (
      <div className="surface-state surface-state--error-terminal" role="alert">
        <h1>
          {is401
            ? "Sign in to view your learning"
            : is403
              ? "Learner access is unavailable"
              : "Could not load curriculum"}
        </h1>
        <p>
          {is401
            ? "Your session has expired. Sign in again to view your courses."
            : is403
              ? "This account is not authorized to view this curriculum."
              : userFacingRequestError(
                  error,
                  "The learning service could not be reached. Try again.",
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

  if (!me || !hasMembershipRole(me)) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }

  if (!learning) {
    return (
      <div className="learning-empty-view">
        {offlineRead ? (
          <div
            className="offline-read-notice"
            id="learning-offline-read"
            role="status"
          >
            {offlineReadNotice(offlineRead)}
          </div>
        ) : null}
        <section
          className="card empty-learning-card"
          aria-labelledby="empty-learning-title"
        >
          <div className="empty-icon-circle" aria-hidden="true">
            <BookOpen size={28} />
          </div>
          <h1 id="empty-learning-title" className="empty-title">
            No active course enrollments yet
          </h1>
          <p className="empty-description">
            Browse the published catalog to find a course available for this
            learner workspace.
          </p>
          <div className="empty-actions">
            <Link className="button button--cobalt" href={ROUTES.dashboard}>
              Go to Dashboard <ArrowRight size={16} aria-hidden="true" />
            </Link>
            <Link className="button button--outline" href={ROUTES.discover}>
              Browse Discover
            </Link>
          </div>
        </section>
      </div>
    );
  }

  const percentage = Number.isFinite(learning.projection.percentage)
    ? Math.round(Math.min(1, Math.max(0, learning.projection.percentage)) * 100)
    : null;
  const progressDetail =
    Number.isFinite(learning.projection.completed_count) &&
    Number.isFinite(learning.projection.denominator) &&
    learning.projection.completed_count >= 0 &&
    learning.projection.denominator >= 0
      ? `${learning.projection.completed_count} of ${learning.projection.denominator} activities complete`
      : "Progress is unavailable until the learning service can provide it.";
  const moduleOne = learning.modules[0];
  const nextActivity = learning.modules
    .flatMap((module) => module.activities)
    .find(isActivityActionable);

  return (
    <div className="learning-view">
      {/* Course Hero & Progression Summary */}
      <RouteHeader
        className="learning-header"
        title={learning.program_title}
        titleId="course-heading"
        titleClassName="learning-title"
        breadcrumbs={
          <div className="learning-breadcrumbs" aria-label="Breadcrumb">
            <Link href={ROUTES.dashboard}>Dashboard</Link>
            <span aria-hidden="true">/</span>
            <span>My Learning</span>
          </div>
        }
        eyebrow={
          <span className="card-badge card-badge--primary">
            Enrolled Course
          </span>
        }
        description={
          "Review the published modules and follow the activity states returned for your enrollment."
        }
        descriptionClassName="learning-subhead"
        aside={
          <div className="learning-header__stats">
            <div className="learning-stat-box">
              <ProgressMeter
                value={percentage}
                label="Progress"
                detail={progressDetail}
              />
            </div>
          </div>
        }
      />

      {offlineRead ? (
        <div
          className="offline-read-notice"
          id="learning-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}

      {nextActivity && !offlineRead ? (
        <NextActionCard
          className="learning-next-action"
          eyebrow="Next action"
          title={nextActivity.title}
          detail="Open the next server-authorized activity in your published learning path."
          action={
            <Link
              className="button button--cobalt"
              href={ROUTES.activity(nextActivity.id)}
            >
              Open activity <ArrowRight size={16} aria-hidden="true" />
            </Link>
          }
        />
      ) : null}

      {/* Direction B: Skill Journey Stepper */}
      <section
        className="card skill-journey-card"
        aria-labelledby="skill-journey-title"
      >
        <div className="skill-journey-header">
          <div>
            <span className="card-badge card-badge--neutral">
              {moduleOne
                ? `Module ${moduleOne.position} Journey`
                : "Course journey"}
            </span>
            <h2 id="skill-journey-title" className="skill-journey-title">
              {moduleOne ? moduleOne.title : "Published course activities"}
            </h2>
          </div>
          <span className="skill-journey-count">
            {moduleOne?.activities.length ?? 0}{" "}
            {moduleOne?.activities.length === 1 ? "activity" : "activities"}
          </span>
        </div>

        <div
          className="skill-journey-chain"
          role="list"
          aria-label={
            moduleOne
              ? `Module ${moduleOne.position} activity sequence`
              : "Course activity sequence"
          }
        >
          {moduleOne?.activities.map((act, index) => {
            const state = act.state.toLowerCase();
            const isCompleted = state === "completed";
            const isLocked = state === "locked";
            const isActionable = isActivityActionable(act);
            const canOpen = !offlineRead && (isCompleted || isActionable);

            return (
              <div
                key={act.id}
                role="listitem"
                className={`journey-step journey-step--${state}`}
              >
                {/* Step Connector Line */}
                {index < moduleOne.activities.length - 1 ? (
                  <div
                    className={`journey-step__connector${isCompleted ? " is-completed" : ""}`}
                    aria-hidden="true"
                  />
                ) : null}

                {/* Step Circle Indicator */}
                <div className="journey-step__indicator">
                  {isCompleted ? (
                    <span
                      className="step-circle step-circle--completed"
                      aria-label="Completed"
                    >
                      <CheckCircle2 size={20} aria-hidden="true" />
                    </span>
                  ) : isLocked ? (
                    <span
                      className="step-circle step-circle--locked"
                      aria-label="Locked"
                    >
                      <LockKeyhole size={16} aria-hidden="true" />
                    </span>
                  ) : (
                    <span
                      className="step-circle step-circle--active"
                      aria-label="Active"
                    >
                      0{index + 1}
                    </span>
                  )}
                </div>

                {/* Step Content */}
                <div className="journey-step__body">
                  <div className="journey-step__header-row">
                    <span className="journey-step__index">
                      Step 0{index + 1}
                    </span>
                    {isCompleted ? (
                      <span className="step-pill step-pill--done">
                        Completed
                      </span>
                    ) : isLocked ? (
                      <span className="step-pill step-pill--locked">
                        Locked
                      </span>
                    ) : isActionable ? (
                      <span className="step-pill step-pill--active">
                        Ready to practice
                      </span>
                    ) : (
                      <span className="step-pill step-pill--locked">
                        {activityStateLabel(act.state)}
                      </span>
                    )}
                  </div>

                  <h3 className="journey-step__title">{act.title}</h3>
                  <p className="journey-step__prompt">
                    {act.prompt
                      ? act.prompt
                      : "No activity prompt is available."}
                  </p>

                  {isLocked ? (
                    <p className="journey-step__lock-msg" role="status">
                      <LockKeyhole size={14} aria-hidden="true" />
                      {act.explanation.reason ||
                        "This activity remains locked by the learning service."}
                    </p>
                  ) : canOpen ? (
                    <div className="journey-step__actions">
                      <Link
                        href={ROUTES.activity(act.id)}
                        className={`button button--small ${isCompleted ? "button--outline" : "button--cobalt"}`}
                      >
                        {isCompleted ? "Review activity" : "Start activity"}
                        <ArrowRight size={14} aria-hidden="true" />
                      </Link>
                    </div>
                  ) : (
                    <p className="journey-step__lock-msg" role="status">
                      {offlineRead
                        ? "Reconnect to open this activity."
                        : activityStateLabel(act.state)}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Curriculum Modules Overview */}
      <section
        className="dashboard-section"
        aria-labelledby="curriculum-overview-title"
      >
        <h2 id="curriculum-overview-title" className="section-title">
          All Course Modules
        </h2>

        <div className="curriculum-module-stack ac-module-stack">
          {learning.modules.map((mod) => {
            const isCurrent = mod.id === activeModuleId;
            const completedCount = mod.activities.filter(
              (activity) => activity.state.toLowerCase() === "completed",
            ).length;
            const moduleStatus =
              mod.activities.length === 0
                ? "No published activities"
                : completedCount === mod.activities.length
                  ? "Complete"
                  : mod.activities.some((activity) =>
                        ["in_progress", "available"].includes(
                          activity.state.toLowerCase(),
                        ),
                      )
                    ? "In progress"
                    : mod.activities.some(
                          (activity) =>
                            activity.state.toLowerCase() === "awaiting_review",
                        )
                      ? "Awaiting review"
                      : mod.activities.every(
                            (activity) =>
                              activity.state.toLowerCase() === "locked",
                          )
                        ? "Locked"
                        : "Published";

            return (
              <ModuleCard
                key={mod.id}
                className={`card curriculum-module-card${isCurrent ? " is-expanded" : ""}`}
                title={mod.title}
                titleId={`learning-module-${mod.id}-title`}
                position={`Module ${mod.position}`}
                status={
                  <span className="module-meta-status">{moduleStatus}</span>
                }
                header={
                  <div className="curriculum-module-header">
                    <h3
                      id={`learning-module-${mod.id}-title`}
                      className="curriculum-module-heading"
                    >
                      <button
                        type="button"
                        className="curriculum-module-toggle"
                        aria-expanded={isCurrent}
                        aria-controls={`learning-module-${mod.id}-content`}
                        aria-label={`${isCurrent ? "Collapse" : "Expand"} module ${mod.position}: ${mod.title}`}
                        onClick={() =>
                          setActiveModuleId(isCurrent ? null : mod.id)
                        }
                      >
                        <span className="curriculum-module-header__left">
                          <span className="module-index-badge">
                            0{mod.position}
                          </span>
                          <span>
                            <span className="module-title">{mod.title}</span>
                            <span className="module-meta">
                              {mod.activities.length}{" "}
                              {mod.activities.length === 1
                                ? "activity"
                                : "activities"}{" "}
                              · {moduleStatus}
                            </span>
                          </span>
                        </span>
                        <ChevronDown
                          className={`module-chevron${isCurrent ? " is-rotated" : ""}`}
                          size={20}
                          aria-hidden="true"
                        />
                      </button>
                    </h3>
                  </div>
                }
              >
                {isCurrent ? (
                  <div
                    className="curriculum-module-body"
                    id={`learning-module-${mod.id}-content`}
                  >
                    {mod.activities.length > 0 ? (
                      <ol className="module-activity-list ac-activity-list">
                        {mod.activities.map((act) => (
                          <ActivityRow
                            key={act.id}
                            className="module-activity-row"
                            position={String(act.position).padStart(2, "0")}
                            icon={
                              <span
                                className="activity-icon-wrapper"
                                aria-hidden="true"
                              >
                                {activityKindIcon(act.kind)}
                              </span>
                            }
                            eyebrow={act.kind.replaceAll("_", " ")}
                            title={act.title}
                            ariaLabel={`${act.position}. ${act.title}, ${activityStateLabel(act.state)}`}
                            disabled={act.state.toLowerCase() === "locked"}
                            status={
                              act.state.toLowerCase() === "locked" ? (
                                <span className="status-pill status-pill--locked">
                                  <LockKeyhole size={12} aria-hidden="true" />{" "}
                                  Locked
                                </span>
                              ) : null
                            }
                            action={
                              act.state.toLowerCase() ===
                              "locked" ? null : !offlineRead &&
                                (isActivityActionable(act) ||
                                  act.state.toLowerCase() === "completed") ? (
                                <Link
                                  className="button button--small button--outline"
                                  href={ROUTES.activity(act.id)}
                                >
                                  Open
                                </Link>
                              ) : (
                                <span className="status-pill status-pill--locked">
                                  {offlineRead
                                    ? "Reconnect to open"
                                    : activityStateLabel(act.state)}
                                </span>
                              )
                            }
                          />
                        ))}
                      </ol>
                    ) : (
                      <div className="module-empty-state">
                        <p>
                          No activities are currently available in this module.
                        </p>
                      </div>
                    )}
                  </div>
                ) : null}
              </ModuleCard>
            );
          })}
        </div>
      </section>
    </div>
  );
}
