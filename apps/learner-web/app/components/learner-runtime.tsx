"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
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
import { ROUTES } from "../lib/routes";

const defaultApi = createLearnerApi();

type LoadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "empty" }
  | { status: "error"; error: unknown };

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "Sign in is required for this learner surface.";
    if (error.status === 403)
      return "This learner resource is not available for the current account.";
    return error.title ?? error.message;
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
        <p>Loading server data…</p>
      </div>
    );
  }
  if (state.status === "empty") {
    return (
      <div className="surface-state" role="status">
        <Heading>Nothing is published here yet.</Heading>
        <p>
          The API returned no learner content. No local course data is
          substituted.
        </p>
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
  const program = state.status === "ready" ? state.value : null;
  async function enroll() {
    if (!program) return;
    setEnrollment("saving");
    setEnrollmentMessage("");
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
      setEnrollmentMessage(errorText(error));
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
              {enrollmentMessage ? (
                <p role={enrollment === "error" ? "alert" : "status"}>
                  {enrollmentMessage}
                </p>
              ) : null}
              {enrollment === "error" &&
              enrollmentMessage.includes("Sign in") ? (
                <Link className="text-link" href={ROUTES.login}>
                  Go to sign in →
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
  learning?: LearningResponse;
}> {
  const [me, context] = await Promise.all([api.me(), api.context()]);
  const candidateProgramIds = programId
    ? [programId]
    : (await api.listPrograms()).items.map((program) => program.id);
  let learning: LearningResponse | undefined;

  for (const candidateProgramId of candidateProgramIds) {
    try {
      learning = await api.learning(candidateProgramId);
      break;
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
    }
  }

  return { me, context, learning };
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

export function LearnerHomeEnrollmentCard({
  learning,
}: {
  learning?: LearningResponse;
}) {
  return (
    <section
      className="current-course-card"
      aria-labelledby="current-course-title"
    >
      <div className="current-course-card__topline">
        <p className="kicker">Continue learning</p>
        <span className="status-pill status-pill--neutral">
          {learning
            ? projectionStateLabel(learning.projection)
            : "Enrollment summary unavailable"}
        </span>
      </div>
      <div className="current-course-card__body">
        <h2 id="current-course-title">
          {learning?.program_title ?? "No current course selected."}
        </h2>
        <p className="current-course-card__description">
          {learning
            ? learning.projection.percentage >= 1
              ? "Review the completed, server-authorized course path."
              : "Pick up the next server-authorized activity from your course path."
            : "This v0.1 home route does not yet expose a complete enrollment collection."}
        </p>
        {learning ? (
          <p role="status">
            Authoritative projection: {projectionLabel(learning.projection)}
          </p>
        ) : (
          <p role="status">
            No catalog item is substituted as a current course, and absence of a
            projection is not treated as proof that no enrollment exists.
          </p>
        )}
        {learning ? (
          <Link
            className="button button--ink"
            href={ROUTES.programLearning(learning.program_slug)}
          >
            {learning.projection.percentage >= 1
              ? "Review course"
              : "Continue course"}
          </Link>
        ) : (
          <Link className="button button--outline" href={ROUTES.home}>
            View published programs
          </Link>
        )}
      </div>
    </section>
  );
}

export function LearnerHomeRuntime({ api = defaultApi }: { api?: LearnerApi }) {
  const state = useLoad(
    () => identityState(api),
    () => false,
  );
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Learner workspace"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" ? (
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
                Welcome back,{" "}
                {state.value.me.display_name || state.value.me.email}
              </h1>
              <p className="dashboard-intro__subhead">
                Here&apos;s what&apos;s happening in your learning journey.
              </p>
            </div>
            <span className="dashboard-intro__tenant">
              {state.value.context.tenant_id
                ? "Workspace selected"
                : "Workspace not selected"}
            </span>
          </section>
          <div className="dashboard-grid dashboard-grid--clarity">
            <LearnerHomeEnrollmentCard learning={state.value.learning} />
            <aside className="first-win-card learner-account-card">
              <p className="kicker">Account</p>
              <h2>{state.value.me.display_name || "Learner profile"}</h2>
              <p>{state.value.me.email}</p>
              <dl className="learner-account-card__facts">
                <div>
                  <dt>Access</dt>
                  <dd>{state.value.me.membership_role ?? "Learner"}</dd>
                </div>
                <div>
                  <dt>Progress source</dt>
                  <dd>Server projection</dd>
                </div>
              </dl>
              <button
                className="button button--outline"
                type="button"
                onClick={() =>
                  api.logout().then(() => window.location.assign(ROUTES.login))
                }
              >
                Sign out
              </button>
            </aside>
          </div>
          <section
            className="dashboard-lower dashboard-lower--clarity"
            aria-labelledby="my-learning-title"
          >
            <div className="dashboard-lower__heading">
              <div>
                <p className="kicker">Your courses</p>
                <h2 id="my-learning-title">My learning</h2>
              </div>
              <span className="dashboard-lower__caption">
                A complete assignment collection is not available in v0.1.
              </span>
            </div>
            <div className="workspace-card workspace-card--empty">
              <p className="kicker">Assignment boundary</p>
              <h3>Additional assignments are not listed in this alpha.</h3>
              <p>
                The current API contract exposes a selected program projection,
                not a complete assignment collection.
              </p>
            </div>
          </section>
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
      </span>
      <span className="activity-row__status">
        {activityStateLabel(activity.state)}
      </span>
    </>
  );
  if (activity.state.toLowerCase() === "locked") {
    return (
      <div className="activity-row activity-row--locked" aria-disabled="true">
        {content}
      </div>
    );
  }
  return (
    <Link className="activity-row" href={ROUTES.activity(activity.id)}>
      {content}
    </Link>
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
  api = defaultApi,
}: {
  activity: ActivityResponse;
  api?: LearnerApi;
}) {
  const initialResponse =
    typeof activity.draft_payload?.response === "string"
      ? activity.draft_payload.response
      : "";
  const [response, setResponse] = useState(initialResponse);
  const [draftRevision, setDraftRevision] = useState(activity.draft_revision);
  const [activityRevision, setActivityRevision] = useState(activity.revision);
  const [mutation, setMutation] = useState<
    "idle" | "saving" | "saved" | "submitted" | "error"
  >("idle");
  const [message, setMessage] = useState("");
  const [reauthRequired, setReauthRequired] = useState(false);
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
  const draftStatus =
    mutation === "saving"
      ? "Saving to the server…"
      : mutation === "saved"
        ? "Saved to the server"
        : mutation === "error"
          ? "Save needs attention"
          : initialResponse
            ? "Server draft restored"
            : "Draft is not submitted";
  async function save() {
    if (!canSaveDraft) return;
    setMutation("saving");
    setMessage("");
    setReauthRequired(false);
    try {
      const saved = await api.saveDraft(
        activity.id,
        { response },
        draftRevision,
      );
      setDraftRevision(saved.revision);
      setActivityRevision(saved.activity_revision);
      setMutation("saved");
      setMessage("Draft saved by the server.");
    } catch (error) {
      setMutation("error");
      setMessage(errorText(error));
      setReauthRequired(isSessionExpiredError(error));
    }
  }
  async function submit() {
    if (!canSubmitEvidence || !evidenceType) return;
    setMutation("saving");
    setMessage("");
    setReauthRequired(false);
    try {
      const submitted = await api.submitEvidence(
        activity.id,
        evidenceType,
        { response },
        activityRevision,
      );
      setActivityRevision(submitted.activity_revision);
      setMutation("submitted");
      setMessage("Evidence submitted for server-side processing.");
    } catch (error) {
      setMutation("error");
      setMessage(errorText(error));
      setReauthRequired(isSessionExpiredError(error));
    }
  }
  return (
    <div
      className={`activity-shell activity-shell--${activity.kind.toLowerCase().replaceAll("_", "-")}`}
      aria-label="Connected learner activity"
    >
      <div className="activity-shell__breadcrumb">
        <Link href={ROUTES.learnerHome}>Course path</Link>
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
        <p className="prompt-card">{prompt}</p>
      ) : (
        <div className="surface-state" role="status">
          <h3>No learner-facing prompt is published.</h3>
          <p>
            Writing and evidence submission stay unavailable until the API
            supplies activity guidance.
          </p>
        </div>
      )}
      {activity.kind.toLowerCase() === "video" ? (
        <div className="activity-media-state" role="status">
          <div className="activity-media-state__icon" aria-hidden="true">
            <Play size={24} />
          </div>
          <div>
            <strong>Lesson media is pending approval.</strong>
            <p className="field-help">
              {canCompleteVideo
                ? "The server has enabled its versioned playback workflow."
                : "Playback completion is unavailable because the server has not exposed that action."}
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
          <label
            className="field-group activity-response-form__label"
            htmlFor="activity-response"
          >
            Your response
          </label>
          <textarea
            id="activity-response"
            rows={8}
            value={response}
            onChange={(event) => setResponse(event.target.value)}
            disabled={!canEditResponse || mutation === "saving"}
            placeholder={
              canEditResponse
                ? "Write only what the published prompt asks for."
                : "Unavailable until the server enables an activity action."
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
              <strong>Controlled learner draft</strong>
              Your response stays unsubmitted until the server authorizes the
              next workflow action.
            </span>
          </aside>
          <ActivityLoop currentKind={activity.kind} />
          <div className="hero-actions activity-response-form__actions">
            <button
              className="button button--outline"
              type="submit"
              disabled={!canSaveDraft || mutation === "saving"}
            >
              Save draft
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
              Submission is locked until the server authorizes this step.
            </p>
          ) : null}
        </form>
      )}
      {message ? (
        <p role={mutation === "error" ? "alert" : "status"}>{message}</p>
      ) : null}
      {reauthRequired ? (
        <Link className="button button--ink" href={ROUTES.sessionExpired}>
          Sign in again
        </Link>
      ) : null}
    </div>
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
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Learner path"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" ? (
        <section className="learning-hero" aria-labelledby="learning-title">
          <div className="learning-hero__copy">
            <div
              className="breadcrumbs breadcrumbs--clarity"
              aria-label="Course location"
            >
              Home <span aria-hidden="true">/</span> My learning
            </div>
            <p className="eyebrow">Published course</p>
            <h1 id="learning-title">
              {state.value.learning?.program_title ?? state.value.program.title}
            </h1>
            <p>
              Your course outline and activity access are read from the
              server-authoritative learning response.
            </p>
            {state.value.learning ? (
              <LearningModules learning={state.value.learning} />
            ) : (
              <div className="enrollment-required" role="status">
                <strong>No active enrollment for this course.</strong>
                <span>
                  This account cannot open Module 1 until the server returns an
                  enrollment.
                </span>
              </div>
            )}
          </div>
        </section>
      ) : null}
    </>
  );
}

function LearningModules({ learning }: { learning: LearningResponse }) {
  return (
    <div className="course-path">
      {learning.modules.map((module) => (
        <article className="module-card" key={module.id}>
          <div className="module-card__header">
            <div>
              <p className="module-card__number">Module {module.position}</p>
              <h2>{module.title}</h2>
            </div>
            <span className="module-card__count">
              {
                module.activities.filter(
                  (activity) => activity.state.toLowerCase() === "completed",
                ).length
              }
              /{module.activities.length}
            </span>
          </div>
          {module.activities.map((activity) => (
            <LearningActivityNavigation activity={activity} key={activity.id} />
          ))}
        </article>
      ))}
    </div>
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
      return identity;
    },
    () => false,
  );
  if (state.status !== "ready")
    return (
      <StateMessage
        state={state}
        pageTitle="Module"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
    );
  // The slug-shaped module URL is navigation only. The authenticated learning
  // response below remains the authority for activity access and state.
  const courseModule = state.value.learning?.modules.find(
    (item) =>
      item.id === moduleId ||
      `module-${String(item.position).padStart(2, "0")}` === moduleId,
  );
  if (!courseModule)
    return <StateMessage state={{ status: "empty" }} pageTitle="Module" />;
  return (
    <>
      <section className="module-hero" aria-labelledby="module-title">
        <div>
          <div
            className="breadcrumbs breadcrumbs--clarity"
            aria-label="Module location"
          >
            Course <span aria-hidden="true">/</span> Module{" "}
            {courseModule.position}
          </div>
          <p className="eyebrow">Course module</p>
          <h1 id="module-title">{courseModule.title}</h1>
          <p>
            Complete each server-authorized activity in sequence. The status
            beside every item comes from the learning API.
          </p>
        </div>
      </section>
      <section className="module-activities">
        <ol className="activity-list activity-list--large">
          {courseModule.activities.map((activity) => (
            <li className="activity-row" key={activity.id}>
              <LearningActivityNavigation activity={activity} />
            </li>
          ))}
        </ol>
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
    () => api.activity(activityId),
    () => false,
  );
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Activity"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" ? (
        <ConnectedActivityWorkspace activity={state.value} api={api} />
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
    () => api.certificate(certificateId),
    () => false,
  );
  return (
    <>
      <StateMessage
        state={state}
        pageTitle="Certificate"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
      {state.status === "ready" ? (
        <section
          className="certificate-hero"
          aria-labelledby="certificate-title"
        >
          <p className="eyebrow">
            <span aria-hidden="true" /> Server-issued certificate
          </p>
          <h1 id="certificate-title">{state.value.status}</h1>
          <p>
            Certificate {state.value.id} · issued {state.value.issued_at}
          </p>
          <p>
            {state.value.completion.completed_activity_count} of{" "}
            {state.value.completion.required_activity_count} required activities
            at capture.
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
  if (state.status !== "ready") {
    return (
      <StateMessage
        state={state}
        pageTitle="Completion status"
        retry={(state as LoadState<unknown> & { retry?: () => void }).retry}
      />
    );
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
        <span aria-hidden="true" /> Server-authoritative completion
      </p>
      <h1 id="completion-title">Completion status.</h1>
      {state.value.learning ? (
        <>
          <p>
            {typeof completed === "number" && typeof required === "number"
              ? `${completed} of ${required} required activities complete.`
              : "The API returned learning data without a completion count."}
          </p>
          <p role="status">
            {complete
              ? "The server reports completion."
              : "The server does not report completion."}
          </p>
        </>
      ) : (
        <p>Enrollment or learning state is not available for this account.</p>
      )}
      <p className="field-help">
        This screen never issues a certificate and never promotes progress from
        the browser.
      </p>
    </section>
  );
}
