"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  ChevronRight,
  FileText,
  Flag,
  LockKeyhole,
  PenLine,
  Play,
  ShieldCheck,
  Trophy,
  Wrench,
} from "lucide-react";

import {
  ApiError,
  createLearnerApi,
  type ActivityResponse,
  type ContextResponse,
  type LearnerApi,
  type LearningActivityResponse,
  type LearningResponse,
  type MeResponse,
  type ProgramSummaryResponse,
} from "../lib/learner-api";
import {
  activityRecoveryText,
  activityServerFingerprint,
  clearAllLearnerLocalDrafts,
  clearActivityLocalDraft,
  localDraftMatchesServer,
  mutationFailureKind,
  readActivityLocalDraft,
  registerBeforeUnloadGuard,
  writeActivityLocalDraft,
  type ActivityDraftEnvelope,
  type ActivityDraftScope,
  type MutationFailureKind,
} from "../lib/local-drafts";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";
import { SignOutControl } from "./sign-out-control";

const defaultApi = createLearnerApi();
export const FREE_COURSE_SLUG = "authority-closers-free-course";

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
      <div className="surface-state" role="status">
        <Heading>{pageTitle}</Heading>
        <p>Loading your learning…</p>
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
  loader: () => Promise<T>,
  empty: (value: T) => boolean,
): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) setState({ status: "loading" });
    });
    loader()
      .then((value) => {
        if (!active) return;
        setState(
          empty(value) ? { status: "empty" } : { status: "ready", value },
        );
      })
      .catch((error: unknown) => {
        if (active) setState({ status: "error", error });
      });
    return () => {
      active = false;
    };
    // The loader is intentionally captured per caller; retry is the only trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);
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
    () => api.listPrograms(),
    (value) => value.items.length === 0,
  );
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
        {state.status === "ready" ? (
          <CatalogList items={state.value.items} />
        ) : null}
      </section>
    </>
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
    () => api.program(slug),
    () => false,
  );
  const [enrollment, setEnrollment] = useState<
    "idle" | "saving" | "done" | "error"
  >("idle");
  const [enrollmentMessage, setEnrollmentMessage] = useState("");
  const [enrollmentRecovery, setEnrollmentRecovery] = useState<ReturnType<
    typeof enrollmentFailureMessage
  > | null>(null);
  const program = state.status === "ready" ? state.value : null;
  const freeEnrollmentAvailable =
    program !== null && isFreeEnrollmentProgram(program);
  async function enroll() {
    if (!program || !freeEnrollmentAvailable) return;
    setEnrollment("saving");
    setEnrollmentMessage("");
    setEnrollmentRecovery(null);
    try {
      const result = await api.enrollFree(program.program_version_id);
      setEnrollment("done");
      setEnrollmentMessage(
        result.replayed
          ? "Enrollment already exists for this account."
          : "Enrollment created. Open the learner path to continue.",
      );
    } catch (error) {
      setEnrollment("error");
      const recovery = enrollmentFailureMessage(error);
      setEnrollmentRecovery(recovery);
      setEnrollmentMessage(recovery.message);
    }
  }
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Program details"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {program ? (
        <>
          <section className="program-hero" aria-labelledby="program-title">
            <div className="program-hero__main">
              <p className="eyebrow">
                <span aria-hidden="true" /> Published program · v
                {program.version_number}
              </p>
              <h1 id="program-title">{program.title}</h1>
              <p className="program-hero__description">
                This detail is supplied by the published catalog API. Learner
                guidance appears only when the API publishes it.
              </p>
              {freeEnrollmentAvailable ? (
                <div className="hero-actions">
                  <button
                    className="button button--ink"
                    type="button"
                    onClick={enroll}
                    disabled={enrollment === "saving"}
                  >
                    {enrollment === "saving"
                      ? "Enrolling…"
                      : enrollment === "done"
                        ? "Enrolled"
                        : "Enroll free"}
                  </button>
                  <Link
                    className="text-link"
                    href={ROUTES.programLearning(program.slug)}
                  >
                    Open learner path →
                  </Link>
                </div>
              ) : (
                <p role="status">
                  Free enrollment is unavailable for this program.
                </p>
              )}
              {enrollmentMessage ? (
                <p role={enrollment === "error" ? "alert" : "status"}>
                  {enrollmentMessage}
                </p>
              ) : null}
              {enrollmentRecovery?.recoveryHref ? (
                <Link
                  className="text-link"
                  href={enrollmentRecovery.recoveryHref}
                >
                  {enrollmentRecovery.recoveryLabel} →
                </Link>
              ) : null}
            </div>
            <aside className="program-hero__aside">
              <p>Published modules and activities</p>
              <strong>{program.modules.length}</strong>
            </aside>
          </section>
          <section
            className="detail-section"
            aria-labelledby="module-list-title"
          >
            <div className="section-heading">
              <p className="kicker">Published structure</p>
              <h2 id="module-list-title">Modules.</h2>
            </div>
            <div className="course-path">
              {program.modules.map((module) => (
                <article className="module-card" key={module.id}>
                  <p className="module-card__number">
                    Module {module.position}
                  </p>
                  <h3>{module.title}</h3>
                  <p>{module.activities.length} published activities</p>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </>
  );
}

export async function identityState(
  api: LearnerApi,
  programId?: string,
): Promise<{
  me: MeResponse;
  context: ContextResponse;
  programs: ProgramSummaryResponse[];
  learning?: LearningResponse;
}> {
  const [me, context, programs] = await Promise.all([
    api.me(),
    api.context(),
    programId
      ? Promise.resolve<ProgramSummaryResponse[]>([])
      : api.listPrograms().then((response) => response.items),
  ]);
  const selectedProgramId =
    programId ?? selectPublishedFreeCourse(programs)?.id;
  let learning: LearningResponse | undefined;

  if (hasMembershipRole(me) && selectedProgramId) {
    try {
      learning = await api.learning(selectedProgramId);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
    }
  }

  return { me, context, programs, learning };
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

function useInvalidateDraftsWithoutMembership(
  membershipKnown: boolean,
  membershipAvailable: boolean,
) {
  useEffect(() => {
    if (membershipKnown && !membershipAvailable) {
      clearAllLearnerLocalDrafts(window.localStorage);
    }
  }, [membershipAvailable, membershipKnown]);
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
    return {
      message:
        "Your account is signed in, but the enrollment service has not authorized Free Course access. Try again after learner eligibility is approved.",
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

export function LearnerHomeEnrollmentCard({
  learning,
  program,
  api = defaultApi,
}: {
  learning?: LearningResponse;
  program?: ProgramSummaryResponse;
  api?: LearnerApi;
}) {
  const [enrollment, setEnrollment] = useState<"idle" | "saving" | "error">(
    "idle",
  );
  const [failure, setFailure] = useState<ReturnType<
    typeof enrollmentFailureMessage
  > | null>(null);
  const nextActivity = learning ? firstActionableActivity(learning) : undefined;

  async function startFreeCourse() {
    if (!program || enrollment === "saving") return;
    setEnrollment("saving");
    setFailure(null);
    try {
      await api.enrollFree(program.program_version_id);
      window.location.assign(ROUTES.programLearning(program.slug));
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
        {learning ? (
          <div className="current-course-card__actions">
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
              disabled={enrollment === "saving"}
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

export function LearnerHomeRuntime({ api = defaultApi }: { api?: LearnerApi }) {
  const state = useLoad(
    async () => ({
      ...(await identityState(api)),
      onboarding: await api.onboarding(),
    }),
    () => false,
  );
  const onboardingReady =
    state.status === "ready" &&
    (state.value.onboarding.status === "completed" ||
      state.value.onboarding.status === "skipped");
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
  );
  useEffect(() => {
    if (state.status === "ready" && membershipAvailable && !onboardingReady) {
      window.location.replace(ROUTES.onboarding);
    }
  }, [membershipAvailable, onboardingReady, state.status]);
  const publishedProgram =
    state.status === "ready"
      ? selectPublishedFreeCourse(state.value.programs)
      : undefined;
  const nextActivity =
    state.status === "ready" && state.value.learning
      ? firstActionableActivity(state.value.learning)
      : undefined;
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Learner workspace"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" && !membershipAvailable ? (
        <MembershipUnavailable api={api} />
      ) : null}
      {state.status === "ready" && membershipAvailable && !onboardingReady ? (
        <div className="surface-state" role="status">
          <h1>Opening your learner profile…</h1>
        </div>
      ) : null}
      {state.status === "ready" && membershipAvailable && onboardingReady ? (
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
                Continue the Free Course or start Module 1 when access is ready.
              </p>
            </div>
            {state.value.context.tenant_id ? (
              <span className="dashboard-intro__tenant">Learner workspace</span>
            ) : null}
          </section>
          <div className="dashboard-grid dashboard-grid--clarity">
            <LearnerHomeEnrollmentCard
              learning={state.value.learning}
              program={publishedProgram}
              api={api}
            />
            <aside className="first-win-card learner-account-card">
              <p className="kicker">Account</p>
              <h2>{state.value.me.display_name || "Learner profile"}</h2>
              <p>{state.value.me.email}</p>
              <dl className="learner-account-card__facts">
                <div>
                  <dt>Access</dt>
                  <dd>{state.value.me.membership_role}</dd>
                </div>
                <div>
                  <dt>Email</dt>
                  <dd>Verified</dd>
                </div>
              </dl>
              <SignOutControl api={api} />
            </aside>
          </div>
          <section
            className="dashboard-lower dashboard-lower--clarity"
            aria-labelledby="my-learning-title"
            id="my-learning"
          >
            <div className="dashboard-lower__heading">
              <div>
                <p className="kicker">Your courses</p>
                <h2 id="my-learning-title">My learning</h2>
              </div>
              {state.value.learning ? (
                <span className="dashboard-lower__caption">
                  {projectionLabel(state.value.learning.projection)} complete
                </span>
              ) : null}
            </div>
            {state.value.learning ? (
              <Link
                className="learning-list-card"
                href={ROUTES.programLearning(state.value.learning.program_slug)}
              >
                <span className="learning-list-card__icon" aria-hidden="true">
                  <BookOpenCheck size={21} />
                </span>
                <span className="learning-list-card__copy">
                  <span className="kicker">Free course</span>
                  <strong>{state.value.learning.program_title}</strong>
                  <span>
                    {projectionStateLabel(state.value.learning.projection)}
                  </span>
                </span>
                <span className="learning-list-card__progress">
                  {Math.round(state.value.learning.projection.percentage * 100)}
                  %
                </span>
                <ChevronRight size={19} aria-hidden="true" />
              </Link>
            ) : publishedProgram ? (
              <div className="learning-list-card learning-list-card--published">
                <span className="learning-list-card__icon" aria-hidden="true">
                  <BookOpenCheck size={21} />
                </span>
                <span className="learning-list-card__copy">
                  <span className="kicker">Published free course</span>
                  <strong>{publishedProgram.title}</strong>
                  <span>Start the course above to add it to My learning.</span>
                </span>
                <Link
                  className="button button--outline button--small"
                  href="#continue-learning"
                >
                  Start above
                </Link>
              </div>
            ) : (
              <div className="workspace-card workspace-card--empty">
                <h3>No published Free Course is available.</h3>
                <p>Retry when your workspace has a published course.</p>
              </div>
            )}
          </section>
          <section
            className="practice-section"
            aria-labelledby="practice-title"
            id="practice"
          >
            <div className="dashboard-lower__heading">
              <div>
                <p className="kicker">Module 1</p>
                <h2 id="practice-title">Practice</h2>
              </div>
            </div>
            <div className="practice-card">
              <span className="practice-card__icon" aria-hidden="true">
                <BarChart3 size={22} />
              </span>
              <div>
                <h3>
                  {nextActivity
                    ? nextActivity.title
                    : state.value.learning
                      ? "Review your authorized course path"
                      : "Practice begins after enrollment"}
                </h3>
                <p>
                  {nextActivity
                    ? activityStateLabel(nextActivity.state)
                    : state.value.learning
                      ? "The server currently exposes no next available activity."
                      : "Start the Free Course to open the activities authorized for your learner account."}
                </p>
              </div>
              <Link
                className="button button--outline button--small"
                href={
                  nextActivity
                    ? ROUTES.activity(nextActivity.id)
                    : state.value.learning
                      ? ROUTES.programLearning(
                          state.value.learning.program_slug,
                        )
                      : "#continue-learning"
                }
              >
                {nextActivity
                  ? "Open practice"
                  : state.value.learning
                    ? "View course"
                    : "Start above"}
              </Link>
            </div>
          </section>
          <div id="progress" className="progress-anchor" aria-hidden="true" />
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
  if (missingActivities > 0) {
    return `Complete ${missingActivities} earlier required ${missingActivities === 1 ? "activity" : "activities"} to unlock.`;
  }
  if (missingModules > 0) {
    return `Complete ${missingModules} prerequisite ${missingModules === 1 ? "module" : "modules"} to unlock.`;
  }
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
}: {
  activity: LearningActivityResponse;
}) {
  const lockedReason = activityLockReason(activity);
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
        <span>{activityStateLabel(activity.state)}</span>
        {lockedReason ? (
          <LockKeyhole size={15} aria-hidden="true" />
        ) : (
          <ChevronRight size={16} aria-hidden="true" />
        )}
      </span>
    </>
  );
  if (activity.state.toLowerCase() === "locked") {
    return (
      <li className="activity-row activity-row--locked">
        <div aria-disabled="true">{content}</div>
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

function ActivityLoop({ currentKind }: { currentKind: string }) {
  return (
    <ol className="activity-loop" aria-label="Module 1 learning loop">
      {ACTIVITY_LOOP.map((step) => {
        const current = step.kind === currentKind.toUpperCase();
        return (
          <li
            className={`activity-loop__step${current ? " is-current" : ""}`}
            aria-current={current ? "step" : undefined}
            key={step.kind}
          >
            <span className="activity-loop__icon" aria-hidden="true">
              {activityIcon(step.kind)}
            </span>
            <span>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function ConnectedActivityWorkspace({
  activity,
  tenantId,
  personId,
  api = defaultApi,
}: {
  activity: ActivityResponse;
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
  const [localPersistence, setLocalPersistence] = useState<
    "idle" | "saved" | "failed"
  >("idle");
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
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
  const canCompleteVideo =
    writableState && allowedActions.has("complete_video");
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
    if (!localDraftScope) {
      queueMicrotask(() => {
        setLocalPersistence("failed");
        setLocalDraftChecked(true);
      });
      return;
    }
    const localDraft = readActivityLocalDraft(
      window.localStorage,
      localDraftScope,
    );
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      if (localDraft.status === "ready") {
        if (
          localDraftMatchesServer(
            localDraft.envelope,
            activity.draft_revision,
            activityServerFingerprint(initialResponse),
          )
        ) {
          if (localDraft.envelope.draft.response !== initialResponse) {
            setResponse(localDraft.envelope.draft.response);
            setLocalDraftRestored(true);
            setLocalPersistence("saved");
          }
        } else {
          setStaleLocalDraft(localDraft.envelope);
        }
      } else if (localDraft.status === "unavailable") {
        setLocalPersistence("failed");
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
      const result = writeActivityLocalDraft(window.localStorage, {
        scope: localDraftScope,
        response,
        baseRevision: draftRevision,
        serverFingerprint: activityServerFingerprint(savedResponse),
      });
      queueMicrotask(() => {
        if (active) setLocalPersistence(result.ok ? "saved" : "failed");
      });
    } else {
      clearActivityLocalDraft(window.localStorage, localDraftScope);
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
    response,
    savedResponse,
    staleLocalDraft,
  ]);

  useEffect(() => registerBeforeUnloadGuard(window, dirty), [dirty]);

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

  async function save() {
    if (!canSaveDraft) return;
    setLastOperation("draft");
    setMutation("saving");
    setMessage("");
    setReauthRequired(false);
    setFailureKind(null);
    const localResult = localDraftScope
      ? writeActivityLocalDraft(window.localStorage, {
          scope: localDraftScope,
          response,
          baseRevision: draftRevision,
          serverFingerprint: activityServerFingerprint(savedResponse),
        })
      : { ok: false as const, reason: "unavailable" as const };
    setLocalPersistence(localResult.ok ? "saved" : "failed");
    try {
      const saved = await api.saveDraft(
        activity.id,
        { response },
        draftRevision,
      );
      setDraftRevision(saved.revision);
      setActivityRevision(saved.activity_revision);
      setSavedResponse(response);
      setMutation("saved");
      setMessage("Draft saved by the server.");
      setLastOperation(null);
      setLocalDraftRestored(false);
      if (localDraftScope) {
        clearActivityLocalDraft(window.localStorage, localDraftScope);
      }
      setLocalPersistence("idle");
    } catch (error) {
      const kind = mutationFailureKind(error, online());
      setMutation("error");
      setFailureKind(kind);
      setMessage(mutationErrorMessage(error, kind, localResult.ok));
      setReauthRequired(isSessionExpiredError(error));
    }
  }
  async function submit() {
    if (!canSubmitEvidence || !evidenceType) return;
    setLastOperation("evidence");
    setMutation("saving");
    setMessage("");
    setReauthRequired(false);
    setFailureKind(null);
    const localResult = localDraftScope
      ? writeActivityLocalDraft(window.localStorage, {
          scope: localDraftScope,
          response,
          baseRevision: draftRevision,
          serverFingerprint: activityServerFingerprint(savedResponse),
        })
      : { ok: false as const, reason: "unavailable" as const };
    setLocalPersistence(localResult.ok ? "saved" : "failed");
    try {
      const submitted = await api.submitEvidence(
        activity.id,
        evidenceType,
        { response },
        activityRevision,
      );
      setActivityRevision(submitted.activity_revision);
      setSavedResponse(response);
      setMutation("submitted");
      setMessage(
        "Evidence submitted. The server will determine the next activity state.",
      );
      setLastOperation(null);
      setLocalDraftRestored(false);
      if (localDraftScope) {
        clearActivityLocalDraft(window.localStorage, localDraftScope);
      }
      setLocalPersistence("idle");
    } catch (error) {
      const kind = mutationFailureKind(error, online());
      setMutation("error");
      setFailureKind(kind);
      setMessage(mutationErrorMessage(error, kind, localResult.ok));
      setReauthRequired(isSessionExpiredError(error));
    }
  }

  function keepServerActivityDraft() {
    if (localDraftScope) {
      clearActivityLocalDraft(window.localStorage, localDraftScope);
    }
    setResponse(savedResponse);
    setStaleLocalDraft(null);
    setLocalDraftRestored(false);
    setLocalPersistence("idle");
    setRecoveryMessage("The local recovery copy was discarded.");
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
    staleLocalDraft?.draft.response ?? (dirty ? response : null);

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
          <Link href={ROUTES.myLearning}>My learning</Link>
          <span aria-hidden="true">/</span> Module 1 activity
        </div>
        <div className="activity-shell__header">
          <div>
            <p className="activity-shell__type">
              <span className="activity-shell__type-icon" aria-hidden="true">
                {activityIcon(activity.kind)}
              </span>
              {activity.kind.replaceAll("_", " ")}
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
                onClick={keepServerActivityDraft}
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
          <div className="activity-media-state" role="status">
            <div className="activity-media-state__icon" aria-hidden="true">
              <Play size={24} />
            </div>
            <div>
              <strong>No approved lesson media is connected yet.</strong>
              <p className="field-help">
                {canCompleteVideo
                  ? "Playback authorization exists, but this screen will not fabricate media or completion evidence."
                  : "Playback and completion remain unavailable for this activity."}
              </p>
            </div>
          </div>
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
              <span>{response.length.toLocaleString()} characters</span>
            </div>
            <aside className="activity-draft-boundary">
              <ShieldCheck size={20} aria-hidden="true" />
              <span>
                <strong>Versioned learner draft</strong>
                Saving updates draft revision {draftRevision}. Submission is a
                separate server-authorized action.
              </span>
            </aside>
            <div className="activity-response-form__actions">
              <button
                className="button button--outline"
                type="submit"
                disabled={!canSaveDraft || mutation === "saving"}
              >
                {mutation === "saving" ? "Saving…" : "Save draft"}
              </button>
              <button
                className="button button--ink"
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
        <section>
          <p className="kicker">This activity</p>
          <h2>Authorized state</h2>
          <dl>
            <div>
              <dt>Status</dt>
              <dd>{activityStateLabel(activity.state)}</dd>
            </div>
            <div>
              <dt>Activity version</dt>
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
        </section>
        <section>
          <p className="kicker">Module 1</p>
          <h2>Learning loop</h2>
          <ActivityLoop currentKind={activity.kind} />
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
    async () => {
      const program = await api.program(slug);
      const identity = await identityState(api, program.id);
      return { program, ...identity };
    },
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
  );
  if (state.status === "ready" && !membershipAvailable) {
    return <MembershipUnavailable api={api} />;
  }
  const learning = state.status === "ready" ? state.value.learning : undefined;
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
                  <Link
                    className="button button--ink"
                    href={
                      nextActivity
                        ? ROUTES.activity(nextActivity.id)
                        : firstModule
                          ? ROUTES.module(learning.program_slug, firstModule.id)
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
    async () => {
      const program = await api.program(slug);
      const identity = await identityState(api, program.id);
      return { program, ...identity };
    },
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
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
    return <MembershipUnavailable api={api} />;
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

export function LiveActivity({
  activityId,
  api = defaultApi,
}: {
  activityId: string;
  api?: LearnerApi;
}) {
  const state = useLoad(
    async () => {
      const me = await api.me();
      return {
        me,
        activity: hasMembershipRole(me)
          ? await api.activity(activityId)
          : undefined,
      };
    },
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
  );
  if (state.status === "ready" && !membershipAvailable) {
    return <MembershipUnavailable api={api} />;
  }
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Activity"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" && state.value.activity ? (
        <ConnectedActivityWorkspace
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
    async () => {
      const me = await api.me();
      return {
        me,
        certificate: hasMembershipRole(me)
          ? await api.certificate(certificateId)
          : undefined,
      };
    },
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
  );
  if (state.status === "ready" && !membershipAvailable) {
    return <MembershipUnavailable api={api} />;
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
    async () => {
      const program = await api.program(slug);
      const identity = await identityState(api, program.id);
      return { program, ...identity };
    },
    () => false,
  );
  const membershipAvailable =
    state.status === "ready" && hasMembershipRole(state.value.me);
  useInvalidateDraftsWithoutMembership(
    state.status === "ready",
    membershipAvailable,
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
    return <MembershipUnavailable api={api} />;
  }
  const projection = state.value.learning?.projection;
  const completed = projection?.completed_count;
  const required = projection?.denominator;
  const complete =
    typeof completed === "number" &&
    typeof required === "number" &&
    required > 0 &&
    completed === required;
  return (
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
  );
}
