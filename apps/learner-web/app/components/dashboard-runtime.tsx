"use client";

import {
  ArrowRight,
  BookOpen,
  ChevronRight,
  Compass,
  Edit3,
  FileText,
  MessageSquare,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type LearningActivityResponse,
  type LearningResponse,
  type MeResponse,
  type ProgramSummaryResponse,
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
import { DashboardSkeleton } from "./skeletons";

const defaultApi = createLearnerApi();
export const FREE_COURSE_SLUG = "authority-closers-free-course";

const PRESENTATION_ARTWORK = [
  "/media/ac-course-hero-v1.png",
  "/media/ac-module-conversation-v1.png",
  "/media/ac-module-presentation-v1.png",
] as const;

function presentationArtwork(
  index: number,
): (typeof PRESENTATION_ARTWORK)[number] {
  return PRESENTATION_ARTWORK[index % PRESENTATION_ARTWORK.length];
}

export function selectPublishedFreeCourse(
  programs: ProgramSummaryResponse[],
): ProgramSummaryResponse | undefined {
  return programs.find((p) => p.slug === FREE_COURSE_SLUG);
}

export function firstActionableActivity(
  learning: LearningResponse,
): LearningActivityResponse | undefined {
  for (const mod of learning.modules) {
    for (const activity of mod.activities) {
      const state = activity.state.toLowerCase();
      if (
        (state === "in_progress" || state === "available") &&
        activity.allowed_actions.length > 0
      ) {
        return activity;
      }
    }
  }
  return undefined;
}

export function activityStateLabel(activity: LearningActivityResponse): string {
  return activity.state
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function isReviewable(activity: LearningActivityResponse): boolean {
  return activity.state.toLowerCase() === "completed";
}

export function isOpenable(activity: LearningActivityResponse): boolean {
  const state = activity.state.toLowerCase();
  return (
    isReviewable(activity) ||
    ((state === "in_progress" || state === "available") &&
      activity.allowed_actions.length > 0)
  );
}

type LoadResult = "loaded" | "error" | "aborted" | "redirecting";

export type DashboardData = {
  me: MeResponse;
  programs: ProgramSummaryResponse[];
  learning?: LearningResponse;
  offlineRead?: OfflineReadMetadata;
};

export type DashboardReadResult =
  | { kind: "ready"; data: DashboardData }
  | { kind: "onboarding" };

export async function loadDashboardData(
  api: LearnerApi,
  signal?: AbortSignal,
): Promise<DashboardReadResult> {
  const me = await api.me({ signal });
  if (!hasMembershipRole(me)) {
    return { kind: "ready", data: { me, programs: [] } };
  }

  const onboarding = await api.onboarding({ signal });
  if (onboarding.status !== "completed" && onboarding.status !== "skipped") {
    return { kind: "onboarding" };
  }

  const programsRes = await api.listPrograms(50, { signal });
  const freeCourse = selectPublishedFreeCourse(programsRes.items);
  let learning: LearningResponse | undefined;
  if (freeCourse) {
    try {
      learning = await api.learning(freeCourse.id, undefined, { signal });
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
  }
  return {
    kind: "ready",
    data: {
      me,
      programs: programsRes.items,
      learning,
      offlineRead:
        getEarliestOfflineReadMetadata(me, onboarding, programsRes, learning) ??
        undefined,
    },
  };
}

export type DashboardRuntimeProps = { api?: LearnerApi };

export function DashboardRuntime({ api = defaultApi }: DashboardRuntimeProps) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [onboardingRedirecting, setOnboardingRedirecting] = useState(false);
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const membershipKnown = data !== null;
  const membershipAvailable = data !== null && hasMembershipRole(data.me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    membershipKnown,
    membershipAvailable,
    data?.me.person_id ?? null,
  );

  const load = useCallback(async (): Promise<LoadResult> => {
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
    setOnboardingRedirecting(false);
    try {
      const result = await loadDashboardData(api, controller.signal);
      if (!isCurrent()) return "aborted";
      if (result.kind === "onboarding") {
        setOnboardingRedirecting(true);
        return "redirecting";
      }
      setData(result.data);
      return "loaded";
    } catch (err) {
      if (isAbortError(err) || !isCurrent()) return "aborted";
      setError(err);
      return "error";
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

  useEffect(() => {
    if (onboardingRedirecting) window.location.replace(ROUTES.onboarding);
  }, [onboardingRedirecting]);

  async function handleEnroll(programVersionId: string) {
    setEnrolling(true);
    setEnrollError(null);
    try {
      await api.enrollFree(programVersionId);
      if (!mountedRef.current) return;
      const refreshResult = await load();
      if (refreshResult === "error" && mountedRef.current) {
        setError(null);
        setEnrollError(
          "Enrollment completed, but the dashboard could not refresh. Your enrollment was not lost; retry the dashboard read.",
        );
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setEnrollError(
        userFacingRequestError(
          err,
          "Could not start the free course at this time. Please retry.",
        ),
      );
    } finally {
      if (mountedRef.current) setEnrolling(false);
    }
  }

  if (loading) {
    return <DashboardSkeleton />;
  }

  if (onboardingRedirecting) {
    return (
      <div className="surface-state" role="status" aria-live="polite">
        <h1>Opening your learner setup</h1>
        <p>
          Complete the required setup before entering the learner workspace.
        </p>
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
            ? "Sign in to continue"
            : is403
              ? "Learner access is unavailable"
              : "Dashboard could not load"}
        </h1>
        <p>
          {is401
            ? "Your session has expired. Sign in again to access your dashboard."
            : is403
              ? "This account is not authorized to view the learner workspace."
              : userFacingRequestError(
                  error,
                  "The service could not be reached. Try again.",
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

  const { me, programs, learning } = data;

  if (!hasMembershipRole(me)) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }

  const displayName = me.display_name || "Learner";
  const freeCourse = selectPublishedFreeCourse(programs);
  const nextActivity = learning ? firstActionableActivity(learning) : undefined;
  const leadModule = learning?.modules[0];
  // Keep the dashboard read authoritative: a cached projection is surfaced
  // only as an explicitly labelled, non-canonical fallback by the loader.
  const offlineRead = data.offlineRead;
  const percentage = learning
    ? Math.round(Math.min(1, Math.max(0, learning.projection.percentage)) * 100)
    : 0;
  const activities =
    learning?.modules.flatMap((module) => module.activities) ?? [];
  const nextActivities = activities.slice(0, 4);
  const practiceActivity = nextActivity;
  const canOpenNext = Boolean(
    nextActivity && isOpenable(nextActivity) && !offlineRead,
  );
  const remainingRequired = learning
    ? Math.max(
        0,
        learning.projection.denominator - learning.projection.completed_count,
      )
    : 0;

  return (
    <div className="dashboard-view dashboard-view--modern ac-dashboard-wrapper">
      {/* Welcome Banner */}
      <section
        className="dashboard-intro ac-welcome-banner"
        aria-labelledby="dashboard-title"
      >
        <div>
          <p className="dashboard-intro__eyebrow sr-only">
            Learning Command Center
          </p>
          <h1
            id="dashboard-title"
            className="dashboard-intro__title ac-welcome-title"
          >
            Welcome back, {displayName}
          </h1>
          <p className="dashboard-intro__subhead ac-welcome-subtitle">
            <span className="desktop-text">
              Pick up where you left off or follow your learning path.
            </span>
            <span className="mobile-text">
              Let&apos;s keep your learning on track.
            </span>
          </p>
        </div>
      </section>

      {offlineRead ? (
        <div
          className="offline-read-notice"
          id="dashboard-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}

      {learning ? (
        <div className="dashboard-modern-layout ac-dashboard-grid">
          {/* Top Row: Continue Learning + Today's Plan */}
          <div className="dashboard-row dashboard-row--top ac-grid-row-top">
            {/* Continue Learning Card */}
            <section
              className="card continue-learning-card ac-card"
              aria-labelledby="continue-learning-title"
            >
              <div className="card-header-row ac-card-header">
                <h2
                  id="continue-learning-title"
                  className="card-header-title ac-card-title"
                >
                  <span className="desktop-text">Continue learning</span>
                  <span className="mobile-text">Continue watching</span>
                </h2>
                <Link
                  className="card-header-link ac-card-link"
                  href={ROUTES.learning}
                >
                  <span className="desktop-text">View all</span>
                  <ChevronRight
                    size={16}
                    aria-hidden="true"
                    className="mobile-icon"
                  />
                </Link>
              </div>

              <div className="continue-learning-card__body ac-continue-content">
                {/* Presentation artwork is not a media source or player. */}
                <div
                  className="continue-learning-media ac-media-frame"
                  role="status"
                  aria-label="Presentation artwork; approved lesson media is unavailable"
                >
                  <Image
                    src="/media/ac-course-hero-v1.png"
                    alt=""
                    fill
                    sizes="(max-width: 1023px) 44vw, 100vw"
                    className="ac-media-frame__art"
                  />
                  <div className="ac-media-frame__veil" aria-hidden="true" />
                  <div className="ac-media-frame__copy">
                    <span className="ac-media-frame__eyebrow">
                      Module {leadModule?.position ?? 1} · presentation artwork
                    </span>
                    <strong>
                      {leadModule?.title ?? learning.program_title}
                    </strong>
                    <span>
                      Approved lesson media is not connected yet. Playback is
                      unavailable.
                    </span>
                  </div>
                </div>

                {/* Course Info & Progress */}
                <div className="continue-learning-info ac-continue-meta">
                  <p className="continue-learning-module-tag ac-module-badge">
                    {learning.program_title}
                    {leadModule ? ` · Module ${leadModule.position}` : ""}
                  </p>
                  <h3 className="continue-learning-heading ac-course-heading">
                    {nextActivity?.title ??
                      leadModule?.title ??
                      learning.program_title}
                  </h3>

                  <div className="continue-learning-progress-group ac-progress-container">
                    <div
                      className="progress-bar-track ac-progress-bar-track"
                      role="progressbar"
                      aria-valuenow={percentage}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label="Course completion"
                    >
                      <div
                        className="progress-bar-fill ac-progress-bar-fill"
                        style={{ width: `${percentage}%` }}
                      />
                    </div>
                    <div className="progress-label-row">
                      <span className="progress-label-text ac-progress-pct-label">
                        {percentage}% complete
                      </span>
                    </div>
                  </div>

                  <div className="continue-learning-last-watched ac-last-watched desktop-only">
                    <span className="meta-label ac-lw-label">
                      Current state
                    </span>
                    <span className="meta-value ac-lw-val">
                      {nextActivity
                        ? activityStateLabel(nextActivity)
                        : "Course outline"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Bottom Action Section */}
              <div className="continue-learning-card__footer ac-continue-footer">
                {/* Desktop inline lesson row */}
                <div className="continue-lesson-row desktop-only">
                  <Link
                    href={
                      canOpenNext && nextActivity
                        ? ROUTES.activity(nextActivity.id)
                        : ROUTES.learning
                    }
                    className="continue-lesson-link ac-continue-lesson-btn"
                  >
                    <span className="continue-lesson-icon-circle ac-lesson-icon-circle">
                      <ArrowRight size={15} />
                    </span>
                    <div className="continue-lesson-copy ac-lesson-btn-text">
                      <strong>
                        {canOpenNext ? "Continue activity" : "Open curriculum"}
                      </strong>
                      <span>
                        {nextActivity?.title ??
                          leadModule?.title ??
                          learning.program_title}
                      </span>
                    </div>
                  </Link>
                  <span className="continue-lesson-duration ac-lesson-time-left">
                    {nextActivity
                      ? activityStateLabel(nextActivity)
                      : "Open path"}
                  </span>
                </div>

                {/* Mobile large CTA button */}
                <div className="continue-mobile-cta mobile-only">
                  <Link
                    href={
                      canOpenNext && nextActivity
                        ? ROUTES.activity(nextActivity.id)
                        : ROUTES.learning
                    }
                    className="button button--cobalt button--full"
                  >
                    <ArrowRight size={16} aria-hidden="true" />
                    <span>{canOpenNext ? "Continue" : "Open curriculum"}</span>
                  </Link>
                </div>
              </div>
            </section>

            {/* The learning projection has ordered activities, not a schedule. */}
            <section
              className="card todays-plan-card ac-card"
              aria-labelledby="todays-plan-title"
            >
              <div className="card-header-row ac-card-header">
                <h2
                  id="todays-plan-title"
                  className="card-header-title ac-card-title"
                >
                  <span className="desktop-text">Next activities</span>
                  <span className="mobile-text">Up next</span>
                </h2>
                <span className="date-badge ac-date-pill desktop-only">
                  Path version {learning.version_number}
                </span>
                <Link
                  className="card-header-link ac-card-link mobile-only"
                  href={ROUTES.learning}
                >
                  View all
                </Link>
              </div>

              <div className="todays-plan-list ac-plan-list">
                {nextActivities.length > 0 ? (
                  nextActivities.map((activity, index) => {
                    const actionable = isOpenable(activity) && !offlineRead;
                    const row = (
                      <>
                        <div className="plan-item-time ac-plan-time">
                          Step {index + 1}
                        </div>
                        <div
                          className={`plan-item-icon ac-plan-badge plan-item-icon--${
                            index === 0
                              ? "blue"
                              : index === 1
                                ? "green"
                                : "amber"
                          } ac-plan-badge--${
                            index === 0
                              ? "blue"
                              : index === 1
                                ? "green"
                                : "amber"
                          }`}
                        >
                          {index === 0 ? (
                            <BookOpen size={14} aria-hidden="true" />
                          ) : index === 1 ? (
                            <FileText size={14} aria-hidden="true" />
                          ) : (
                            <Edit3 size={14} aria-hidden="true" />
                          )}
                        </div>
                        <div className="plan-item-text ac-plan-details">
                          <strong className="ac-plan-action">
                            {activity.kind.replaceAll("_", " ")}
                          </strong>
                          <span className="ac-plan-target">
                            {activity.title}
                          </span>
                        </div>
                        <div className="plan-item-meta">
                          <span className="duration-tag ac-plan-dur desktop-only">
                            {offlineRead
                              ? "Reconnect to open"
                              : activityStateLabel(activity)}
                          </span>
                          <ChevronRight
                            className="ac-plan-arrow"
                            size={15}
                            aria-hidden="true"
                          />
                        </div>
                      </>
                    );
                    return actionable ? (
                      <Link
                        href={ROUTES.activity(activity.id)}
                        className="plan-schedule-item ac-plan-row"
                        key={activity.id}
                      >
                        {row}
                      </Link>
                    ) : (
                      <div
                        aria-disabled="true"
                        className="plan-schedule-item ac-plan-row is-disabled"
                        key={activity.id}
                      >
                        {row}
                      </div>
                    );
                  })
                ) : (
                  <div className="dashboard-card-empty" role="status">
                    No activities are published in this learning path yet.
                  </div>
                )}
              </div>

              <div className="card-footer-action ac-card-bottom-link desktop-only">
                <Link
                  href={ROUTES.learning}
                  className="footer-plan-link ac-footer-action-link"
                >
                  <BookOpen size={14} aria-hidden="true" />
                  <span>Open full learning path</span>
                  <ChevronRight size={14} aria-hidden="true" />
                </Link>
              </div>
            </section>
          </div>

          {/* Mobile rails keep the selected media-first hierarchy without
              inventing enrolled courses, artwork URLs, or progress facts. */}
          <section
            className="dashboard-collection dashboard-collection--learning mobile-only"
            aria-labelledby="mobile-my-learning-title"
          >
            <div className="dashboard-collection__header">
              <h2 id="mobile-my-learning-title">My Learning</h2>
              <Link href={ROUTES.learning}>View all</Link>
            </div>
            {learning.modules.length > 0 ? (
              <div className="dashboard-collection__rail" role="list">
                {learning.modules.slice(0, 4).map((module, index) => {
                  const completedCount = module.activities.filter(
                    (moduleActivity) =>
                      moduleActivity.state.toLowerCase() === "completed",
                  ).length;
                  const modulePercentage = module.activities.length
                    ? Math.round(
                        (completedCount / module.activities.length) * 100,
                      )
                    : 0;
                  const moduleNext = module.activities.find((moduleActivity) =>
                    isOpenable(moduleActivity),
                  );
                  const moduleActionable = Boolean(moduleNext && !offlineRead);
                  const content = (
                    <>
                      <div className="dashboard-collection-card__art">
                        <Image
                          src={presentationArtwork(index + 1)}
                          alt=""
                          fill
                          sizes="(max-width: 520px) 78vw, 280px"
                        />
                        <span>Module {module.position}</span>
                      </div>
                      <div className="dashboard-collection-card__body">
                        <strong>{module.title}</strong>
                        <span>
                          {completedCount} of {module.activities.length}{" "}
                          activities complete
                        </span>
                        <div
                          className="dashboard-collection-card__progress"
                          role="progressbar"
                          aria-valuenow={modulePercentage}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label={module.title + " completion"}
                        >
                          <span style={{ width: modulePercentage + "%" }} />
                        </div>
                      </div>
                    </>
                  );
                  return moduleActionable ? (
                    <Link
                      href={ROUTES.activity(moduleNext!.id)}
                      className="dashboard-collection-card"
                      role="listitem"
                      key={module.id}
                    >
                      {content}
                    </Link>
                  ) : (
                    <div
                      className="dashboard-collection-card is-disabled"
                      role="listitem"
                      data-disabled="true"
                      key={module.id}
                    >
                      {content}
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="dashboard-collection__empty" role="status">
                No modules are published in this learning path yet.
              </p>
            )}
          </section>

          <section
            className="dashboard-collection dashboard-collection--discover mobile-only"
            aria-labelledby="mobile-discover-title"
          >
            <div className="dashboard-collection__header">
              <h2 id="mobile-discover-title">Discover</h2>
              <Link href={ROUTES.discover}>View all</Link>
            </div>
            {programs.filter((program) => program.id !== learning.program_id)
              .length > 0 ? (
              <div className="dashboard-collection__rail" role="list">
                {programs
                  .filter((program) => program.id !== learning.program_id)
                  .slice(0, 4)
                  .map((program, index) => (
                    <Link
                      href={ROUTES.programDetail(program.slug)}
                      className="dashboard-discover-card"
                      role="listitem"
                      key={program.id}
                    >
                      <div className="dashboard-discover-card__art">
                        <Image
                          src={presentationArtwork(index + 1)}
                          alt=""
                          fill
                          sizes="(max-width: 520px) 78vw, 280px"
                        />
                        <span>Published</span>
                      </div>
                      <strong>{program.title}</strong>
                      <span>Version {program.version_number}</span>
                    </Link>
                  ))}
              </div>
            ) : (
              <p className="dashboard-collection__empty" role="status">
                No additional published programs are available yet.
              </p>
            )}
          </section>

          {/* Mobile projection-backed next-focus summary. */}
          <div className="mobile-practice-banner mobile-only">
            <Link
              href={
                canOpenNext && practiceActivity
                  ? ROUTES.activity(practiceActivity.id)
                  : ROUTES.learning
              }
              className="card upcoming-practice-soft-card"
            >
              <div className="soft-card-icon">
                <BookOpen size={18} aria-hidden="true" />
              </div>
              <div className="soft-card-content">
                <span className="soft-card-kicker">Next focus</span>
                <strong>
                  {practiceActivity?.title ?? "No next activity is published"}
                </strong>
                <span>
                  {practiceActivity
                    ? activityStateLabel(practiceActivity)
                    : "Check the learning path for updates"}
                </span>
              </div>
              <ChevronRight
                size={18}
                aria-hidden="true"
                className="soft-card-chevron"
              />
            </Link>
          </div>

          {/* Middle Row: 3 Columns on Desktop */}
          <div className="dashboard-row dashboard-row--middle ac-grid-row-middle desktop-only">
            {/* Col 1: next authorized focus */}
            <section
              className="card upcoming-practice-card ac-card"
              aria-labelledby="upcoming-practice-title"
            >
              <div className="card-header-row ac-card-header">
                <h2
                  id="upcoming-practice-title"
                  className="card-header-title ac-card-title"
                >
                  Next focus
                </h2>
                <Link
                  className="card-header-link ac-card-link"
                  href={ROUTES.learning}
                >
                  View learning
                </Link>
              </div>

              <div className="upcoming-practice-body ac-practice-body">
                <div
                  className="event-date-block ac-calendar-date-box"
                  aria-hidden="true"
                >
                  <span className="event-date-month ac-cal-month">STEP</span>
                  <span className="event-date-day ac-cal-day">
                    {practiceActivity?.position ?? "—"}
                  </span>
                  <span className="event-date-weekday ac-cal-weekday">
                    PATH
                  </span>
                </div>

                <div className="event-details ac-practice-info">
                  <span className="event-tag-pill ac-roleplay-tag">
                    {practiceActivity
                      ? practiceActivity.kind.replaceAll("_", " ")
                      : "Not published"}
                  </span>
                  <h3 className="event-title ac-practice-event-title">
                    {practiceActivity?.title ?? "No next activity yet"}
                  </h3>
                  <p className="event-time-text ac-practice-time">
                    {practiceActivity
                      ? activityStateLabel(practiceActivity)
                      : "The schedule service is not part of this release."}
                  </p>
                  <p className="event-coach-text ac-practice-coach">
                    {practiceActivity?.explanation.reason ??
                      "Published activities will appear here."}
                  </p>
                </div>
              </div>

              <div className="event-actions-row ac-practice-buttons">
                <Link
                  href={
                    canOpenNext && practiceActivity
                      ? ROUTES.activity(practiceActivity.id)
                      : ROUTES.learning
                  }
                  className="button button--cobalt button--small ac-btn-primary"
                >
                  {canOpenNext ? "Open activity" : "Open learning path"}
                </Link>
              </div>

              <div className="card-footer-action ac-card-bottom-link">
                <Link
                  href={ROUTES.learning}
                  className="footer-plan-link ac-footer-action-link"
                >
                  <BookOpen size={14} aria-hidden="true" />
                  <span>View all activities</span>
                  <ChevronRight size={14} aria-hidden="true" />
                </Link>
              </div>
            </section>

            {/* Col 2: published programs */}
            <section
              className="card my-courses-card ac-card"
              aria-labelledby="my-courses-title"
            >
              <div className="card-header-row ac-card-header">
                <h2
                  id="my-courses-title"
                  className="card-header-title ac-card-title"
                >
                  Published programs
                </h2>
                <Link
                  className="card-header-link ac-card-link"
                  href={ROUTES.discover}
                >
                  View all
                </Link>
              </div>

              <div className="my-courses-list ac-courses-list">
                {programs.slice(0, 3).map((program, index) => {
                  const isCurrentProgram = program.id === learning.program_id;
                  return (
                    <Link
                      href={
                        isCurrentProgram
                          ? ROUTES.learning
                          : ROUTES.programDetail(program.slug)
                      }
                      className="course-progress-item ac-course-row"
                      key={program.id}
                    >
                      <div className="course-item-thumb ac-course-thumb">
                        <Image
                          src={presentationArtwork(index)}
                          alt=""
                          fill
                          sizes="44px"
                        />
                        <span>Published</span>
                      </div>
                      <div className="course-item-info ac-course-info">
                        <strong className="ac-course-name">
                          {program.title}
                        </strong>
                        <div className="course-item-sub ac-course-prog-line">
                          <span>
                            {isCurrentProgram
                              ? `${learning.projection.completed_count} / ${learning.projection.denominator} required`
                              : `Published version ${program.version_number}`}
                          </span>
                          {isCurrentProgram ? (
                            <>
                              <div className="course-item-bar ac-course-bar">
                                <div
                                  className="course-item-bar-fill ac-course-bar-fill"
                                  style={{ width: `${percentage}%` }}
                                />
                              </div>
                              <span className="course-item-pct ac-course-pct">
                                {percentage}%
                              </span>
                            </>
                          ) : null}
                        </div>
                      </div>
                      <ChevronRight
                        className="ac-course-arrow"
                        size={15}
                        aria-hidden="true"
                      />
                    </Link>
                  );
                })}
              </div>
            </section>

            {/* Col 3: canonical projection snapshot */}
            <section
              className="card weekly-activity-card ac-card"
              aria-labelledby="weekly-activity-title"
            >
              <div className="card-header-row ac-card-header">
                <div>
                  <h2
                    id="weekly-activity-title"
                    className="card-header-title ac-card-title"
                  >
                    Progress snapshot
                  </h2>
                  <p className="card-header-subtitle ac-card-subtitle">
                    Projection {learning.projection.projection_version}
                  </p>
                </div>
                <Link
                  className="card-header-link ac-card-link"
                  href={ROUTES.progress}
                >
                  View progress
                </Link>
              </div>

              <div className="weekly-metrics-list ac-activity-list">
                <div className="weekly-metric-row ac-activity-metric-row">
                  <div className="metric-icon metric-icon--green ac-metric-icon ac-metric-icon--green">
                    <BookOpen size={14} aria-hidden="true" />
                  </div>
                  <div className="metric-label ac-metric-label">
                    Required complete
                  </div>
                  <div className="metric-count ac-metric-count">
                    {learning.projection.completed_count}
                  </div>
                  <div className="metric-time ac-metric-time">
                    {percentage}%
                  </div>
                </div>

                <div className="weekly-metric-row ac-activity-metric-row">
                  <div className="metric-icon metric-icon--blue ac-metric-icon ac-metric-icon--blue">
                    <Edit3 size={14} aria-hidden="true" />
                  </div>
                  <div className="metric-label ac-metric-label">
                    Required remaining
                  </div>
                  <div className="metric-count ac-metric-count">
                    {remainingRequired}
                  </div>
                  <div className="metric-time ac-metric-time">
                    of {learning.projection.denominator}
                  </div>
                </div>

                <div className="weekly-metric-row ac-activity-metric-row">
                  <div className="metric-icon metric-icon--green ac-metric-icon ac-metric-icon--green">
                    <MessageSquare size={14} aria-hidden="true" />
                  </div>
                  <div className="metric-label ac-metric-label">
                    Published modules
                  </div>
                  <div className="metric-count ac-metric-count">
                    {learning.modules.length}
                  </div>
                  <div className="metric-time ac-metric-time">Current path</div>
                </div>
              </div>

              <div className="card-footer-action ac-card-bottom-link">
                <Link
                  href={ROUTES.progress}
                  className="footer-plan-link ac-footer-action-link"
                >
                  <BookOpen size={14} aria-hidden="true" />
                  <span>View full progress</span>
                  <ChevronRight size={14} aria-hidden="true" />
                </Link>
              </div>
            </section>
          </div>

          {/* Bottom row remains truthful until another program is published. */}
          <div className="dashboard-row dashboard-row--bottom ac-grid-row-bottom desktop-only">
            <section
              className="card upcoming-program-banner ac-card ac-upcoming-banner"
              aria-labelledby="upcoming-banner-title"
            >
              <div className="upcoming-banner-thumb ac-upcoming-thumb">
                <Image
                  src="/media/ac-course-hero-v1.png"
                  alt=""
                  fill
                  sizes="(max-width: 1023px) 100vw, 220px"
                />
                <div className="ac-upcoming-thumb__veil" aria-hidden="true" />
                <span className="upcoming-thumb-badge ac-upcoming-badge">
                  CATALOG
                </span>
                <strong className="ac-upcoming-thumb-title">
                  Published programs
                </strong>
                <span className="upcoming-thumb-pill ac-upcoming-pill">
                  SERVER PUBLISHED
                </span>
              </div>

              <div className="upcoming-banner-content ac-upcoming-body">
                <span className="upcoming-kicker ac-upcoming-tag">
                  CATALOG STATUS
                </span>
                <h3
                  id="upcoming-banner-title"
                  className="upcoming-title ac-upcoming-heading"
                >
                  {programs.length > 1
                    ? `${programs.length} programs are published`
                    : "More programs will appear when published"}
                </h3>
                <p className="upcoming-description ac-upcoming-desc">
                  This workspace never presents launch dates, availability, or
                  enrollment progress until the server publishes it.
                </p>

                <div className="upcoming-footer-row ac-upcoming-action-row">
                  <div className="upcoming-date-label ac-upcoming-date">
                    <Compass size={14} aria-hidden="true" />
                    <span>{programs.length} published</span>
                  </div>
                  <Link
                    href={ROUTES.discover}
                    className="button button--outline button--small"
                  >
                    <Compass size={14} aria-hidden="true" />
                    <span>Open catalog</span>
                  </Link>
                </div>
              </div>
            </section>
          </div>
        </div>
      ) : (
        /* Honest published-program state when unenrolled */
        <section
          className="card start-course-hero"
          aria-labelledby="start-course-title"
        >
          <div className="start-course-hero__copy">
            <span className="card-badge card-badge--neutral">
              {freeCourse ? "Published program" : "No published free course"}
            </span>
            <h2 id="start-course-title">
              {freeCourse?.title ?? "No published free course is available"}
            </h2>
            <p>
              {freeCourse
                ? `Version ${freeCourse.version_number} is available in this learner workspace.`
                : "Browse the published catalog when a course is available for this workspace."}
            </p>

            {enrollError ? (
              <div className="alert-box alert-box--error" role="alert">
                <p>{enrollError}</p>
              </div>
            ) : null}

            <div className="start-course-hero__actions">
              {freeCourse ? (
                <button
                  className="button button--cobalt"
                  type="button"
                  disabled={enrolling || Boolean(offlineRead)}
                  aria-describedby={
                    offlineRead ? "dashboard-offline-read" : undefined
                  }
                  onClick={() =>
                    void handleEnroll(freeCourse.program_version_id)
                  }
                >
                  {enrolling ? "Enrolling…" : "Start the Free Course"}
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              ) : (
                <Link className="button button--cobalt" href={ROUTES.discover}>
                  Browse published programs{" "}
                  <Compass size={16} aria-hidden="true" />
                </Link>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
