"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ModuleCard } from "@ac/ui";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CirclePlay,
  FileText,
  Flag,
  Layers3,
  LockKeyhole,
  PenLine,
  Play,
  ShieldCheck,
  Sparkles,
  Trophy,
  Wrench,
} from "lucide-react";
import Image from "next/image";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type ActivityResponse,
  type LearnerApi,
  type LearningActivityResponse,
  type LearningResponse,
  type MeResponse,
  type ProgramSummaryResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  getOfflineReadMetadata,
  offlineReadNotice,
  type OfflineReadMetadata,
} from "../lib/offline-read-cache";
import {
  activityRecoveryText,
  activityServerFingerprint,
  availableLocalStorage,
  clearActivityLocalDraftIfMatchesWithLock,
  clearLearnerLocalDraftsForPersonWithLock,
  localDraftMatchesServer,
  mutationFailureKind,
  purgeActivityLocalDraftIfMatchesWithLock,
  readActivityLocalDraftWithLock,
  registerBeforeUnloadGuard,
  registerHistoryNavigationGuard,
  registerInternalNavigationGuard,
  writeActivityLocalDraftWithLock,
  writeActivityLocalDraftWithLockAndEnvelope,
  type ActivityDraftEnvelope,
  type ActivityDraftScope,
  type LocalDraftRawSnapshot,
  type MutationFailureKind,
} from "../lib/local-drafts";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";
import {
  hasMembershipRole,
  MembershipDraftCleanupNotice,
  MembershipUnavailable,
  type MembershipDraftCleanup,
} from "./membership-availability";
import { VideoViewer } from "./learning-loop-runtime";

const defaultApi = createLearnerApi();
export const FREE_COURSE_SLUG = "authority-closers-free-course";
const LEARNER_SUPPORT_HREF =
  "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20learner%20access";

export function isFreeEnrollmentProgram(program: { slug: string }): boolean {
  return program.slug === FREE_COURSE_SLUG;
}

type LoadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "empty" }
  | { status: "error"; error: unknown };

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "Your session has expired. Sign in again to continue.";
    if (error.status === 403)
      return "This account is not permitted to use this learner action.";
    return userFacingRequestError(
      error,
      "The learning service could not complete this request. Try again.",
    );
  }
  if (error instanceof TypeError)
    return "The service could not be reached. Try again when connected.";
  return "The service returned an unexpected response. Try again.";
}

function StateMessage({
  state,
  retry,
  pageTitle,
  pageHeadingPresent = false,
}: {
  state: LoadState<unknown>;
  retry?: () => void;
  pageTitle: string;
  pageHeadingPresent?: boolean;
}) {
  const Heading = pageHeadingPresent ? "h3" : "h1";
  if (state.status === "loading") {
    return (
      <div
        className="surface-state surface-state--loading"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <div className="surface-state__loading-heading">
          <div>
            <p className="surface-state__eyebrow">Preparing your workspace</p>
            <Heading>{pageTitle}</Heading>
          </div>
          <span className="surface-state__loading-status">Loading</span>
        </div>
        <div className="surface-state__skeleton" aria-hidden="true">
          <span className="surface-state__skeleton-line is-title" />
          <span className="surface-state__skeleton-line is-copy" />
          <span className="surface-state__skeleton-line is-action" />
        </div>
        <p className="sr-only">Your learning workspace is loading.</p>
      </div>
    );
  }
  if (state.status === "empty") {
    return (
      <div className="surface-state" role="status">
        <Heading>No published learning is available yet.</Heading>
        <p>Try again after a course has been published for this workspace.</p>
      </div>
    );
  }
  if (state.status !== "error") return null;
  const needsSignIn =
    state.error instanceof ApiError && state.error.status === 401;
  return (
    <div className="surface-state surface-state--error-terminal" role="alert">
      <Heading>
        {needsSignIn ? "Sign in to continue." : "This view could not load."}
      </Heading>
      <p>{errorText(state.error)}</p>
      {needsSignIn ? (
        <Link
          className="button button--small button--ink"
          href={ROUTES.sessionExpired}
        >
          Sign in again
        </Link>
      ) : retry ? (
        <button
          className="button button--small button--ink"
          type="button"
          onClick={retry}
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}

function useLoad<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  empty: (value: T) => boolean,
  reloadKey?: string | number,
): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (active) setState({ status: "loading" });
    });
    loader(controller.signal)
      .then((value) => {
        if (!active) return;
        setState(
          empty(value) ? { status: "empty" } : { status: "ready", value },
        );
      })
      .catch((error: unknown) => {
        if (active && !isAbortError(error)) {
          setState({ status: "error", error });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
    // The loader is intentionally captured per caller; retry and an explicit
    // route/resource identity are the only triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt, reloadKey]);
  return {
    ...state,
    retry: () => setAttempt((value) => value + 1),
  } as LoadState<T> & {
    retry: () => void;
  };
}

function CatalogList({ items }: { items: ProgramSummaryResponse[] }) {
  return (
    <div className="workspace-grid">
      {items.map((program) => (
        <article className="workspace-card" key={program.id}>
          <p className="kicker">
            Published program · v{program.version_number}
          </p>
          <h2>{program.title}</h2>
          <p>Published {new Date(program.published_at).toLocaleDateString()}</p>
          <Link className="text-link" href={ROUTES.programDetail(program.slug)}>
            View program →
          </Link>
        </article>
      ))}
    </div>
  );
}

export function PublicCatalogHome({ api = defaultApi }: { api?: LearnerApi }) {
  const state = useLoad(
    (signal) => api.listPrograms(50, { signal }),
    (value) => value.items.length === 0,
  );
  const offlineRead =
    state.status === "ready"
      ? getEarliestOfflineReadMetadata(state.value, state.value.items)
      : null;
  return (
    <>
      <section className="hero landing-hero" aria-labelledby="catalog-title">
        <div className="eyebrow">
          <span aria-hidden="true" /> Authority Closers learning
        </div>
        <h1 id="catalog-title">
          Published learning.
          <br />
          <em>One useful move at a time.</em>
        </h1>
        <p className="hero-copy">
          The catalog below is read from the staging API. If nothing is
          published, this surface stays empty.
        </p>
        <div className="hero-actions">
          <Link className="button button--outline" href={ROUTES.login}>
            Learner sign in
          </Link>
        </div>
      </section>
      <section className="detail-section" aria-labelledby="catalog-list-title">
        <div className="section-heading">
          <p className="kicker">API catalog</p>
          <h2 id="catalog-list-title">Available programs.</h2>
        </div>
        <StateMessage
          state={state}
          pageTitle="Available programs"
          pageHeadingPresent
          retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
        />
        {offlineRead ? (
          <div
            className="offline-read-notice"
            id="catalog-offline-read"
            role="status"
          >
            {offlineReadNotice(offlineRead)}
          </div>
        ) : null}
        {state.status === "ready" ? (
          <CatalogList items={state.value.items} />
        ) : null}
      </section>
    </>
  );
}

function formatPublicActivityKind(kind: string): string {
  const normalized = kind
    .toLowerCase()
    .replace(/[_\s-]+/g, " ")
    .trim();
  if (normalized === "video") return "Video Lesson";
  if (normalized === "reflection") return "Interactive Reflection";
  if (normalized === "choice") return "Knowledge Check";
  return normalized
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function activityKindIcon(kind: string) {
  const normalized = kind.toUpperCase();
  if (normalized === "VIDEO") {
    return (
      <CirclePlay
        size={16}
        aria-hidden="true"
        className="public-activity-row__kind-icon"
      />
    );
  }
  if (
    normalized === "REFLECTION" ||
    normalized === "QUIZ" ||
    normalized === "CHOICE"
  ) {
    return (
      <Sparkles
        size={16}
        aria-hidden="true"
        className="public-activity-row__kind-icon"
      />
    );
  }
  return (
    <BookOpen
      size={16}
      aria-hidden="true"
      className="public-activity-row__kind-icon"
    />
  );
}

export function PublicProgramDetail({
  slug,
  api = defaultApi,
}: {
  slug: string;
  api?: LearnerApi;
}) {
  const state = useLoad(
    (signal) => api.program(slug, { signal }),
    () => false,
  );
  const program = state.status === "ready" ? state.value : null;
  const offlineRead = program ? getEarliestOfflineReadMetadata(program) : null;
  const freeEnrollmentAvailable =
    program !== null && isFreeEnrollmentProgram(program);

  const totalActivities = program
    ? program.modules.reduce(
        (sum, module) => sum + (module.activities?.length || 0),
        0,
      )
    : 0;

  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Program details"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {offlineRead ? (
        <div
          className="offline-read-notice"
          id="program-detail-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}
      {program ? (
        <div className="public-program-storefront">
          {/* Two-Column Hero Section */}
          <section className="program-hero" aria-labelledby="program-title">
            <div className="program-hero__main">
              <div className="program-hero__badge-row">
                <span className="eyebrow program-hero__eyebrow">
                  <span className="eyebrow-dot" aria-hidden="true" />
                  Published Program · Version {program.version_number}
                </span>
                {freeEnrollmentAvailable ? (
                  <span className="program-hero__access-badge">
                    Free Enrollment
                  </span>
                ) : null}
              </div>

              <h1 id="program-title" className="program-hero__title">
                {program.title}
              </h1>

              <p className="program-hero__description">
                Published curriculum from the canonical catalog.
              </p>

              <div
                className="program-hero__stats-pills"
                aria-label="Course summary statistics"
              >
                <div className="stat-pill">
                  <Layers3 size={15} aria-hidden="true" />
                  <span>
                    <strong>{program.modules.length}</strong>{" "}
                    {program.modules.length === 1 ? "Module" : "Modules"}
                  </span>
                </div>
                <div className="stat-pill">
                  <BookOpen size={15} aria-hidden="true" />
                  <span>
                    <strong>{totalActivities}</strong>{" "}
                    {totalActivities === 1 ? "Activity" : "Activities"}
                  </span>
                </div>
                <div className="stat-pill">
                  <ShieldCheck size={15} aria-hidden="true" />
                  <span>Canonical Curriculum</span>
                </div>
              </div>

              {freeEnrollmentAvailable ? (
                <div className="hero-actions program-hero__actions">
                  <Link
                    className="button button--ink program-hero__cta-primary"
                    href={ROUTES.login}
                  >
                    Sign in to start free
                  </Link>
                  <Link
                    className="button button--outline program-hero__cta-secondary"
                    href={ROUTES.register}
                  >
                    Create learner account →
                  </Link>
                </div>
              ) : (
                <p className="program-hero__unavailable-note" role="status">
                  Free enrollment is unavailable for this program.
                </p>
              )}
            </div>

            <aside
              className="program-hero__aside"
              aria-label="Course overview card"
            >
              <div className="program-hero__preview-card">
                <div className="program-hero__image-frame">
                  <Image
                    src="/media/ac-course-hero-v1.png"
                    alt=""
                    width={560}
                    height={315}
                    className="program-hero__cover-image"
                    priority
                  />
                  <div
                    className="program-hero__image-overlay"
                    aria-hidden="true"
                  >
                    <span className="program-hero__overlay-badge">
                      Official Curriculum
                    </span>
                  </div>
                </div>

                <div className="program-hero__card-body">
                  <div className="program-hero__card-specs">
                    <div className="card-spec-item">
                      <span className="card-spec-label">Modules</span>
                      <strong className="card-spec-value">
                        {program.modules.length}{" "}
                        {program.modules.length === 1 ? "Module" : "Modules"}
                      </strong>
                    </div>
                    <div className="card-spec-item">
                      <span className="card-spec-label">Activities</span>
                      <strong className="card-spec-value">
                        {totalActivities}{" "}
                        {totalActivities === 1 ? "Activity" : "Activities"}
                      </strong>
                    </div>
                    <div className="card-spec-item">
                      <span className="card-spec-label">Published Release</span>
                      <strong className="card-spec-value">
                        Version {program.version_number}
                      </strong>
                    </div>
                    <div className="card-spec-item">
                      <span className="card-spec-label">Access Level</span>
                      <strong className="card-spec-value">
                        {freeEnrollmentAvailable
                          ? "Free Enrollment"
                          : "Restricted"}
                      </strong>
                    </div>
                  </div>

                  <div className="program-hero__card-cta">
                    <Link
                      className="button button--ink button--full-width"
                      href={ROUTES.login}
                    >
                      {freeEnrollmentAvailable
                        ? "Sign in to start free"
                        : "Sign in"}
                    </Link>
                  </div>
                </div>
              </div>
            </aside>
          </section>

          {/* Curriculum / Modules Breakdown Section */}
          <section
            className="detail-section program-curriculum-section"
            aria-labelledby="module-list-title"
          >
            <div className="section-heading program-curriculum-heading">
              <div>
                <p className="kicker">Course Curriculum</p>
                <h2 id="module-list-title">Published Syllabus</h2>
              </div>
              <div className="program-curriculum-meta">
                <span className="curriculum-count-badge">
                  {program.modules.length}{" "}
                  {program.modules.length === 1 ? "Module" : "Modules"} ·{" "}
                  {totalActivities}{" "}
                  {totalActivities === 1 ? "Activity" : "Activities"}
                </span>
              </div>
            </div>

            <div className="course-path program-modules-stack">
              {program.modules.map((module) => (
                <ModuleCard
                  className="module-card public-module-detail-card"
                  key={module.id}
                  title={module.title}
                  titleId={`program-module-${module.id}-title`}
                  header={
                    <header className="public-module-card__header">
                      <div className="public-module-card__title-group">
                        <span className="public-module-card__number">
                          Module {module.position}
                        </span>
                        <h3
                          id={`program-module-${module.id}-title`}
                          className="public-module-card__title"
                        >
                          {module.title}
                        </h3>
                      </div>
                      <span className="public-module-card__activity-badge">
                        {module.activities.length}{" "}
                        {module.activities.length === 1
                          ? "activity"
                          : "activities"}
                      </span>
                    </header>
                  }
                >
                  {module.activities.length > 0 ? (
                    <div className="public-module-card__activities">
                      <ul
                        className="public-activity-list"
                        aria-label={`Activities in ${module.title}`}
                      >
                        {module.activities.map((activity) => (
                          <li className="public-activity-row" key={activity.id}>
                            <div className="public-activity-row__icon-wrap">
                              {activityKindIcon(activity.kind)}
                            </div>
                            <div className="public-activity-row__main">
                              <span className="public-activity-row__title">
                                {activity.title}
                              </span>
                              <span className="public-activity-row__kind">
                                {formatPublicActivityKind(activity.kind)}
                              </span>
                            </div>
                            <div className="public-activity-row__meta">
                              {activity.is_required ? (
                                <span className="activity-requirement-badge activity-requirement-badge--required">
                                  Required
                                </span>
                              ) : (
                                <span className="activity-requirement-badge activity-requirement-badge--core">
                                  Core
                                </span>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </ModuleCard>
              ))}
            </div>
          </section>

          {/* Bottom Call to Action Section */}
          <section
            className="program-bottom-cta"
            aria-labelledby="bottom-cta-heading"
          >
            <div className="program-bottom-cta__inner">
              <div className="program-bottom-cta__copy">
                <h2
                  id="bottom-cta-heading"
                  className="program-bottom-cta__title"
                >
                  Start learning today
                </h2>
                <p className="program-bottom-cta__description">
                  Sign in or create your learner account to access the published
                  curriculum and your learning workspace.
                </p>
              </div>
              <div className="program-bottom-cta__actions">
                <Link className="button button--ink" href={ROUTES.login}>
                  {freeEnrollmentAvailable
                    ? "Sign in to start free"
                    : "Sign in"}
                </Link>
                <Link className="button button--outline" href={ROUTES.register}>
                  Create learner account →
                </Link>
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}

async function settleConcurrentReads<A, B>(
  first: Promise<A>,
  second: Promise<B>,
): Promise<[A, B]> {
  const [firstResult, secondResult] = await Promise.allSettled([first, second]);
  const failures = [firstResult, secondResult].filter(
    (result): result is PromiseRejectedResult => result.status === "rejected",
  );
  const sessionFailure = failures.find((failure) =>
    isSessionExpiredError(failure.reason),
  );

  if (sessionFailure) throw sessionFailure.reason;
  if (firstResult.status === "rejected") throw firstResult.reason;
  if (secondResult.status === "rejected") throw secondResult.reason;
  return [firstResult.value, secondResult.value];
}

export async function identityState(
  api: LearnerApi,
  programId?: string,
  signal?: AbortSignal,
): Promise<{
  me: MeResponse;
  programs: ProgramSummaryResponse[];
  learning?: LearningResponse;
}> {
  const [me, programs] = await settleConcurrentReads(
    api.me({ signal }),
    programId
      ? Promise.resolve<ProgramSummaryResponse[]>([])
      : api.listPrograms(50, { signal }).then((response) => response.items),
  );
  const selectedProgramId =
    programId ?? selectPublishedFreeCourse(programs)?.id;
  let learning: LearningResponse | undefined;

  if (hasMembershipRole(me) && selectedProgramId) {
    try {
      learning = await api.learning(selectedProgramId, undefined, { signal });
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
    }
  }

  return { me, programs, learning };
}

export async function loadProgramLearningState(
  slug: string,
  api: LearnerApi,
  signal?: AbortSignal,
) {
  const [program, me] = await settleConcurrentReads(
    api.program(slug, { signal }),
    api.me({ signal }),
  );
  let learning: LearningResponse | undefined;
  if (hasMembershipRole(me)) {
    try {
      learning = await api.learning(program.id, undefined, { signal });
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
    }
  }
  return { program, me, programs: [] as ProgramSummaryResponse[], learning };
}

export function selectPublishedFreeCourse(
  programs: ProgramSummaryResponse[],
): ProgramSummaryResponse | undefined {
  return programs.find((program) => isFreeEnrollmentProgram(program));
}

function projectionLabel(projection: LearningResponse["projection"]): string {
  return `${Math.round(projection.percentage * 100)}% · ${projection.completed_count} / ${projection.denominator}`;
}

function projectionStateLabel(
  projection: LearningResponse["projection"],
): string {
  if (projection.percentage >= 1) return "Completed";
  if (projection.completed_count > 0) return "In progress";
  return "Ready to start";
}

export function isSessionExpiredError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function isForbiddenError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

export function learningPathStatusForError(
  error: unknown,
): "unavailable" | "forbidden" | "error" {
  if (error instanceof ApiError && error.status === 404) return "unavailable";
  if (isForbiddenError(error)) return "forbidden";
  return "error";
}

export type MembershipCleanupContext = {
  membershipKnown: boolean;
  membershipAvailable: boolean;
  personId: string | null;
};

export type MembershipCleanupToken = MembershipCleanupContext & {
  generation: number;
};

export type MembershipCleanupGuard = {
  activate: () => void;
  begin: (context: MembershipCleanupContext) => MembershipCleanupToken;
  invalidate: () => void;
  dispose: () => void;
  canCommit: (
    token: MembershipCleanupToken,
    current: MembershipCleanupContext,
  ) => boolean;
};

/**
 * Membership cleanup is destructive to bounded local recovery data. An async
 * completion may publish only while its generation, person, and membership
 * context still describe the current mounted surface.
 */
export function createMembershipCleanupGuard(): MembershipCleanupGuard {
  let mounted = false;
  let generation = 0;
  return {
    activate() {
      mounted = true;
      generation += 1;
    },
    begin(context) {
      generation += 1;
      return { ...context, generation };
    },
    invalidate() {
      generation += 1;
    },
    dispose() {
      mounted = false;
      generation += 1;
    },
    canCommit(token, current) {
      return (
        mounted &&
        token.generation === generation &&
        token.personId === current.personId &&
        token.membershipKnown === current.membershipKnown &&
        token.membershipAvailable === current.membershipAvailable
      );
    },
  };
}

export function useInvalidateDraftsWithoutMembership(
  membershipKnown: boolean,
  membershipAvailable: boolean,
  personId: string | null,
): MembershipDraftCleanup {
  const [status, setStatus] =
    useState<MembershipDraftCleanup["status"]>("idle");
  const cleanupGuardRef = useRef(createMembershipCleanupGuard());
  useEffect(() => {
    const guard = cleanupGuardRef.current;
    guard.activate();
    return () => guard.dispose();
  }, []);
  const attempt = useCallback(async () => {
    const context: MembershipCleanupContext = {
      membershipKnown,
      membershipAvailable,
      personId,
    };
    const guard = cleanupGuardRef.current;
    const token = guard.begin(context);
    const canPublish = () =>
      guard.canCommit(token, {
        membershipKnown,
        membershipAvailable,
        personId,
      });
    if (!membershipKnown || membershipAvailable) {
      if (canPublish()) setStatus("idle");
      return;
    }
    if (canPublish()) setStatus("pending");
    if (!personId) {
      if (canPublish()) setStatus("failed");
      return;
    }
    const storage = availableLocalStorage(window);
    if (!storage) {
      if (canPublish()) setStatus("failed");
      return;
    }
    const result = await clearLearnerLocalDraftsForPersonWithLock(
      storage,
      personId,
    );
    if (canPublish()) setStatus(result.ok ? "success" : "failed");
  }, [membershipAvailable, membershipKnown, personId]);
  useEffect(() => {
    const guard = cleanupGuardRef.current;
    void attempt();
    return () => guard.invalidate();
  }, [attempt]);
  return {
    status,
    retry: () => void attempt(),
  };
}

export function enrollmentFailureMessage(error: unknown): {
  message: string;
  recoveryHref?: string;
  recoveryLabel?: string;
} {
  if (error instanceof ApiError && error.status === 401) {
    return {
      message: "Your session expired before the course could start.",
      recoveryHref: ROUTES.sessionExpired,
      recoveryLabel: "Sign in again",
    };
  }
  if (error instanceof ApiError && error.status === 403) {
    if (error.code === "tenant_context_required") {
      return {
        message:
          "Learner access could not be activated automatically. Your account and existing progress were not changed.",
        recoveryHref: LEARNER_SUPPORT_HREF,
        recoveryLabel: "Contact learner support",
      };
    }
    if (error.code === "self_attested_eligibility_denied") {
      return {
        message:
          "Free-course access could not be confirmed for this account. Your account and existing progress were not changed.",
        recoveryHref: LEARNER_SUPPORT_HREF,
        recoveryLabel: "Contact learner support",
      };
    }
    return {
      message:
        "This account is not currently authorized to start the free course. Your existing account data was not changed.",
      recoveryHref: LEARNER_SUPPORT_HREF,
      recoveryLabel: "Contact learner support",
    };
  }
  return {
    message: `${errorText(error)} You can retry without losing progress.`,
  };
}

function firstActionableActivity(
  learning: LearningResponse,
): LearningActivityResponse | undefined {
  const activities = learning.modules.flatMap((module) => module.activities);
  return (
    activities.find(
      (activity) => activity.state.toLowerCase() === "in_progress",
    ) ??
    activities.find((activity) => activity.state.toLowerCase() === "available")
  );
}

function learnerDisplayName(me: MeResponse): string {
  const displayName = me.display_name?.trim();
  return displayName ? displayName.split(/\s+/)[0] : "Learner";
}

export function learnerHomeMode(
  membershipAvailable: boolean,
  onboardingReady: boolean,
): "activation" | "onboarding" | "workspace" {
  if (!membershipAvailable) return "activation";
  return onboardingReady ? "workspace" : "onboarding";
}

export function HomeLearningPath({ learning }: { learning: LearningResponse }) {
  return (
    <section
      className="home-learning-path"
      aria-labelledby="learning-path-title"
    >
      <div className="home-learning-path__heading">
        <div>
          <p className="kicker">Your course path</p>
          <h2 id="learning-path-title">Move through one module at a time</h2>
        </div>
        <span>{projectionLabel(learning.projection)}</span>
      </div>
      <ol className="home-module-list">
        {learning.modules.map((module) => {
          const completed = module.activities.filter(
            (activity) => activity.state.toLowerCase() === "completed",
          ).length;
          const current = module.activities.some((activity) =>
            ["available", "in_progress"].includes(activity.state.toLowerCase()),
          );
          const awaitingReview = module.activities.some(
            (activity) => activity.state.toLowerCase() === "awaiting_review",
          );
          const complete =
            module.activities.length > 0 &&
            completed === module.activities.length;
          const locked = !complete && !current && !awaitingReview;
          const statusLabel = complete
            ? "Complete"
            : awaitingReview
              ? "Awaiting review"
              : current
                ? "Current"
                : module.activities.length === 0
                  ? "Unavailable"
                  : "Locked";
          const row = (
            <>
              <span className="home-module-list__number" aria-hidden="true">
                {complete ? <CheckCircle2 size={18} /> : module.position}
              </span>
              <span className="home-module-list__copy">
                <strong>{module.title}</strong>
                <span>
                  {module.activities.length === 0
                    ? "No published activities"
                    : awaitingReview
                      ? `${completed} complete · feedback pending`
                      : `${completed} of ${module.activities.length} activities complete`}
                </span>
              </span>
              <span
                className={`home-module-list__state${
                  complete
                    ? " is-complete"
                    : awaitingReview
                      ? " is-review"
                      : current
                        ? " is-current"
                        : ""
                }`}
              >
                {statusLabel}
              </span>
              {locked ? (
                <LockKeyhole size={17} aria-hidden="true" />
              ) : (
                <ChevronRight size={18} aria-hidden="true" />
              )}
            </>
          );
          return (
            <li key={module.id}>
              {locked ? (
                <div className="home-module-list__row" aria-disabled="true">
                  {row}
                </div>
              ) : (
                <Link
                  className="home-module-list__row"
                  href={ROUTES.module(learning.program_slug, module.id)}
                >
                  {row}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

const homeLearningLoop = [
  { label: "Watch", copy: "Learn the concept", icon: Play },
  { label: "Reflect", copy: "Make it your own", icon: PenLine },
  { label: "Implement", copy: "Apply it in practice", icon: Wrench },
  { label: "Review", copy: "Check your work", icon: Flag },
  { label: "Improve", copy: "Refine the next move", icon: Trophy },
] as const;

export function HomeLearningLoop() {
  return (
    <section
      className="home-learning-loop"
      aria-labelledby="learning-loop-title"
    >
      <div className="home-learning-loop__heading">
        <p className="kicker">How the course works</p>
        <h2 id="learning-loop-title">Your 5-step learning loop</h2>
      </div>
      <ol>
        {homeLearningLoop.map((step, index) => {
          const Icon = step.icon;
          return (
            <li key={step.label}>
              <span className="home-learning-loop__icon" aria-hidden="true">
                <Icon size={18} />
              </span>
              <strong>{step.label}</strong>
              <span>{step.copy}</span>
              {index < homeLearningLoop.length - 1 ? (
                <ArrowRight
                  className="home-learning-loop__arrow"
                  size={18}
                  aria-hidden="true"
                />
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function LearnerHomeEnrollmentCard({
  learning,
  program,
  api = defaultApi,
  afterEnrollmentHref,
  offlineRead: offlineReadOverride,
}: {
  learning?: LearningResponse;
  program?: ProgramSummaryResponse;
  api?: LearnerApi;
  afterEnrollmentHref?: string;
  offlineRead?: OfflineReadMetadata;
}) {
  const [enrollment, setEnrollment] = useState<"idle" | "saving" | "error">(
    "idle",
  );
  const [failure, setFailure] = useState<ReturnType<
    typeof enrollmentFailureMessage
  > | null>(null);
  const nextActivity = learning ? firstActionableActivity(learning) : undefined;
  const offlineRead =
    offlineReadOverride ?? getEarliestOfflineReadMetadata(learning, program);

  async function startFreeCourse() {
    if (!program || enrollment === "saving" || offlineRead) return;
    setEnrollment("saving");
    setFailure(null);
    try {
      await api.enrollFree(program.program_version_id);
      window.location.assign(
        afterEnrollmentHref ?? ROUTES.programLearning(program.slug),
      );
    } catch (error) {
      setEnrollment("error");
      setFailure(enrollmentFailureMessage(error));
    }
  }

  return (
    <section
      className="current-course-card"
      aria-labelledby="current-course-title"
      id="continue-learning"
    >
      <div className="current-course-card__topline">
        <p className="kicker">
          {learning ? "Continue learning" : "Free course"}
        </p>
        <span className="status-pill status-pill--neutral">
          {learning
            ? projectionStateLabel(learning.projection)
            : program
              ? "Published"
              : "Not available"}
        </span>
      </div>
      <div className="current-course-card__body">
        <h2 id="current-course-title">
          {learning?.program_title ??
            program?.title ??
            "No free course is published right now."}
        </h2>
        <p className="current-course-card__description">
          {learning
            ? learning.projection.percentage >= 1
              ? "Your required activities are complete. You can revisit the course path at any time."
              : nextActivity
                ? `Your next available step is “${nextActivity.title}”.`
                : "Open the course to review the activity states authorized for your enrollment."
            : program
              ? "Start the published Authority Closers Free Course and open Module 1."
              : "There is no published Free Course available to start in this workspace."}
        </p>
        {learning ? (
          <div className="course-progress" role="status">
            <div className="course-progress__labels">
              <span>{projectionStateLabel(learning.projection)}</span>
              <strong>{projectionLabel(learning.projection)}</strong>
            </div>
            <div
              className="course-progress__track"
              role="progressbar"
              aria-label="Course progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(
                Math.min(1, Math.max(0, learning.projection.percentage)) * 100,
              )}
            >
              <span
                style={{
                  width: `${Math.round(
                    Math.min(1, Math.max(0, learning.projection.percentage)) *
                      100,
                  )}%`,
                }}
              />
            </div>
          </div>
        ) : null}
        {offlineRead ? (
          <div
            className="offline-read-notice"
            id="learner-home-offline-read"
            role="status"
          >
            {offlineReadNotice(offlineRead)}
          </div>
        ) : null}
        {learning ? (
          <div className="current-course-card__actions">
            {offlineRead ? (
              <span
                className="button button--ink is-disabled"
                aria-disabled="true"
              >
                Reconnect to continue
              </span>
            ) : (
              <Link
                className="button button--ink"
                href={
                  nextActivity
                    ? ROUTES.activity(nextActivity.id)
                    : ROUTES.programLearning(learning.program_slug)
                }
              >
                {learning.projection.percentage >= 1
                  ? "Review course"
                  : "Continue"}
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
            )}
            <Link
              className="text-link"
              href={ROUTES.programLearning(learning.program_slug)}
            >
              View course outline
            </Link>
          </div>
        ) : program ? (
          <div className="current-course-card__actions">
            <button
              className="button button--ink"
              type="button"
              onClick={() => void startFreeCourse()}
              disabled={enrollment === "saving" || Boolean(offlineRead)}
            >
              {enrollment === "saving"
                ? "Starting free course…"
                : "Start free course"}
              <ArrowRight size={16} aria-hidden="true" />
            </button>
            <Link
              className="text-link"
              href={ROUTES.programDetail(program.slug)}
            >
              View course details
            </Link>
          </div>
        ) : null}
        {failure ? (
          <div className="enrollment-recovery" role="alert">
            <p>{failure.message}</p>
            {failure.recoveryHref ? (
              <Link className="text-link" href={failure.recoveryHref}>
                {failure.recoveryLabel}
              </Link>
            ) : (
              <button
                className="text-button"
                type="button"
                onClick={() => void startFreeCourse()}
              >
                Retry enrollment
              </button>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function LearnerHomeOnboardingRedirect() {
  return (
    <div className="surface-state" role="status" id="my-learning">
      <h1>Opening your learner profile…</h1>
    </div>
  );
}

export async function loadLearnerHomeState(
  api: LearnerApi,
  signal?: AbortSignal,
) {
  const [identity, onboarding] = await settleConcurrentReads(
    identityState(api, undefined, signal),
    api.onboarding({ signal }),
  );
  return { ...identity, onboarding };
}

export function LearnerHomeRuntime({ api = defaultApi }: { api?: LearnerApi }) {
  const state = useLoad(
    (signal) => loadLearnerHomeState(api, signal),
    () => false,
  );
  const onboardingReady =
    state.status === "ready" &&
    (state.value.onboarding.status === "completed" ||
      state.value.onboarding.status === "skipped");
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  const homeMode = learnerHomeMode(membershipAvailable, onboardingReady);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
    state.status === "ready" ? state.value.me.person_id : null,
  );
  useEffect(() => {
    if (state.status === "ready" && homeMode === "onboarding") {
      window.location.replace(ROUTES.onboarding);
    }
  }, [homeMode, state.status]);
  const publishedProgram =
    state.status === "ready"
      ? selectPublishedFreeCourse(state.value.programs)
      : undefined;
  const offlineRead =
    state.status === "ready"
      ? getEarliestOfflineReadMetadata(
          state.value.me,
          state.value.programs,
          state.value.learning,
          state.value.onboarding,
        )
      : null;
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Learner workspace"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" && homeMode === "onboarding" ? (
        <LearnerHomeOnboardingRedirect />
      ) : null}
      {state.status === "ready" && homeMode !== "onboarding" ? (
        <>
          <section
            className="dashboard-intro"
            aria-labelledby="dashboard-title"
          >
            <div>
              <p className="dashboard-intro__eyebrow">
                Your learning workspace
              </p>
              <h1 id="dashboard-title">
                Welcome back, {learnerDisplayName(state.value.me)}
              </h1>
              <p className="dashboard-intro__subhead">
                {membershipAvailable
                  ? "Pick up at the next available activity. Your course state is saved to this account."
                  : "Start the free course to activate your learner workspace. Access remains server-authorized."}
              </p>
            </div>
            {state.value.me.selected_tenant_id ? (
              <span className="dashboard-intro__tenant">Learner workspace</span>
            ) : null}
          </section>
          {offlineRead ? (
            <div
              className="offline-read-notice"
              id="learner-home-state-offline-read"
              role="status"
            >
              {offlineReadNotice(offlineRead)}
            </div>
          ) : null}
          {!membershipAvailable ? (
            <MembershipDraftCleanupNotice cleanup={draftCleanup} />
          ) : null}
          <div className="home-workspace-grid" id="my-learning">
            <LearnerHomeEnrollmentCard
              learning={state.value.learning}
              program={publishedProgram}
              api={api}
              afterEnrollmentHref={
                onboardingReady ? undefined : ROUTES.onboarding
              }
              offlineRead={offlineRead ?? undefined}
            />
            {state.value.learning ? (
              <HomeLearningPath learning={state.value.learning} />
            ) : null}
          </div>
          {state.value.learning ? <HomeLearningLoop /> : null}
        </>
      ) : null}
    </>
  );
}

function activityStateLabel(state: string): string {
  return state
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function activityLockReason(
  activity: LearningActivityResponse,
): string | null {
  if (activity.state.toLowerCase() !== "locked") return null;
  const missingActivities = activity.explanation.missing_activity_ids.length;
  const missingModules = activity.explanation.missing_module_ids.length;
  const blockers: string[] = [];
  if (missingActivities > 0)
    blockers.push(
      `${missingActivities} earlier required ${missingActivities === 1 ? "activity" : "activities"}`,
    );
  if (missingModules > 0)
    blockers.push(
      `${missingModules} prerequisite ${missingModules === 1 ? "module" : "modules"}`,
    );
  if (blockers.length > 0)
    return `Complete ${blockers.join(" and ")} to unlock.`;
  return "This step remains locked until the learning service authorizes access.";
}

function activityIcon(kind: string) {
  switch (kind.toUpperCase()) {
    case "VIDEO":
      return <Play size={13} />;
    case "REFLECTION":
      return <PenLine size={14} />;
    case "IMPLEMENTATION_CHALLENGE":
      return <Wrench size={14} />;
    case "REVIEW":
      return <Flag size={14} />;
    case "IMPROVE":
      return <Trophy size={14} />;
    default:
      return <FileText size={14} />;
  }
}

export function LearningActivityNavigation({
  activity,
  disabled = false,
}: {
  activity: LearningActivityResponse;
  disabled?: boolean;
}) {
  const lockedReason = activityLockReason(activity);
  const offlineRead = disabled || Boolean(getOfflineReadMetadata(activity));
  const unavailableReason = offlineRead
    ? "Reconnect to open this activity."
    : lockedReason;
  const content = (
    <>
      <span className="activity-row__order">
        {String(activity.position).padStart(2, "0")}
      </span>
      <span className="activity-row__icon" aria-hidden="true">
        {activity.state.toLowerCase() === "locked" ? (
          <LockKeyhole size={14} />
        ) : (
          activityIcon(activity.kind)
        )}
      </span>
      <span className="activity-row__copy">
        <strong>{activity.title}</strong>
        <span className="activity-row__objective">
          {activity.kind.replaceAll("_", " ")}
        </span>
        {lockedReason ? (
          <span className="activity-row__reason">{lockedReason}</span>
        ) : null}
      </span>
      <span className="activity-row__status">
        <span>
          {offlineRead
            ? "Reconnect to open"
            : activityStateLabel(activity.state)}
        </span>
        {unavailableReason ? (
          <LockKeyhole size={15} aria-hidden="true" />
        ) : (
          <ChevronRight size={16} aria-hidden="true" />
        )}
      </span>
    </>
  );
  if (activity.state.toLowerCase() === "locked" || offlineRead) {
    return (
      <li
        className={`activity-row activity-row--locked${offlineRead ? " activity-row--offline" : ""}`}
      >
        <div aria-disabled="true" title={unavailableReason ?? undefined}>
          {content}
        </div>
      </li>
    );
  }
  return (
    <li className="activity-row">
      <Link href={ROUTES.activity(activity.id)}>{content}</Link>
    </li>
  );
}

function learnerPrompt(activity: ActivityResponse): string | null {
  const prompt = activity.prompt?.trim() ?? "";
  return prompt || null;
}

const ACTIVITY_LOOP = [
  { kind: "VIDEO", label: "Watch" },
  { kind: "REFLECTION", label: "Reflect" },
  { kind: "IMPLEMENTATION_CHALLENGE", label: "Implement" },
  { kind: "REVIEW", label: "Review" },
  { kind: "IMPROVE", label: "Improve" },
] as const;

function activityKindLabel(kind: string): string {
  return (
    ACTIVITY_LOOP.find((step) => step.kind === kind.toUpperCase())?.label ??
    activityStateLabel(kind)
  );
}

function ActivityLoop({
  activities,
  currentActivityId,
  label,
}: {
  activities: LearningActivityResponse[];
  currentActivityId: string;
  label: string;
}) {
  return (
    <ol className="activity-loop" aria-label={label}>
      {activities.map((step) => {
        const current = step.id === currentActivityId;
        const lockedReason = activityLockReason(step);
        const completed = step.state.toLowerCase() === "completed";
        const content = (
          <>
            <span className="activity-loop__icon" aria-hidden="true">
              {completed ? (
                <CheckCircle2 size={16} />
              ) : lockedReason ? (
                <LockKeyhole size={15} />
              ) : (
                activityIcon(step.kind)
              )}
            </span>
            <span className="activity-loop__copy">
              <strong>{activityKindLabel(step.kind)}</strong>
              <span className="activity-loop__status">
                {current
                  ? "Current"
                  : getOfflineReadMetadata(step)
                    ? "Reconnect to open"
                    : activityStateLabel(step.state)}
              </span>
              {lockedReason ? (
                <span className="activity-loop__reason">{lockedReason}</span>
              ) : null}
            </span>
            {!lockedReason && !current && !getOfflineReadMetadata(step) ? (
              <ChevronRight
                className="activity-loop__chevron"
                size={16}
                aria-hidden="true"
              />
            ) : null}
          </>
        );
        return (
          <li
            className={`activity-loop__step${current ? " is-current" : ""}${completed ? " is-complete" : ""}${lockedReason ? " is-locked" : ""}${getOfflineReadMetadata(step) ? " is-offline" : ""}`}
            aria-current={current ? "step" : undefined}
            key={step.id}
          >
            {!lockedReason && !current && !getOfflineReadMetadata(step) ? (
              <Link href={ROUTES.activity(step.id)}>{content}</Link>
            ) : (
              <div
                aria-disabled={
                  lockedReason || getOfflineReadMetadata(step)
                    ? "true"
                    : undefined
                }
                title={
                  getOfflineReadMetadata(step)
                    ? "Reconnect to open this activity."
                    : undefined
                }
              >
                {content}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

type ActivityRecoveryCleanupAttempt = {
  result:
    | { ok: true }
    | { ok: false; reason: "quota" | "unavailable" | "busy" | "changed" };
  envelope: ActivityDraftEnvelope | null;
  rawSnapshot: LocalDraftRawSnapshot | null;
};

export type ActivityOperationLock = {
  activate: () => void;
  acquire: () => number | null;
  release: (token: number) => void;
  invalidate: () => void;
  dispose: () => void;
  canCommit: (token: number) => boolean;
};

export function activityStateForScope<T>(
  state: { scopeKey: string; value: T } | null,
  scopeKey: string,
): T | null {
  return state?.scopeKey === scopeKey ? state.value : null;
}

export function createActivityOperationLock(): ActivityOperationLock {
  let mounted = false;
  let inFlight = false;
  let generation = 0;
  return {
    activate() {
      mounted = true;
      generation += 1;
    },
    acquire() {
      if (!mounted || inFlight) return null;
      inFlight = true;
      return generation;
    },
    release(token) {
      if (token === generation) inFlight = false;
    },
    invalidate() {
      generation += 1;
      inFlight = false;
    },
    dispose() {
      mounted = false;
      generation += 1;
      inFlight = false;
    },
    canCommit(token) {
      return mounted && token === generation;
    },
  };
}

export type ActivityRecoveryHydrationGuard = {
  begin: () => number;
  markLearnerEdit: () => void;
  canApply: (hydrationGeneration: number) => boolean;
};

/**
 * Recovery hydration is advisory. A learner edit wins over a delayed local
 * read, even if the read began first and the recovery copy matches the server.
 */
export function createActivityRecoveryHydrationGuard(): ActivityRecoveryHydrationGuard {
  let learnerEditGeneration = 0;
  return {
    begin: () => learnerEditGeneration,
    markLearnerEdit: () => {
      learnerEditGeneration += 1;
    },
    canApply: (hydrationGeneration) =>
      hydrationGeneration === learnerEditGeneration,
  };
}

async function clearActivityRecoveryCopy(
  storage: Storage,
  scope: ActivityDraftScope,
  expected?: ActivityDraftEnvelope,
  expectedRaw?: LocalDraftRawSnapshot,
): Promise<ActivityRecoveryCleanupAttempt> {
  let target = expected;
  const rawSnapshot = expectedRaw;
  if (!target && !rawSnapshot) {
    const current = await readActivityLocalDraftWithLock(storage, scope);
    if (current.status === "missing") {
      return { result: { ok: true }, envelope: null, rawSnapshot: null };
    }
    if (current.status !== "ready") {
      return {
        result: {
          ok: false,
          reason: current.status === "unavailable" ? "unavailable" : "changed",
        },
        envelope: null,
        rawSnapshot:
          current.status === "expired" || current.status === "invalid"
            ? current.cleanupTarget
            : null,
      };
    }
    target = current.envelope;
  }
  const result = rawSnapshot
    ? await purgeActivityLocalDraftIfMatchesWithLock(
        storage,
        scope,
        rawSnapshot,
      )
    : await clearActivityLocalDraftIfMatchesWithLock(
        storage,
        scope,
        target ?? null,
      );
  if (!result.ok && result.reason === "changed") {
    const latest = await readActivityLocalDraftWithLock(storage, scope);
    if (latest.status === "missing") {
      return { result: { ok: true }, envelope: null, rawSnapshot: null };
    }
    if (latest.status === "ready") {
      return { result, envelope: latest.envelope, rawSnapshot: null };
    }
    if (latest.status === "expired" || latest.status === "invalid") {
      return {
        result: {
          ok: false,
          reason:
            latest.cleanupStatus === "unavailable" ? "unavailable" : "changed",
        },
        envelope: null,
        rawSnapshot: latest.cleanupTarget,
      };
    }
    return {
      result: { ok: false, reason: "unavailable" },
      envelope: null,
      rawSnapshot: null,
    };
  }
  return { result, envelope: target ?? null, rawSnapshot: rawSnapshot ?? null };
}

export function ConnectedActivityWorkspace({
  activity,
  learning,
  learningPathStatus = "idle",
  learningPathError,
  onRetryLearningPath,
  onMutationCommitted,
  tenantId,
  personId,
  api = defaultApi,
}: {
  activity: ActivityResponse;
  learning?: LearningResponse;
  learningPathStatus?:
    | "idle"
    | "loading"
    | "ready"
    | "unavailable"
    | "forbidden"
    | "error";
  learningPathError?: unknown;
  onRetryLearningPath?: () => void;
  onMutationCommitted?: (kind: "draft" | "evidence") => void | Promise<void>;
  tenantId?: string;
  personId?: string;
  api?: LearnerApi;
}) {
  const initialResponse =
    typeof activity.draft_payload?.response === "string"
      ? activity.draft_payload.response
      : "";
  const [response, setResponse] = useState(initialResponse);
  const [savedResponse, setSavedResponse] = useState(initialResponse);
  const [draftRevision, setDraftRevision] = useState(activity.draft_revision);
  const [activityRevision, setActivityRevision] = useState(activity.revision);
  const [mutation, setMutation] = useState<
    "idle" | "saving" | "saved" | "submitted" | "error"
  >("idle");
  const [message, setMessage] = useState("");
  const [reauthRequired, setReauthRequired] = useState(false);
  const [failureKind, setFailureKind] = useState<MutationFailureKind | null>(
    null,
  );
  const [lastOperation, setLastOperation] = useState<
    "draft" | "evidence" | null
  >(null);
  const [localDraftChecked, setLocalDraftChecked] = useState(false);
  const [localDraftRestored, setLocalDraftRestored] = useState(false);
  const [staleLocalDraft, setStaleLocalDraft] =
    useState<ActivityDraftEnvelope | null>(null);
  const [localCleanupState, setLocalCleanupState] = useState<{
    scopeKey: string;
    value: {
      draft: ActivityDraftEnvelope | null;
      raw: LocalDraftRawSnapshot | null;
      reason: "server-save" | "expired-record";
    };
  } | null>(null);
  const [localPersistence, setLocalPersistence] = useState<
    "idle" | "saved" | "failed"
  >("idle");
  const [recoveryMessageState, setRecoveryMessageState] = useState<{
    scopeKey: string;
    value: string;
  } | null>(null);
  const activityOperationLockRef = useRef(createActivityOperationLock());
  const activityRecoveryHydrationGuardRef = useRef(
    createActivityRecoveryHydrationGuard(),
  );
  const activityGenerationRef = useRef(0);
  const localDraftStorage =
    typeof window === "undefined" ? null : availableLocalStorage(window);
  const dirty = mutation !== "submitted" && response !== savedResponse;
  const prompt = learnerPrompt(activity);
  const writableState =
    prompt !== null &&
    ["available", "in_progress"].includes(activity.state.toLowerCase()) &&
    mutation !== "submitted";
  const allowedActions = new Set(activity.allowed_actions);
  const canSaveDraft = writableState && allowedActions.has("save_draft");
  const canSubmitEvidence =
    writableState && allowedActions.has("submit_evidence");
  const canEditResponse = canSaveDraft || canSubmitEvidence;
  const evidenceType = (
    {
      reflection: "reflection",
      implementation_challenge: "implementation",
      review: "review",
      improve: "improvement",
    } as Record<
      string,
      "reflection" | "implementation" | "review" | "improvement"
    >
  )[activity.kind.toLowerCase()];
  const responseLabel =
    (
      {
        reflection: "Your reflection",
        implementation_challenge: "Implementation evidence",
        review: "Review record",
        improve: "Next improvement",
      } as Record<string, string>
    )[activity.kind.toLowerCase()] ?? "Your response";
  const lockedReason = activityLockReason(activity);
  const localDraftScope = useMemo<ActivityDraftScope | null>(
    () =>
      tenantId && personId
        ? {
            kind: "activity",
            tenantId,
            personId,
            enrollmentId: activity.enrollment_id,
            activityId: activity.id,
          }
        : null,
    [activity.enrollment_id, activity.id, personId, tenantId],
  );
  const activityScopeKey = JSON.stringify([
    tenantId ?? null,
    personId ?? null,
    activity.enrollment_id,
    activity.id,
  ]);
  const activeCleanupState = activityStateForScope(
    localCleanupState,
    activityScopeKey,
  );
  const localCleanupPendingDraft = activeCleanupState?.draft ?? null;
  const localCleanupPendingRaw = activeCleanupState?.raw ?? null;
  const localCleanupPendingReason = activeCleanupState?.reason ?? null;
  const recoveryMessage = activityStateForScope(
    recoveryMessageState,
    activityScopeKey,
  );

  const setLocalCleanupPending = useCallback(
    (
      draft: ActivityDraftEnvelope | null,
      raw: LocalDraftRawSnapshot | null,
      reason: "server-save" | "expired-record",
    ) => {
      setLocalCleanupState({
        scopeKey: activityScopeKey,
        value: { draft, raw, reason },
      });
    },
    [activityScopeKey],
  );

  const clearLocalCleanupPending = useCallback(() => {
    setLocalCleanupState(null);
  }, []);

  const setRecoveryMessage = useCallback(
    (message: string | null) => {
      setRecoveryMessageState(
        message === null
          ? null
          : { scopeKey: activityScopeKey, value: message },
      );
    },
    [activityScopeKey],
  );

  useEffect(() => {
    const generation = ++activityGenerationRef.current;
    const operationLock = activityOperationLockRef.current;
    operationLock.activate();
    return () => {
      if (activityGenerationRef.current === generation) {
        activityGenerationRef.current += 1;
      }
      operationLock.dispose();
    };
  }, [activity.enrollment_id, activity.id, personId, tenantId]);

  function beginActivityOperation(): {
    generation: number;
    token: number;
  } | null {
    const generation = activityGenerationRef.current;
    const token = activityOperationLockRef.current.acquire();
    return token === null ? null : { generation, token };
  }

  function canCommitActivityOperation(operation: {
    generation: number;
    token: number;
  }): boolean {
    return (
      operation.generation === activityGenerationRef.current &&
      activityOperationLockRef.current.canCommit(operation.token)
    );
  }
  const draftStatus =
    mutation === "saving"
      ? "Saving to the server…"
      : mutation === "saved"
        ? "Saved to the server"
        : mutation === "error"
          ? "Save needs attention"
          : localPersistence === "failed" && dirty
            ? "Not saved on this device"
            : localDraftRestored && dirty
              ? "Local draft restored — not yet saved"
              : localPersistence === "saved" && dirty
                ? "Recovery copy saved on this device — not the server"
                : dirty
                  ? "Unsaved local changes"
                  : initialResponse
                    ? "Server draft restored"
                    : "Draft is not submitted";

  useEffect(() => {
    let active = true;
    const hydrationGeneration =
      activityRecoveryHydrationGuardRef.current.begin();
    if (!localDraftScope || !localDraftStorage) {
      queueMicrotask(() => {
        if (!active) return;
        setLocalPersistence("failed");
        setLocalDraftChecked(true);
      });
      return () => {
        active = false;
      };
    }
    void readActivityLocalDraftWithLock(
      localDraftStorage,
      localDraftScope,
    ).then((localDraft) => {
      if (!active) return;
      if (localDraft.status === "ready") {
        if (
          localDraftMatchesServer(
            localDraft.envelope,
            activity.draft_revision,
            activityServerFingerprint(initialResponse),
          )
        ) {
          if (
            activityRecoveryHydrationGuardRef.current.canApply(
              hydrationGeneration,
            ) &&
            localDraft.envelope.draft.response !== initialResponse
          ) {
            setResponse(localDraft.envelope.draft.response);
            setLocalDraftRestored(true);
            setLocalPersistence("saved");
          }
        } else {
          setStaleLocalDraft(localDraft.envelope);
        }
      } else if (localDraft.status === "unavailable") {
        setLocalPersistence("failed");
        setRecoveryMessage(
          "This browser could not verify local activity recovery storage. The server activity remains authoritative; keep any response you need before leaving.",
        );
      } else if (
        localDraft.status === "expired" ||
        localDraft.status === "invalid"
      ) {
        setLocalCleanupPending(
          null,
          localDraft.cleanupTarget,
          "expired-record",
        );
        setLocalPersistence("failed");
        setRecoveryMessage(
          localDraft.status === "expired"
            ? "An expired activity recovery copy could not be removed under the shared lock. Retry local cleanup before leaving."
            : "An invalid activity recovery copy could not be removed under the shared lock. Retry local cleanup before leaving.",
        );
      }
      setLocalDraftChecked(true);
    });
    return () => {
      active = false;
    };
  }, [
    activity.draft_revision,
    activity.enrollment_id,
    activity.id,
    initialResponse,
    localDraftScope,
    localDraftStorage,
    setLocalCleanupPending,
    setRecoveryMessage,
  ]);

  useEffect(() => {
    if (!localDraftChecked) return;
    if (staleLocalDraft) return;
    let active = true;
    if (!localDraftScope) {
      if (dirty) {
        queueMicrotask(() => {
          if (active) setLocalPersistence("failed");
        });
      }
      return () => {
        active = false;
      };
    }
    if (dirty) {
      if (!localDraftStorage) {
        queueMicrotask(() => {
          if (active) setLocalPersistence("failed");
        });
        return () => {
          active = false;
        };
      }
      void writeActivityLocalDraftWithLock(localDraftStorage, {
        scope: localDraftScope,
        response,
        baseRevision: draftRevision,
        serverFingerprint: activityServerFingerprint(savedResponse),
      }).then((result) => {
        if (active) setLocalPersistence(result.ok ? "saved" : "failed");
      });
    } else {
      if (localDraftStorage) {
        void clearActivityRecoveryCopy(localDraftStorage, localDraftScope).then(
          ({ result, envelope, rawSnapshot }) => {
            if (!active) return;
            if (!result.ok && envelope) {
              setLocalCleanupPending(envelope, null, "server-save");
            } else if (!result.ok && rawSnapshot) {
              setLocalCleanupPending(null, rawSnapshot, "expired-record");
            } else if (result.ok) {
              clearLocalCleanupPending();
            }
            setLocalPersistence(result.ok ? "idle" : "failed");
          },
        );
      } else
        queueMicrotask(() => {
          if (active) setLocalPersistence("idle");
        });
    }
    return () => {
      active = false;
    };
  }, [
    dirty,
    draftRevision,
    localDraftChecked,
    localDraftScope,
    localDraftStorage,
    response,
    savedResponse,
    clearLocalCleanupPending,
    setLocalCleanupPending,
    staleLocalDraft,
  ]);

  useEffect(() => registerBeforeUnloadGuard(window, dirty), [dirty]);

  useEffect(
    () =>
      registerInternalNavigationGuard(
        document,
        dirty && localPersistence === "failed",
        () =>
          window.confirm(
            "This browser could not retain a recovery copy. Leave this activity and discard the unsaved response?",
          ),
      ),
    [dirty, localPersistence],
  );

  useEffect(
    () =>
      registerHistoryNavigationGuard(
        window as unknown as Parameters<
          typeof registerHistoryNavigationGuard
        >[0],
        dirty && localPersistence === "failed",
        () =>
          window.confirm(
            "This browser could not retain a recovery copy. Leave this activity and discard the unsaved response?",
          ),
      ),
    [dirty, localPersistence],
  );

  function online(): boolean {
    return typeof navigator === "undefined" ? true : navigator.onLine;
  }

  function mutationErrorMessage(
    error: unknown,
    kind: MutationFailureKind,
    locallyStored: boolean,
  ): string {
    if (kind === "conflict") {
      return locallyStored
        ? "The server revision changed elsewhere. Reload to compare this recovery copy with the latest activity before saving again."
        : "The server revision changed elsewhere, and this browser could not retain a recovery copy. Copy/export your response before reloading.";
    }
    if (kind === "offline") {
      return locallyStored
        ? "You are offline. A bounded recovery copy is stored on this device; reconnect and retry this operation."
        : "You are offline, and this browser could not retain a recovery copy. Keep this page open or copy/export your response.";
    }
    return errorText(error);
  }

  function refreshCommittedMutationState(kind: "draft" | "evidence") {
    try {
      const refresh = onMutationCommitted?.(kind);
      if (refresh) void refresh.catch(() => undefined);
    } catch {
      // The authoritative mutation already succeeded. Dependent path recovery
      // is owned by the parent and must not rewrite that success as a failure.
    }
  }

  async function save() {
    if (!canSaveDraft) return;
    const operation = beginActivityOperation();
    if (!operation) return;
    setLastOperation("draft");
    setMutation("saving");
    setMessage("");
    setReauthRequired(false);
    setFailureKind(null);
    let locallyStored = false;
    let localRecoveryUsable = false;
    let cleanupTarget: ActivityDraftEnvelope | null = null;
    let cleanupRawSnapshot: LocalDraftRawSnapshot | null = null;
    try {
      if (localDraftScope && localDraftStorage) {
        const localWrite = dirty
          ? await writeActivityLocalDraftWithLockAndEnvelope(
              localDraftStorage,
              {
                scope: localDraftScope,
                response,
                baseRevision: draftRevision,
                serverFingerprint: activityServerFingerprint(savedResponse),
              },
            )
          : null;
        if (localWrite) {
          localRecoveryUsable = localWrite.result.ok;
          if (localWrite.result.ok) cleanupTarget = localWrite.envelope;
          locallyStored = localWrite.result.ok;
          setLocalPersistence(localWrite.result.ok ? "saved" : "failed");
        } else {
          const current = await readActivityLocalDraftWithLock(
            localDraftStorage,
            localDraftScope,
          );
          if (current.status !== "unavailable") localRecoveryUsable = true;
          if (current.status === "ready") cleanupTarget = current.envelope;
          if (current.status === "expired" || current.status === "invalid") {
            cleanupRawSnapshot = current.cleanupTarget;
          }
        }
      }
      if (!canCommitActivityOperation(operation)) return;
      const saved = await api.saveDraft(
        activity.id,
        { response },
        draftRevision,
      );
      if (!canCommitActivityOperation(operation)) return;
      setDraftRevision(saved.revision);
      setActivityRevision(saved.activity_revision);
      setSavedResponse(response);
      setMutation("saved");
      setMessage("Draft saved by the server.");
      setLastOperation(null);
      setLocalDraftRestored(false);
      let cleanupMessage = "";
      if (
        localDraftScope &&
        localDraftStorage &&
        (cleanupTarget || cleanupRawSnapshot)
      ) {
        const cleanup = await clearActivityRecoveryCopy(
          localDraftStorage,
          localDraftScope,
          cleanupTarget ?? undefined,
          cleanupRawSnapshot ?? undefined,
        );
        if (!canCommitActivityOperation(operation)) return;
        if (!cleanup.result.ok) {
          if (cleanup.envelope) {
            setLocalCleanupPending(cleanup.envelope, null, "server-save");
          } else if (cleanup.rawSnapshot) {
            setLocalCleanupPending(null, cleanup.rawSnapshot, "expired-record");
          }
          cleanupMessage =
            " The server save succeeded, but this browser could not verify or clear its recovery copy. Keep this page open and copy or download the response if it is available, then retry local cleanup.";
        } else {
          clearLocalCleanupPending();
        }
        setLocalPersistence(cleanup.result.ok ? "idle" : "failed");
      } else {
        setLocalPersistence(localRecoveryUsable ? "idle" : "failed");
        if (!localRecoveryUsable) {
          cleanupMessage =
            " The server save succeeded, but this browser could not verify or retain its recovery copy.";
        }
      }
      if (!canCommitActivityOperation(operation)) return;
      if (cleanupMessage)
        setMessage(`Draft saved by the server.${cleanupMessage}`);
      refreshCommittedMutationState("draft");
    } catch (error) {
      const kind = mutationFailureKind(error, online());
      if (!canCommitActivityOperation(operation)) return;
      setMutation("error");
      setFailureKind(kind);
      setMessage(mutationErrorMessage(error, kind, locallyStored));
      setReauthRequired(isSessionExpiredError(error));
    } finally {
      activityOperationLockRef.current.release(operation.token);
    }
  }
  async function submit() {
    if (!canSubmitEvidence || !evidenceType) return;
    const operation = beginActivityOperation();
    if (!operation) return;
    setLastOperation("evidence");
    setMutation("saving");
    setMessage("");
    setReauthRequired(false);
    setFailureKind(null);
    let locallyStored = false;
    let localRecoveryUsable = false;
    let cleanupTarget: ActivityDraftEnvelope | null = null;
    let cleanupRawSnapshot: LocalDraftRawSnapshot | null = null;
    try {
      if (localDraftScope && localDraftStorage) {
        const localWrite = dirty
          ? await writeActivityLocalDraftWithLockAndEnvelope(
              localDraftStorage,
              {
                scope: localDraftScope,
                response,
                baseRevision: draftRevision,
                serverFingerprint: activityServerFingerprint(savedResponse),
              },
            )
          : null;
        if (localWrite) {
          localRecoveryUsable = localWrite.result.ok;
          if (localWrite.result.ok) cleanupTarget = localWrite.envelope;
          locallyStored = localWrite.result.ok;
          setLocalPersistence(localWrite.result.ok ? "saved" : "failed");
        } else {
          const current = await readActivityLocalDraftWithLock(
            localDraftStorage,
            localDraftScope,
          );
          if (current.status !== "unavailable") localRecoveryUsable = true;
          if (current.status === "ready") cleanupTarget = current.envelope;
          if (current.status === "expired" || current.status === "invalid") {
            cleanupRawSnapshot = current.cleanupTarget;
          }
        }
      }
      if (!canCommitActivityOperation(operation)) return;
      const submitted = await api.submitEvidence(
        activity.id,
        evidenceType,
        { response },
        activityRevision,
      );
      if (!canCommitActivityOperation(operation)) return;
      setActivityRevision(submitted.activity_revision);
      setSavedResponse(response);
      setMutation("submitted");
      setMessage(
        "Evidence submitted. The server determined the current activity state.",
      );
      setLastOperation(null);
      setLocalDraftRestored(false);
      let cleanupMessage = "";
      if (
        localDraftScope &&
        localDraftStorage &&
        (cleanupTarget || cleanupRawSnapshot)
      ) {
        const cleanup = await clearActivityRecoveryCopy(
          localDraftStorage,
          localDraftScope,
          cleanupTarget ?? undefined,
          cleanupRawSnapshot ?? undefined,
        );
        if (!canCommitActivityOperation(operation)) return;
        if (!cleanup.result.ok) {
          if (cleanup.envelope) {
            setLocalCleanupPending(cleanup.envelope, null, "server-save");
          } else if (cleanup.rawSnapshot) {
            setLocalCleanupPending(null, cleanup.rawSnapshot, "expired-record");
          }
          cleanupMessage =
            " The server submission succeeded, but this browser could not verify or clear its recovery copy. Keep this page open and copy or download the response if it is available, then retry local cleanup.";
        } else {
          clearLocalCleanupPending();
        }
        setLocalPersistence(cleanup.result.ok ? "idle" : "failed");
      } else {
        setLocalPersistence(localRecoveryUsable ? "idle" : "failed");
        if (!localRecoveryUsable) {
          cleanupMessage =
            " The server submission succeeded, but this browser could not verify or retain its recovery copy.";
        }
      }
      if (!canCommitActivityOperation(operation)) return;
      if (cleanupMessage)
        setMessage(
          `Evidence submitted. The server determined the current activity state.${cleanupMessage}`,
        );
      refreshCommittedMutationState("evidence");
    } catch (error) {
      const kind = mutationFailureKind(error, online());
      if (!canCommitActivityOperation(operation)) return;
      setMutation("error");
      setFailureKind(kind);
      setMessage(mutationErrorMessage(error, kind, locallyStored));
      setReauthRequired(isSessionExpiredError(error));
    } finally {
      activityOperationLockRef.current.release(operation.token);
    }
  }

  async function keepServerActivityDraft() {
    const operation = beginActivityOperation();
    if (!operation) return;
    try {
      if (localDraftScope && localDraftStorage && staleLocalDraft) {
        const cleanup = await clearActivityRecoveryCopy(
          localDraftStorage,
          localDraftScope,
          staleLocalDraft,
        );
        if (!canCommitActivityOperation(operation)) return;
        if (!cleanup.result.ok) {
          if (cleanup.envelope) {
            setLocalCleanupPending(cleanup.envelope, null, "server-save");
          } else if (cleanup.rawSnapshot) {
            setLocalCleanupPending(null, cleanup.rawSnapshot, "expired-record");
          } else {
            setLocalCleanupPending(staleLocalDraft, null, "server-save");
          }
          setLocalPersistence("failed");
          setRecoveryMessage(
            "The server response was kept, but the local recovery copy could not be cleared. Retry cleanup or copy/download it before leaving.",
          );
          return;
        }
      }
      if (!canCommitActivityOperation(operation)) return;
      setResponse(savedResponse);
      setStaleLocalDraft(null);
      clearLocalCleanupPending();
      setLocalDraftRestored(false);
      setLocalPersistence("idle");
      setRecoveryMessage("The local recovery copy was discarded.");
    } finally {
      activityOperationLockRef.current.release(operation.token);
    }
  }

  async function retryLocalActivityCleanup() {
    const operation = beginActivityOperation();
    if (!operation) return;
    try {
      if (!localDraftScope || !localDraftStorage) {
        setRecoveryMessage(
          "Local cleanup is unavailable. Keep this page open or copy/download the recovery response.",
        );
        return;
      }
      if (localCleanupPendingRaw) {
        const result = await purgeActivityLocalDraftIfMatchesWithLock(
          localDraftStorage,
          localDraftScope,
          localCleanupPendingRaw,
        );
        if (!canCommitActivityOperation(operation)) return;
        if (!result.ok && result.reason === "changed") {
          const current = await readActivityLocalDraftWithLock(
            localDraftStorage,
            localDraftScope,
          );
          if (!canCommitActivityOperation(operation)) return;
          if (current.status === "missing") {
            clearLocalCleanupPending();
            setLocalPersistence("idle");
            setRecoveryMessage("The local recovery copy was cleared.");
            return;
          }
          if (current.status === "ready") {
            setLocalCleanupPending(current.envelope, null, "expired-record");
            setRecoveryMessage(
              "A newer activity recovery copy appeared during cleanup. It remains available for review and will not be removed automatically.",
            );
            return;
          }
          if (current.status === "expired" || current.status === "invalid") {
            setLocalCleanupPending(
              null,
              current.cleanupTarget,
              "expired-record",
            );
          }
        }
        if (!result.ok) {
          setRecoveryMessage(
            "Local cleanup is still unavailable. The recovery copy remains on this device.",
          );
          return;
        }
        clearLocalCleanupPending();
        setLocalPersistence("idle");
        setRecoveryMessage("The local recovery copy was cleared.");
        return;
      }
      if (!localCleanupPendingDraft) {
        setRecoveryMessage(
          "Local cleanup is unavailable. Keep this page open or copy/download the recovery response.",
        );
        return;
      }
      const cleanup = await clearActivityRecoveryCopy(
        localDraftStorage,
        localDraftScope,
        localCleanupPendingDraft,
      );
      if (!canCommitActivityOperation(operation)) return;
      if (!cleanup.result.ok) {
        if (cleanup.envelope) {
          setLocalCleanupPending(cleanup.envelope, null, "server-save");
        } else if (cleanup.rawSnapshot) {
          setLocalCleanupPending(null, cleanup.rawSnapshot, "expired-record");
        }
        setRecoveryMessage(
          "Local cleanup is still unavailable. The recovery copy remains on this device.",
        );
        return;
      }
      clearLocalCleanupPending();
      setLocalPersistence("idle");
      setRecoveryMessage("The local recovery copy was cleared.");
    } finally {
      activityOperationLockRef.current.release(operation.token);
    }
  }

  function mergeLocalActivityDraft() {
    if (!staleLocalDraft) return;
    setResponse(staleLocalDraft.draft.response);
    setStaleLocalDraft(null);
    setLocalDraftRestored(true);
    setMutation("idle");
    setRecoveryMessage(
      "The local recovery copy is now in the editor. Review it before saving against the latest server revision.",
    );
  }

  const recoveryResponse =
    staleLocalDraft?.draft.response ??
    localCleanupPendingDraft?.draft.response ??
    (dirty ? response : null);

  const visibleLearning = learningPathStatus === "ready" ? learning : undefined;
  const currentModule = visibleLearning?.modules.find(
    (module) => module.id === activity.module_id,
  );
  const moduleActivities = currentModule
    ? currentModule.activities.map((moduleActivity) =>
        moduleActivity.id === activity.id
          ? { ...moduleActivity, ...activity }
          : moduleActivity,
      )
    : [activity];
  const currentStepIndex = currentModule
    ? moduleActivities.findIndex(
        (moduleActivity) => moduleActivity.id === activity.id,
      )
    : -1;
  const currentStep = currentModule
    ? currentStepIndex >= 0
      ? currentStepIndex + 1
      : activity.position
    : activity.position;
  const totalSteps = currentModule?.activities.length;
  const currentStepLabel = totalSteps
    ? `${currentStep} of ${totalSteps}`
    : `Step ${currentStep}`;
  const moduleLabel = currentModule
    ? `Module ${currentModule.position}`
    : "Current activity";
  const moduleTitle = currentModule?.title ?? "Learning loop";
  const moduleHref =
    visibleLearning && currentModule
      ? ROUTES.module(visibleLearning.program_slug, currentModule.id)
      : ROUTES.myLearning;
  const kindLabel = activityKindLabel(activity.kind);
  const isReflection = activity.kind.toLowerCase() === "reflection";
  const saveLabel = isReflection ? "Save reflection" : "Save draft";
  const activityBoundary = isReflection
    ? "Reflection only — not an evaluation."
    : "Learner evidence — not an autonomous evaluation.";

  async function copyActivityRecovery() {
    if (recoveryResponse === null) return;
    try {
      await navigator.clipboard.writeText(
        activityRecoveryText(recoveryResponse),
      );
      setRecoveryMessage("Recovery copy copied to the clipboard.");
    } catch {
      setRecoveryMessage(
        "Clipboard access was blocked. Download the recovery file instead.",
      );
    }
  }

  function exportActivityRecovery() {
    if (recoveryResponse === null) return;
    const href = URL.createObjectURL(
      new Blob([activityRecoveryText(recoveryResponse)], {
        type: "text/plain;charset=utf-8",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "authority-closers-activity-recovery.txt";
    anchor.click();
    URL.revokeObjectURL(href);
    setRecoveryMessage("Recovery file downloaded on this device.");
  }
  return (
    <div
      className={`activity-workspace activity-workspace--${activity.kind.toLowerCase().replaceAll("_", "-")}`}
      aria-label="Connected learner activity"
    >
      <article className="activity-shell">
        <div className="activity-shell__breadcrumb">
          <Link href={moduleHref}>
            <ArrowLeft size={15} aria-hidden="true" />
            {currentModule ? moduleLabel : "My learning"}
          </Link>
          {visibleLearning ? (
            <span>{visibleLearning.program_title}</span>
          ) : learningPathStatus === "loading" ? (
            <span>Loading course path…</span>
          ) : null}
        </div>
        <div className="activity-shell__header">
          <div>
            <p className="activity-shell__type">
              <span className="activity-shell__type-icon" aria-hidden="true">
                {activityIcon(activity.kind)}
              </span>
              {kindLabel} · {currentStepLabel}
            </p>
            <h1>{activity.title}</h1>
          </div>
          <span className="status-pill">
            {activityStateLabel(activity.state)}
          </span>
        </div>
        {prompt ? (
          <section className="activity-prompt" aria-labelledby="prompt-title">
            <p className="kicker" id="prompt-title">
              Published prompt
            </p>
            <p>{prompt}</p>
            <p className="activity-prompt__help">
              Use the published prompt as the boundary. Saving keeps an editable
              draft; submission remains a separate action.
            </p>
          </section>
        ) : lockedReason ? (
          <div className="activity-access-boundary" role="status">
            <LockKeyhole size={20} aria-hidden="true" />
            <div>
              <strong>This activity is locked.</strong>
              <p>{lockedReason}</p>
            </div>
          </div>
        ) : (
          <div className="surface-state" role="status">
            <h3>No learner prompt is published for this activity.</h3>
            <p>Draft and evidence controls remain unavailable.</p>
          </div>
        )}
        <aside
          className="activity-stage-summary"
          aria-label="Current step"
          aria-live="polite"
        >
          <div>
            <span>Current · {kindLabel}</span>
            <strong>{currentStepLabel}</strong>
          </div>
          <p>{activityBoundary}</p>
          {learningPathStatus === "loading" ? (
            <p className="activity-stage-summary__path-state" role="status">
              Loading the server-authorized module path…
            </p>
          ) : learningPathStatus === "unavailable" ? (
            <p className="activity-stage-summary__path-state" role="status">
              The complete module path is temporarily unavailable.
            </p>
          ) : learningPathStatus === "forbidden" ? (
            <p className="activity-stage-summary__path-state" role="alert">
              This account cannot open the complete module path.
            </p>
          ) : learningPathStatus === "error" ? (
            <p className="activity-stage-summary__path-state" role="alert">
              {isSessionExpiredError(learningPathError)
                ? "Your session expired while refreshing the module path."
                : "The module path could not refresh."}
            </p>
          ) : null}
        </aside>
        <details className="activity-mobile-path">
          <summary>
            <span>View module path</span>
            <span className="activity-mobile-path__summary-meta">
              {currentStepLabel}
              <ChevronRight size={16} aria-hidden="true" />
            </span>
          </summary>
          <div>
            <p className="kicker">{moduleLabel}</p>
            <h2>{moduleTitle}</h2>
            <ActivityLoop
              activities={moduleActivities}
              currentActivityId={activity.id}
              label={`${moduleLabel} learning path`}
            />
            {learningPathStatus === "error" ||
            learningPathStatus === "forbidden" ? (
              <div className="activity-path-recovery" role="alert">
                <p>{errorText(learningPathError)}</p>
                {isSessionExpiredError(learningPathError) ? (
                  <Link href={ROUTES.sessionExpired}>Sign in again</Link>
                ) : isForbiddenError(learningPathError) ? (
                  <a href={LEARNER_SUPPORT_HREF}>Contact learner support</a>
                ) : onRetryLearningPath ? (
                  <button type="button" onClick={onRetryLearningPath}>
                    Retry module path
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </details>
        {staleLocalDraft ? (
          <section
            className="activity-mutation-message"
            aria-labelledby="activity-draft-conflict-title"
          >
            <div role="alert">
              <p className="kicker">Recovery decision required</p>
              <h2 id="activity-draft-conflict-title">
                A newer activity draft exists on the server.
              </h2>
              <p>
                This device recovery copy is based on draft revision{" "}
                {staleLocalDraft.baseRevision}; the server is now at revision{" "}
                {draftRevision}. Nothing has been placed into the editor.
              </p>
            </div>
            <details>
              <summary>Compare server and local responses</summary>
              <div>
                <h3>Server response</h3>
                <pre>{savedResponse || "No server response"}</pre>
                <h3>Local recovery response</h3>
                <pre>
                  {staleLocalDraft.draft.response || "No local response"}
                </pre>
              </div>
            </details>
            <div className="activity-response-form__actions">
              <button
                className="button button--outline"
                type="button"
                onClick={() => void keepServerActivityDraft()}
              >
                Keep server and discard local
              </button>
              <button
                className="button button--ink"
                type="button"
                onClick={mergeLocalActivityDraft}
              >
                Merge local copy into editor
              </button>
            </div>
            <div className="activity-response-form__actions">
              <button
                className="text-button"
                type="button"
                onClick={() => void copyActivityRecovery()}
              >
                Copy local recovery text
              </button>
              <button
                className="text-button"
                type="button"
                onClick={exportActivityRecovery}
              >
                Download local recovery file
              </button>
            </div>
          </section>
        ) : activity.kind.toLowerCase() === "video" ? (
          // VideoViewer owns the Approved lesson media is unavailable state.
          <VideoViewer
            key={activity.id}
            activity={activity}
            api={api}
            moduleHref={moduleHref}
            onPlaybackCommitted={() =>
              refreshCommittedMutationState("evidence")
            }
          />
        ) : (
          <form
            className="activity-response-form"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <div className="activity-response-form__heading">
              <label
                className="field-group activity-response-form__label"
                htmlFor="activity-response"
              >
                {responseLabel}
              </label>
              <span>Draft v{draftRevision}</span>
            </div>
            <textarea
              id="activity-response"
              rows={10}
              value={response}
              onChange={(event) => {
                activityRecoveryHydrationGuardRef.current.markLearnerEdit();
                setResponse(event.target.value);
                setMutation("idle");
                setMessage("");
                setFailureKind(null);
                setReauthRequired(false);
              }}
              disabled={!canEditResponse || mutation === "saving"}
              placeholder={
                canEditResponse
                  ? "Write only what the published prompt asks for."
                  : "Unavailable until the server authorizes a draft or evidence action."
              }
            />
            <div className="activity-response-form__meta" aria-live="polite">
              <span
                className={
                  mutation === "saved"
                    ? "activity-response-form__save-state is-saved"
                    : "activity-response-form__save-state"
                }
              >
                {mutation === "saved" ? (
                  <CheckCircle2 size={16} aria-hidden="true" />
                ) : null}
                {draftStatus}
              </span>
              <span className="activity-response-form__boundary">
                {activityBoundary}
              </span>
            </div>
            <details className="activity-draft-boundary">
              <summary>
                <ShieldCheck size={18} aria-hidden="true" />
                <strong>Versioned learner draft</strong>
              </summary>
              <p>
                Saving updates draft revision {draftRevision}. Submission is a
                separate server-authorized action.
              </p>
            </details>
            <div className="activity-response-form__actions activity-response-form__actions--primary">
              <Link className="activity-back-link" href={moduleHref}>
                <ArrowLeft size={16} aria-hidden="true" />
                Back to module
              </Link>
              <div>
                <button
                  className="button button--ink"
                  type="submit"
                  disabled={!canSaveDraft || mutation === "saving"}
                >
                  {mutation === "saving" ? "Saving…" : saveLabel}
                </button>
                <button
                  className="button button--outline"
                  type="button"
                  onClick={() => void submit()}
                  aria-describedby={
                    !canSubmitEvidence && prompt
                      ? "activity-submit-boundary"
                      : undefined
                  }
                  disabled={
                    !canSubmitEvidence || !evidenceType || mutation === "saving"
                  }
                >
                  Submit evidence
                </button>
              </div>
            </div>
            {!canSubmitEvidence && prompt ? (
              <p
                className="activity-submit-boundary"
                id="activity-submit-boundary"
                role="status"
              >
                Submission remains locked until the server authorizes this
                activity action.
              </p>
            ) : null}
          </form>
        )}
        {localCleanupPendingDraft || localCleanupPendingRaw ? (
          <section
            className="activity-mutation-message"
            aria-labelledby="activity-local-cleanup-title"
          >
            <div role="alert">
              <p className="kicker">
                {localCleanupPendingReason === "expired-record"
                  ? "Recovery cleanup pending"
                  : "Server save complete"}
              </p>
              <h2 id="activity-local-cleanup-title">
                {localCleanupPendingReason === "expired-record"
                  ? "Expired or invalid local recovery cleanup is pending."
                  : "Local recovery cleanup is still pending."}
              </h2>
              <p>
                {localCleanupPendingReason === "expired-record"
                  ? "The server activity remains authoritative. This device copy could not be verified or removed, so it remains until cleanup succeeds."
                  : "The server has the saved response. This device copy remains until cleanup succeeds, so it is not being hidden."}
              </p>
            </div>
            <div className="activity-response-form__actions">
              <button
                className="button button--outline"
                type="button"
                onClick={() => void retryLocalActivityCleanup()}
              >
                Retry local cleanup
              </button>
              {localCleanupPendingDraft ? (
                <>
                  <button
                    className="text-button"
                    type="button"
                    onClick={() => void copyActivityRecovery()}
                  >
                    Copy recovery text
                  </button>
                  <button
                    className="text-button"
                    type="button"
                    onClick={exportActivityRecovery}
                  >
                    Download recovery file
                  </button>
                </>
              ) : null}
            </div>
          </section>
        ) : null}
        {dirty && localPersistence === "failed" && !staleLocalDraft ? (
          <div className="activity-mutation-message" role="alert">
            <p>
              This browser could not save a recovery copy. Keep this page open
              or copy/download your response before leaving.
            </p>
            <button
              className="text-button"
              type="button"
              onClick={() => void copyActivityRecovery()}
            >
              Copy recovery text
            </button>
            <button
              className="text-button"
              type="button"
              onClick={exportActivityRecovery}
            >
              Download recovery file
            </button>
          </div>
        ) : null}
        {recoveryMessage ? <p role="status">{recoveryMessage}</p> : null}
        {message ? (
          <div
            className="activity-mutation-message"
            role={mutation === "error" ? "alert" : "status"}
          >
            <p>{message}</p>
            {failureKind === "conflict" ? (
              <button
                className="text-button"
                type="button"
                onClick={() => window.location.reload()}
              >
                Reload latest activity
              </button>
            ) : null}
            {(failureKind === "offline" || failureKind === "retry") &&
            lastOperation ? (
              <button
                className="text-button"
                type="button"
                onClick={() =>
                  void (lastOperation === "draft" ? save() : submit())
                }
              >
                Retry {lastOperation === "draft" ? "save" : "submission"}
              </button>
            ) : null}
            {dirty && localPersistence === "saved" ? (
              <div>
                <button
                  className="text-button"
                  type="button"
                  onClick={() => void copyActivityRecovery()}
                >
                  Copy recovery text
                </button>
                <button
                  className="text-button"
                  type="button"
                  onClick={exportActivityRecovery}
                >
                  Download recovery file
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
        {reauthRequired ? (
          <Link className="button button--ink" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        ) : null}
      </article>
      <aside className="activity-authority-panel">
        <section className="activity-module-panel">
          <p className="kicker">{moduleLabel}</p>
          <h2>{moduleTitle}</h2>
          <p className="activity-module-panel__progress">
            {currentStepLabel} · {activityStateLabel(activity.state)}
          </p>
          {learningPathStatus === "loading" && !currentModule ? (
            <p className="activity-module-panel__loading" role="status">
              Loading the server-authorized module path…
            </p>
          ) : null}
          {learningPathStatus === "unavailable" && !currentModule ? (
            <p className="activity-module-panel__loading" role="status">
              The full module path is temporarily unavailable. Only this
              server-authorized activity is shown.
            </p>
          ) : null}
          {learningPathStatus === "error" ||
          learningPathStatus === "forbidden" ? (
            <div className="activity-module-panel__loading" role="alert">
              <p>{errorText(learningPathError)}</p>
              {isSessionExpiredError(learningPathError) ? (
                <Link href={ROUTES.sessionExpired}>Sign in again</Link>
              ) : isForbiddenError(learningPathError) ? (
                <a href={LEARNER_SUPPORT_HREF}>Contact learner support</a>
              ) : onRetryLearningPath ? (
                <button type="button" onClick={onRetryLearningPath}>
                  Retry module path
                </button>
              ) : null}
            </div>
          ) : null}
          <ActivityLoop
            activities={moduleActivities}
            currentActivityId={activity.id}
            label={`${moduleLabel} learning path`}
          />
          <Link className="activity-module-panel__back" href={moduleHref}>
            Back to module <ArrowRight size={15} aria-hidden="true" />
          </Link>
          <details className="activity-authority-details">
            <summary>Activity details</summary>
            <dl>
              <div>
                <dt>Progress revision</dt>
                <dd>{activityRevision}</dd>
              </div>
              <div>
                <dt>Draft saving</dt>
                <dd>{canSaveDraft ? "Enabled" : "Not authorized"}</dd>
              </div>
              <div>
                <dt>Evidence submission</dt>
                <dd>{canSubmitEvidence ? "Enabled" : "Not authorized"}</dd>
              </div>
            </dl>
          </details>
        </section>
      </aside>
    </div>
  );
}

function CourseProgressSummary({ learning }: { learning: LearningResponse }) {
  const percentage = Math.round(
    Math.min(1, Math.max(0, learning.projection.percentage)) * 100,
  );
  return (
    <aside className="course-progress-card" aria-label="Course progress">
      <div className="course-progress-card__ring" aria-hidden="true">
        <strong>{percentage}%</strong>
        <span>complete</span>
      </div>
      <div>
        <p className="kicker">Your progress</p>
        <strong>
          {learning.projection.completed_count} of{" "}
          {learning.projection.denominator}
        </strong>
        <span>required activities complete</span>
      </div>
    </aside>
  );
}

function moduleStateLabel(module: LearningResponse["modules"][number]): string {
  if (module.activities.length === 0) return "Not published";
  if (
    module.activities.every(
      (activity) => activity.state.toLowerCase() === "completed",
    )
  )
    return "Complete";
  if (
    module.activities.every(
      (activity) => activity.state.toLowerCase() === "locked",
    )
  )
    return "Locked";
  return "Available";
}

function LearningModules({ learning }: { learning: LearningResponse }) {
  return (
    <section className="course-outline" aria-labelledby="course-outline-title">
      <div className="course-outline__heading">
        <div>
          <p className="kicker">Free Course path</p>
          <h2 id="course-outline-title">Course outline</h2>
        </div>
        <span>{learning.modules.length} modules</span>
      </div>
      <div className="course-path">
        {learning.modules.map((module) => {
          const completed = module.activities.filter(
            (activity) => activity.state.toLowerCase() === "completed",
          ).length;
          const moduleState = moduleStateLabel(module);
          const firstLocked = module.activities.find(
            (activity) => activity.state.toLowerCase() === "locked",
          );
          return (
            <article
              className={`module-card${moduleState === "Locked" ? " module-card--locked" : ""}`}
              key={module.id}
            >
              <div className="module-card__header">
                <div>
                  <p className="module-card__number">
                    Module {module.position}
                  </p>
                  <h3>{module.title}</h3>
                </div>
                <span className="module-card__count">
                  {module.activities.length > 0
                    ? `${completed}/${module.activities.length}`
                    : moduleState}
                </span>
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
                  No activities are published for this module yet.
                </p>
              )}
              {moduleState === "Locked" && firstLocked ? (
                <p className="module-card__lock-reason">
                  <LockKeyhole size={14} aria-hidden="true" />
                  {activityLockReason(firstLocked)}
                </p>
              ) : module.activities.length > 0 ? (
                <Link
                  className="module-card__footer-link"
                  href={ROUTES.module(learning.program_slug, module.id)}
                >
                  Open module <ArrowRight size={15} aria-hidden="true" />
                </Link>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function LiveLearningPath({
  slug,
  api = defaultApi,
}: {
  slug: string;
  api?: LearnerApi;
}) {
  const state = useLoad(
    (signal) => loadProgramLearningState(slug, api, signal),
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
    state.status === "ready" ? state.value.me.person_id : null,
  );
  if (state.status === "ready" && !membershipAvailable) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }
  const learning = state.status === "ready" ? state.value.learning : undefined;
  const offlineRead =
    state.status === "ready"
      ? getEarliestOfflineReadMetadata(
          state.value.program,
          state.value.me,
          state.value.learning,
        )
      : null;
  const nextActivity = learning ? firstActionableActivity(learning) : undefined;
  const firstModule = learning?.modules[0];
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Learner path"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" ? (
        <>
          {offlineRead ? (
            <div
              className="offline-read-notice"
              id="learning-path-offline-read"
              role="status"
            >
              {offlineReadNotice(offlineRead)}
            </div>
          ) : null}
          <section className="course-overview" aria-labelledby="learning-title">
            <div className="course-overview__main">
              <div
                className="breadcrumbs breadcrumbs--clarity"
                aria-label="Course location"
              >
                <Link href={ROUTES.learnerHome}>Home</Link>
                <span aria-hidden="true">/</span> My learning
              </div>
              <p className="eyebrow">Authority Closers · Free Course</p>
              <h1 id="learning-title">
                {learning?.program_title ?? state.value.program.title}
              </h1>
              <p>
                Work through the published Module 1 sequence. Access and
                progress below reflect your current learner enrollment.
              </p>
              {learning ? (
                <div className="course-overview__actions">
                  {offlineRead ? (
                    <span
                      className="button button--ink is-disabled"
                      aria-disabled="true"
                    >
                      Reconnect to continue
                    </span>
                  ) : (
                    <Link
                      className="button button--ink"
                      href={
                        nextActivity
                          ? ROUTES.activity(nextActivity.id)
                          : firstModule
                            ? ROUTES.module(
                                learning.program_slug,
                                firstModule.id,
                              )
                            : ROUTES.programLearning(learning.program_slug)
                      }
                    >
                      {nextActivity
                        ? "Continue learning"
                        : firstModule
                          ? "Open Module 1"
                          : "View course"}
                      <ArrowRight size={16} aria-hidden="true" />
                    </Link>
                  )}
                </div>
              ) : (
                <div className="enrollment-required" role="status">
                  <strong>
                    Start the Free Course before opening Module 1.
                  </strong>
                  <span>
                    Enrollment is controlled by the server and is not inferred
                    from this public course page.
                  </span>
                  <Link
                    className="button button--ink"
                    href={`${ROUTES.learnerHome}#continue-learning`}
                  >
                    Start from learner home
                  </Link>
                </div>
              )}
            </div>
            {learning ? <CourseProgressSummary learning={learning} /> : null}
          </section>
          {learning ? <LearningModules learning={learning} /> : null}
        </>
      ) : null}
    </>
  );
}

export function LiveModule({
  slug,
  moduleId,
  api = defaultApi,
}: {
  slug: string;
  moduleId: string;
  api?: LearnerApi;
}) {
  const state = useLoad(
    (signal) => loadProgramLearningState(slug, api, signal),
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
    state.status === "ready" ? state.value.me.person_id : null,
  );
  if (state.status !== "ready")
    return (
      <StateMessage
        state={state}
        pageTitle="Module"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
    );
  if (!membershipAvailable) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }
  if (!state.value.learning) {
    return (
      <div
        className="enrollment-required enrollment-required--page"
        role="status"
      >
        <strong>This course is not enrolled for the current learner.</strong>
        <span>
          Start the published Free Course from learner home. The interface will
          not manufacture module access.
        </span>
        <Link
          className="button button--ink"
          href={`${ROUTES.learnerHome}#continue-learning`}
        >
          Go to learner home
        </Link>
      </div>
    );
  }
  const courseModule = state.value.learning.modules.find(
    (item) =>
      item.id === moduleId ||
      `module-${String(item.position).padStart(2, "0")}` === moduleId,
  );
  if (!courseModule)
    return (
      <div className="surface-state" role="status">
        <h1>This module is not available.</h1>
        <p>
          Return to the enrolled course outline to choose a published module.
        </p>
        <Link
          className="button button--outline"
          href={ROUTES.programLearning(state.value.learning.program_slug)}
        >
          Back to course
        </Link>
      </div>
    );
  const completed = courseModule.activities.filter(
    (activity) => activity.state.toLowerCase() === "completed",
  ).length;
  return (
    <>
      <section className="module-overview" aria-labelledby="module-title">
        <div>
          <div
            className="breadcrumbs breadcrumbs--clarity"
            aria-label="Module location"
          >
            <Link
              href={ROUTES.programLearning(state.value.learning.program_slug)}
            >
              {state.value.learning.program_title}
            </Link>
            <span aria-hidden="true">/</span> Module {courseModule.position}
          </div>
          <p className="eyebrow">Module {courseModule.position}</p>
          <h1 id="module-title">{courseModule.title}</h1>
          <p>
            Open only the activities available to this enrollment. Locked rows
            explain what the server still requires.
          </p>
        </div>
        <aside className="module-progress-card">
          <span>{completed}</span>
          <p>of {courseModule.activities.length} activities complete</p>
        </aside>
      </section>
      <section className="module-activities" aria-labelledby="activities-title">
        <div className="course-outline__heading">
          <div>
            <p className="kicker">Ordered activities</p>
            <h2 id="activities-title">Module 1 learning loop</h2>
          </div>
          <span>{moduleStateLabel(courseModule)}</span>
        </div>
        {courseModule.activities.length > 0 ? (
          <ol className="activity-list activity-list--large">
            {courseModule.activities.map((activity) => (
              <LearningActivityNavigation
                activity={activity}
                key={activity.id}
              />
            ))}
          </ol>
        ) : (
          <div className="surface-state" role="status">
            <h3>No activities are published in this module yet.</h3>
            <p>Return to the course outline to continue with available work.</p>
          </div>
        )}
      </section>
    </>
  );
}

export async function loadActivityEntryState(
  activityId: string,
  api: LearnerApi,
  signal?: AbortSignal,
): Promise<{
  me: MeResponse;
  activity?: ActivityResponse;
}> {
  const [meResult, activityResult] = await Promise.allSettled([
    api.me({ signal }),
    api.activity(activityId, { signal }),
  ]);

  if (meResult.status === "rejected") throw meResult.reason;
  const me = meResult.value;
  if (!hasMembershipRole(me)) return { me };
  if (activityResult.status === "rejected") throw activityResult.reason;
  return { me, activity: activityResult.value };
}

export function learningPathMatchesActivity(
  learning: LearningResponse,
  activity: Pick<
    ActivityResponse,
    "program_id" | "program_version_id" | "enrollment_id"
  >,
): boolean {
  return (
    learning.program_id === activity.program_id &&
    learning.program_version_id === activity.program_version_id &&
    learning.enrollment_id === activity.enrollment_id
  );
}

export async function refreshActivityLearningSnapshots(
  activity: ActivityResponse,
  api: LearnerApi,
): Promise<{ activity: ActivityResponse; learning: LearningResponse }> {
  const [nextActivity, nextLearning] = await Promise.all([
    api.activity(activity.id),
    api.learning(activity.program_id, {
      enrollmentId: activity.enrollment_id,
      programVersionId: activity.program_version_id,
    }),
  ]);
  if (!learningPathMatchesActivity(nextLearning, nextActivity)) {
    throw new Error(
      "The refreshed activity and learning path did not describe the same server snapshot.",
    );
  }
  return { activity: nextActivity, learning: nextLearning };
}

function ActivityWorkspaceWithLearningPath({
  activity,
  tenantId,
  personId,
  api,
}: {
  activity: ActivityResponse;
  tenantId?: string;
  personId?: string;
  api: LearnerApi;
}) {
  const [activitySnapshot, setActivitySnapshot] = useState(activity);
  const [learning, setLearning] = useState<LearningResponse>();
  const [learningPathStatus, setLearningPathStatus] = useState<
    "loading" | "ready" | "unavailable" | "forbidden" | "error"
  >("loading");
  const [learningPathError, setLearningPathError] = useState<unknown>();
  const [learningPathAttempt, setLearningPathAttempt] = useState(0);
  const learningPathGeneration = useRef(0);
  const activityProgramId = activitySnapshot.program_id;
  const activityProgramVersionId = activitySnapshot.program_version_id;
  const activityEnrollmentId = activitySnapshot.enrollment_id;

  useEffect(() => {
    let active = true;
    const generation = ++learningPathGeneration.current;
    api
      .learning(activityProgramId, {
        enrollmentId: activityEnrollmentId,
        programVersionId: activityProgramVersionId,
      })
      .then((nextLearning) => {
        if (!active || generation !== learningPathGeneration.current) return;
        if (
          !learningPathMatchesActivity(nextLearning, {
            program_id: activityProgramId,
            program_version_id: activityProgramVersionId,
            enrollment_id: activityEnrollmentId,
          })
        ) {
          setLearning(undefined);
          setLearningPathStatus("error");
          setLearningPathError(
            new Error(
              "The learning path changed while this activity was loading. Retry to obtain one consistent server snapshot.",
            ),
          );
          return;
        }
        setLearning(nextLearning);
        setLearningPathStatus("ready");
      })
      .catch((error: unknown) => {
        if (!active || generation !== learningPathGeneration.current) return;
        setLearning(undefined);
        setLearningPathError(error);
        setLearningPathStatus(learningPathStatusForError(error));
      });
    return () => {
      active = false;
    };
  }, [
    activityEnrollmentId,
    activityProgramId,
    activityProgramVersionId,
    api,
    learningPathAttempt,
  ]);

  async function refreshAfterMutation(kind: "draft" | "evidence") {
    if (kind === "draft") return;
    const generation = ++learningPathGeneration.current;
    setLearning(undefined);
    setLearningPathError(undefined);
    setLearningPathStatus("loading");
    try {
      const refreshed = await refreshActivityLearningSnapshots(
        activitySnapshot,
        api,
      );
      if (generation !== learningPathGeneration.current) return;
      setActivitySnapshot(refreshed.activity);
      setLearning(refreshed.learning);
      setLearningPathError(undefined);
      setLearningPathStatus("ready");
    } catch (error) {
      if (generation !== learningPathGeneration.current) return;
      setLearning(undefined);
      setLearningPathError(error);
      setLearningPathStatus(learningPathStatusForError(error));
    }
  }

  return (
    <ConnectedActivityWorkspace
      activity={activitySnapshot}
      api={api}
      learning={learning}
      learningPathStatus={learningPathStatus}
      learningPathError={learningPathError}
      onMutationCommitted={refreshAfterMutation}
      onRetryLearningPath={() => {
        setLearning(undefined);
        setLearningPathStatus("loading");
        setLearningPathError(undefined);
        setLearningPathAttempt((attempt) => attempt + 1);
      }}
      tenantId={tenantId}
      personId={personId}
    />
  );
}

export function LiveActivity({
  activityId,
  api = defaultApi,
}: {
  activityId: string;
  api?: LearnerApi;
}) {
  const state = useLoad(
    (signal) => loadActivityEntryState(activityId, api, signal),
    () => false,
    activityId,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
    state.status === "ready" ? state.value.me.person_id : null,
  );
  if (state.status === "ready" && !membershipAvailable) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Activity"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" && state.value.activity ? (
        <ActivityWorkspaceWithLearningPath
          key={state.value.activity.id}
          activity={state.value.activity}
          api={api}
          tenantId={state.value.me.selected_tenant_id ?? undefined}
          personId={state.value.me.person_id}
        />
      ) : null}
    </>
  );
}

export function LiveCertificate({
  certificateId,
  api = defaultApi,
}: {
  certificateId: string;
  api?: LearnerApi;
}) {
  const state = useLoad(
    async (signal) => {
      const me = await api.me({ signal });
      return {
        me,
        certificate: hasMembershipRole(me)
          ? await api.certificate(certificateId, { signal })
          : undefined,
      };
    },
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
    state.status === "ready" ? state.value.me.person_id : null,
  );
  if (state.status === "ready" && !membershipAvailable) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Certificate"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" && state.value.certificate ? (
        <section
          className="certificate-hero"
          aria-labelledby="certificate-title"
        >
          <p className="eyebrow">
            <span aria-hidden="true" /> Server-issued certificate
          </p>
          <h1 id="certificate-title">{state.value.certificate.status}</h1>
          <p>
            Certificate {state.value.certificate.id} · issued{" "}
            {state.value.certificate.issued_at}
          </p>
          <p>
            {state.value.certificate.completion.completed_activity_count} of{" "}
            {state.value.certificate.completion.required_activity_count}{" "}
            required activities at capture.
          </p>
        </section>
      ) : null}
    </>
  );
}

export function LiveCompletionGate({
  slug,
  api = defaultApi,
}: {
  slug: string;
  api?: LearnerApi;
}) {
  const state = useLoad(
    (signal) => loadProgramLearningState(slug, api, signal),
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
    state.status === "ready" ? state.value.me.person_id : null,
  );
  if (state.status !== "ready") {
    return (
      <StateMessage
        state={state}
        pageTitle="Completion status"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
    );
  }
  if (!membershipAvailable) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }
  const projection = state.value.learning?.projection;
  const completed = projection?.completed_count;
  const required = projection?.denominator;
  const complete =
    typeof completed === "number" &&
    typeof required === "number" &&
    required > 0 &&
    completed === required;
  const offlineRead = getEarliestOfflineReadMetadata(
    state.value.program,
    state.value.me,
    state.value.learning,
  );
  return (
    <>
      {offlineRead ? (
        <div
          className="offline-read-notice"
          id="completion-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}
      <section className="completion-hero" aria-labelledby="completion-title">
        <p className="eyebrow">
          <span aria-hidden="true" /> Course completion
        </p>
        <h1 id="completion-title">Completion status.</h1>
        {state.value.learning ? (
          <>
            <p>
              {typeof completed === "number" && typeof required === "number"
                ? `${completed} of ${required} required activities complete.`
                : "Completion details are not available right now."}
            </p>
            <p role="status">
              {complete
                ? "All required activities are complete."
                : "Keep going to complete the remaining required activities."}
            </p>
          </>
        ) : (
          <p>Start the Free Course to begin tracking completion.</p>
        )}
      </section>
    </>
  );
}
