"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { googleAuthStartUrl } from "../lib/auth-links";
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
        <a
          className="button button--small button--ink"
          href={googleAuthStartUrl("authenticate")}
        >
          Continue with Google
        </a>
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

function identityState(
  api: LearnerApi,
  programId?: string,
): Promise<{
  me: MeResponse;
  context: ContextResponse;
  learning?: LearningResponse;
}> {
  return Promise.all([api.me(), api.context()]).then(async ([me, context]) => {
    let learning: LearningResponse | undefined;
    if (programId) {
      try {
        learning = await api.learning(programId);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
      }
    }
    return { me, context, learning };
  });
}

function projectionLabel(projection: LearningResponse["projection"]): string {
  return `${Math.round(projection.percentage * 100)}% · ${projection.completed_count} / ${projection.denominator}`;
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
      <div className="current-course-card__body">
        <p className="kicker">Current enrollment</p>
        <h2 id="current-course-title">
          {learning?.program_title ?? "No current course selected."}
        </h2>
        <p>
          Learning state is read from the authenticated API and is never
          inferred in the browser.
        </p>
        {learning ? (
          <p role="status">
            Authoritative projection: {projectionLabel(learning.projection)}
          </p>
        ) : (
          <p role="status">
            This account has no server-selected enrollment yet. No catalog item
            is substituted as a current course.
          </p>
        )}
        {learning ? (
          <Link
            className="button button--ink"
            href={ROUTES.programLearning(learning.program_slug)}
          >
            Open learner path →
          </Link>
        ) : (
          <Link className="button button--outline" href={ROUTES.home}>
            Browse published programs →
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
              <p className="eyebrow">
                <span aria-hidden="true" /> Learner workspace
              </p>
              <h1 id="dashboard-title">
                Welcome back,
                <br />
                <em>{state.value.me.display_name || state.value.me.email}.</em>
              </h1>
            </div>
            <div className="dashboard-intro__note">
              Tenant context:{" "}
              {state.value.context.tenant_id ? "selected" : "not selected"}
            </div>
          </section>
          <div className="dashboard-grid">
            <LearnerHomeEnrollmentCard learning={state.value.learning} />
            <aside className="first-win-card">
              <p className="kicker">Identity</p>
              <h2>{state.value.me.email}</h2>
              <p>{state.value.me.membership_role ?? "Learner access"}</p>
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

export function LearningActivityNavigation({
  activity,
}: {
  activity: LearningActivityResponse;
}) {
  const content = (
    <>
      <span>{activity.title}</span>
      <span>{activityStateLabel(activity.state)}</span>
    </>
  );
  if (activity.state.toLowerCase() === "locked") {
    return (
      <div className="activity-row" aria-disabled="true">
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
  async function save() {
    if (!canSaveDraft) return;
    setMutation("saving");
    setMessage("");
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
    }
  }
  async function submit() {
    if (!canSubmitEvidence || !evidenceType) return;
    setMutation("saving");
    setMessage("");
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
    }
  }
  return (
    <div className="activity-shell" aria-label="Connected learner activity">
      <div className="activity-shell__header">
        <div>
          <p className="kicker">{activity.kind}</p>
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
        <p className="field-help">
          {canCompleteVideo
            ? "The server has enabled its versioned playback workflow."
            : "Playback completion is unavailable because the server has not exposed that action."}
        </p>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label className="field-group" htmlFor="activity-response">
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
          <div className="hero-actions">
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
              disabled={
                !canSubmitEvidence || !evidenceType || mutation === "saving"
              }
            >
              Submit evidence
            </button>
          </div>
        </form>
      )}
      {message ? (
        <p role={mutation === "error" ? "alert" : "status"}>{message}</p>
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
            <p className="eyebrow">
              <span aria-hidden="true" /> Authenticated learner path
            </p>
            <h1 id="learning-title">
              {state.value.learning?.program_title ?? state.value.program.title}
            </h1>
            <p>
              Enrollment and progression are read from the server-authoritative
              learning response.
            </p>
            {state.value.learning ? (
              <LearningModules learning={state.value.learning} />
            ) : (
              <p role="status">
                This account has no enrolled learning resource for this program.
              </p>
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
          <p className="module-card__number">Module {module.position}</p>
          <h2>{module.title}</h2>
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
          <p className="eyebrow">
            <span aria-hidden="true" /> Module {courseModule.position}
          </p>
          <h1 id="module-title">{courseModule.title}</h1>
          <p>
            Only activity state returned by the authenticated learning API is
            shown.
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
