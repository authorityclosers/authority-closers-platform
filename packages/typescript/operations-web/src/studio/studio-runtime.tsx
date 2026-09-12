"use client";

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import { StudioCourseEditor } from "./studio-course-editor";
import {
  StudioCourseCreate,
  activateStudioCourseCreationScope,
} from "./studio-course-create";
import { activateStudioVideoRecoveryScope } from "./studio-video-panel";
import {
  activateStudioUploadScope,
  restrictStudioUploadScope,
} from "./studio-video-upload-session";
import {
  activateStudioRecoveryScope,
  clearStudioPublication,
  readStudioPublication,
  retainStudioPublication,
  type StudioPublicationCommand,
} from "./studio-draft-recovery";
import type { AdminSessionState } from "../admin-session";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Database,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";

import {
  AdminApiProblem,
  loadStudioProgram,
  loadStudioPrograms,
  loadStudioReadiness,
  newIdempotencyKey,
  publishProgramVersion,
  type StudioProgramDetail,
} from "../admin-api";
import {
  canBrowseStudio,
  canUseStudioPermission,
  useAdminSession,
} from "../admin-session";

type LoadState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: string };

const loadingState = { status: "loading", data: null, error: null } as const;

function studioContextKey(state: AdminSessionState): string {
  if (state.status !== "ready") return state.status;
  const session = state.session;
  return JSON.stringify([
    session.tenantId,
    session.personId,
    session.sessionId,
    [...session.permissions].sort(),
    session.studioCapabilities,
  ]);
}

function studioVideoContextKey(state: AdminSessionState): string {
  if (state.status !== "ready") return "";
  // Changing assignments must trigger fresh reads, not erase a command whose
  // commit is still unknown. Identity/session/tenant changes do clear it.
  const { tenantId, personId, sessionId } = state.session;
  return JSON.stringify([tenantId, personId, sessionId]);
}

export function useStudioData<T>(
  loader: () => Promise<T>,
  dependency: string,
  programId?: string,
) {
  const session = useAdminSession();
  const canRead = programId
    ? canUseStudioPermission(session, "catalog_read", programId)
    : canBrowseStudio(session);
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${studioContextKey(session)}:${dependency}:${attempt}`;
  const [result, setResult] = useState<{
    dependency: string;
    state: LoadState<T>;
  }>({ dependency: requestKey, state: loadingState });

  useEffect(() => {
    if (session.status === "ready") {
      activateStudioRecoveryScope(studioContextKey(session));
      activateStudioVideoRecoveryScope(studioVideoContextKey(session));
      activateStudioUploadScope(studioVideoContextKey(session));
      restrictStudioUploadScope(
        studioVideoContextKey(session),
        (id) =>
          canUseStudioPermission(session, "catalog_write", id) &&
          canUseStudioPermission(session, "catalog_read", id),
      );
      activateStudioCourseCreationScope(studioVideoContextKey(session));
    } else if (session.status === "denied") {
      activateStudioRecoveryScope("");
      // A failed session read is not proof of logout. Keep unresolved video
      // intent private until the same identity is verified again. A new verified
      // session/tenant clears it; normal sign-out performs a full navigation.
    }
    if (!canRead) return;
    let active = true;
    void Promise.resolve()
      .then(loader)
      .then((data) => {
        if (
          data &&
          typeof data === "object" &&
          "tenant_id" in data &&
          session.status === "ready" &&
          data.tenant_id !== session.session.tenantId
        ) {
          throw new Error("Studio response did not match the active academy");
        }
        if (active) {
          setResult({
            dependency: requestKey,
            state: { status: "ready", data, error: null },
          });
        }
      })
      .catch(() => {
        if (active) {
          setResult({
            dependency: requestKey,
            state: {
              status: "error",
              data: null,
              error: "We couldn’t load your courses. Please try again.",
            },
          });
        }
      });
    return () => {
      active = false;
    };
  }, [canRead, loader, requestKey, session]);

  const state = result.dependency === requestKey ? result.state : loadingState;
  return {
    canRead,
    retry: () => setAttempt((current) => current + 1),
    session,
    state,
  };
}

export function LoadBoundary({
  canRead,
  children,
  error,
  onRetry,
  sessionStatus,
  status,
}: {
  canRead: boolean;
  children: ReactNode;
  error: string | null;
  onRetry: () => void;
  sessionStatus: "loading" | "ready" | "denied" | "error";
  status: LoadState<unknown>["status"];
}) {
  if (sessionStatus === "loading") {
    return (
      <section className="studio-boundary panel" role="status">
        <LoaderCircle className="studio-spinner" aria-hidden="true" />
        <div>
          <h2>Opening your Studio</h2>
          <p>Checking your account…</p>
        </div>
      </section>
    );
  }
  if (sessionStatus === "error") {
    return (
      <section className="studio-boundary panel" role="alert">
        <AlertTriangle aria-hidden="true" />
        <div>
          <h2>We couldn’t check your account</h2>
          <p>
            Your work has not changed. Reload to reconnect to your workspace.
          </p>
          <button
            className="button button-secondary"
            onClick={() => window.location.reload()}
          >
            Reconnect
          </button>
        </div>
      </section>
    );
  }
  if (!canRead) {
    return (
      <section className="studio-boundary panel" role="status">
        <ShieldCheck aria-hidden="true" />
        <div>
          <h2>Studio access is unavailable</h2>
          <p>
            Sign in with the account assigned to your academy. If you’re already
            signed in, ask your administrator to check your Studio access.
          </p>
        </div>
      </section>
    );
  }
  if (status === "loading") {
    return (
      <section className="studio-boundary panel" role="status">
        <LoaderCircle className="studio-spinner" aria-hidden="true" />
        <div>
          <h2>Loading your courses</h2>
          <p>Getting your latest saved work.</p>
        </div>
      </section>
    );
  }
  if (status === "error") {
    return (
      <section
        className="studio-boundary studio-boundary-error panel"
        role="alert"
      >
        <AlertTriangle aria-hidden="true" />
        <div>
          <h2>Your courses couldn’t be loaded</h2>
          <p>{error}</p>
          <button
            className="button button-secondary"
            type="button"
            onClick={onRetry}
          >
            Try again
          </button>
        </div>
      </section>
    );
  }
  return children;
}

function formatTimestamp(value: string | null): string {
  if (value === null) return "None";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? "Unavailable"
    : new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }).format(parsed) + " UTC";
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "None";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  if (days > 0) return `${days}d ${hours}h`;
  const minutes = Math.floor((seconds % 3_600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

const blockerLabels: Record<string, string> = {
  version_not_draft: "Version is no longer a draft",
  structure_invalid: "Check the module order and required learning activities",
  provenance_incomplete:
    "The content source and review still need to be recorded",
  content_digest_mismatch: "The latest edits need a content review",
  supersession_required: "Choose which published version this draft replaces",
};

function Blockers({ blockers }: { blockers: readonly string[] }) {
  if (blockers.length === 0) return <span>Publication checks passed</span>;
  return (
    <ul className="studio-blockers">
      {blockers.map((blocker) => (
        <li key={blocker}>
          {blockerLabels[blocker] ??
            "An additional publication check is needed"}
        </li>
      ))}
    </ul>
  );
}

export function StudioToday() {
  const loader = useMemo(() => () => loadStudioReadiness(), []);
  const { canRead, retry, session, state } = useStudioData(loader, "readiness");

  return (
    <LoadBoundary
      canRead={canRead}
      onRetry={retry}
      sessionStatus={session.status}
      status={state.status}
      error={state.error}
    >
      {state.status === "ready" ? (
        <div className="studio-today-stack">
          <section
            className="studio-summary-grid"
            aria-label="Content readiness summary"
          >
            <article className="studio-summary-card studio-summary-primary">
              <span>Draft backlog</span>
              <strong>{state.data.draft_backlog_count}</strong>
              <small>
                {state.data.truncated
                  ? "The visible list is bounded to the oldest 100 drafts."
                  : "Selected-tenant drafts awaiting a publish decision."}
              </small>
            </article>
            <article className="studio-summary-card">
              <Clock3 aria-hidden="true" />
              <span>Oldest draft age</span>
              <strong>{formatAge(state.data.oldest_draft_age_seconds)}</strong>
              <small>
                Created {formatTimestamp(state.data.oldest_draft_created_at)};
                measured at {formatTimestamp(state.data.as_of)}.
              </small>
            </article>
            {[
              state.data.arrival_rate,
              state.data.service_rate,
              state.data.planned_capacity,
            ].map((metric, index) => (
              <article
                className="studio-summary-card studio-summary-unavailable"
                key={index}
              >
                <span>
                  {["Arrival rate", "Service rate", "Planned capacity"][index]}
                </span>
                <strong>Unavailable</strong>
                <small>{metric.reason}</small>
              </article>
            ))}
          </section>

          <section
            className="panel studio-draft-panel"
            aria-labelledby="studio-drafts-title"
          >
            <div className="section-heading">
              <div>
                <span className="section-eyebrow">
                  Today&apos;s work / oldest first
                </span>
                <h2 id="studio-drafts-title">Content readiness</h2>
                <p>
                  Review the actual draft backlog. Readiness reflects only the
                  catalog rules enforced by publication.
                </p>
              </div>
              <Link className="button button-secondary" href="/studio/programs">
                All programs <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </div>
            {state.data.drafts.length === 0 ? (
              <div className="studio-empty">
                <CheckCircle2 aria-hidden="true" />
                <div>
                  <h3>No tenant drafts in the backlog</h3>
                  <p>No draft work is asserted for the selected tenant.</p>
                </div>
              </div>
            ) : (
              <div className="studio-draft-list">
                {state.data.drafts.map((draft) => (
                  <article key={draft.program_version_id}>
                    <div>
                      <span className="studio-version-label">
                        Version {draft.version_number}
                      </span>
                      <h3>{draft.program_title}</h3>
                      <p>
                        Created {formatTimestamp(draft.created_at)} ·{" "}
                        {formatAge(draft.age_seconds)} old
                      </p>
                    </div>
                    <div
                      className={
                        draft.ready ? "studio-ready" : "studio-blocked"
                      }
                    >
                      <strong>
                        {draft.ready ? "Ready for review" : "Blocked"}
                      </strong>
                      <Blockers blockers={draft.blockers} />
                    </div>
                    <Link
                      className="inline-link"
                      href={`/studio/programs/${draft.program_id}`}
                    >
                      Inspect version{" "}
                      <ArrowRight size={15} aria-hidden="true" />
                    </Link>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </LoadBoundary>
  );
}

export function StudioProgramList() {
  const loader = useMemo(() => () => loadStudioPrograms(), []);
  const { canRead, retry, session, state } = useStudioData(loader, "programs");

  return (
    <LoadBoundary
      canRead={canRead}
      onRetry={retry}
      sessionStatus={session.status}
      status={state.status}
      error={state.error}
    >
      {state.status === "ready" ? (
        <section
          className="panel studio-program-panel"
          aria-labelledby="program-list-title"
        >
          <div className="section-heading">
            <div>
              <span className="section-eyebrow">Your academy</span>
              <h2 id="program-list-title">Your courses</h2>
              <p>
                Pick up where you left off. Open a course to shape its lessons,
                preview the content, or check what’s needed to publish.
              </p>
            </div>
            <StudioCourseCreate onRefresh={retry} />
          </div>
          {state.data.programs.length === 0 ? (
            <div className="studio-empty">
              <Database aria-hidden="true" />
              <div>
                <h3>
                  {canUseStudioPermission(session, "catalog_write")
                    ? "Your first course starts here"
                    : "No courses assigned yet"}
                </h3>
                <p>
                  {canUseStudioPermission(session, "catalog_write")
                    ? "Create a draft, then add your modules and lessons. Nothing is published until it’s ready."
                    : "Your courses will appear here once your administrator assigns them to you."}
                </p>
              </div>
            </div>
          ) : (
            <div className="studio-program-list">
              {state.data.programs.map((program) => (
                <article key={program.id}>
                  <div className="studio-program-title">
                    <span className="studio-scope">
                      {program.access === "global_read_only"
                        ? "Shared · read only"
                        : "Your academy"}
                    </span>
                    <h3>{program.title}</h3>
                  </div>
                  <dl>
                    <div>
                      <dt>Versions</dt>
                      <dd>{program.version_count}</dd>
                    </div>
                    <div>
                      <dt>Drafts</dt>
                      <dd>{program.draft_count}</dd>
                    </div>
                    <div>
                      <dt>Access</dt>
                      <dd>
                        {program.access === "global_read_only"
                          ? "Read only"
                          : "Academy course"}
                      </dd>
                    </div>
                    <div>
                      <dt>Latest</dt>
                      <dd>
                        {program.latest_version
                          ? `v${program.latest_version.version_number} · ${program.latest_version.status}`
                          : "No visible version"}
                      </dd>
                    </div>
                  </dl>
                  <Link
                    className="button button-secondary"
                    href={`/studio/programs/${program.id}`}
                  >
                    Open course <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                </article>
              ))}
            </div>
          )}
          {state.data.truncated ? (
            <p className="studio-bounded-note">
              Showing the first 100 courses available to your account.
            </p>
          ) : null}
        </section>
      ) : null}
    </LoadBoundary>
  );
}

export function PublishDraft({
  onPublished,
  onPendingChange,
  programId,
  programTitle,
  version,
  recoveryContext = "",
}: {
  onPublished: () => void;
  onPendingChange: (pending: boolean) => void;
  programId: string;
  programTitle: string;
  version: StudioProgramDetail["versions"][number] | undefined;
  recoveryContext?: string;
}) {
  const session = useAdminSession();
  const canPublish = canUseStudioPermission(
    session,
    "catalog_publish",
    programId,
  );
  const [recovered] = useState(() =>
    readStudioPublication(recoveryContext, programId),
  );
  const [reason, setReason] = useState(recovered?.reason ?? "");
  const [confirmed, setConfirmed] = useState(Boolean(recovered));
  const [status, setStatus] = useState<
    "idle" | "submitting" | "success" | "error" | "unknown"
  >(recovered ? "unknown" : "idle");
  const [message, setMessage] = useState(
    recovered
      ? "Your unconfirmed publication was recovered in this tab. Check the same publication to confirm its outcome."
      : "",
  );
  const commandKey = useRef<string | null>(recovered?.idempotencyKey ?? null);
  const command = useRef<StudioPublicationCommand | null>(recovered);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      inFlight.current ||
      !canPublish ||
      (!command.current &&
        (!version?.etag ||
          version.readiness !== "ready" ||
          !confirmed ||
          !reason.trim()))
    )
      return;
    setStatus("submitting");
    setMessage("");
    inFlight.current = true;
    onPendingChange(true);
    try {
      commandKey.current ??= newIdempotencyKey();
      command.current ??= {
        programVersionId: version!.id,
        reason: reason.trim(),
        ifMatch: version!.etag!,
        idempotencyKey: commandKey.current,
      };
      retainStudioPublication(recoveryContext, programId, command.current);
      const result = await publishProgramVersion(command.current);
      if (!mounted.current) return;
      if (
        result.id !== command.current.programVersionId ||
        result.program_id !== programId
      ) {
        throw new Error("Publication result did not match the saved command");
      }
      clearStudioPublication(recoveryContext, programId);
      command.current = null;
      onPendingChange(false);
      setStatus("success");
      setMessage(
        result.replayed
          ? "Existing publication result recovered."
          : "Version published and audited.",
      );
      onPublished();
    } catch (error) {
      if (!mounted.current) return;
      if (
        error instanceof AdminApiProblem &&
        error.status >= 400 &&
        error.status < 500
      ) {
        command.current = null;
        commandKey.current = null;
        clearStudioPublication(recoveryContext, programId);
        onPendingChange(false);
        setStatus("error");
        setMessage(
          "Publication was not accepted. Reopen the course to check its current content and your publishing access.",
        );
      } else {
        setStatus("unknown");
        setMessage(
          "Publication has not been confirmed. Check this same publication before leaving or editing content.",
        );
      }
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <form className="studio-publish-form" onSubmit={submit}>
      <div>
        <span className="section-eyebrow">Publication</span>
        <h4>
          {status === "unknown"
            ? "Recover publication"
            : `Publish version ${version?.version_number ?? "unavailable"}`}
        </h4>
        <p>
          Publish only after the content review is complete. This version
          becomes immutable; your publication is recorded in the audit history.
        </p>
      </div>
      {!canPublish ? (
        <p className="studio-permission-note">
          Publishing is not assigned for this program.
        </p>
      ) : null}
      <label className="field">
        <span>Publication reason</span>
        <textarea
          value={reason}
          maxLength={500}
          required
          disabled={
            !canPublish || status === "submitting" || status === "unknown"
          }
          onChange={(event) => {
            commandKey.current = null;
            setReason(event.target.value);
          }}
        />
      </label>
      <label className="studio-confirmation">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={
            !canPublish || status === "submitting" || status === "unknown"
          }
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>
          I reviewed {programTitle}, version{" "}
          {version?.version_number ?? "saved in this command"}, and confirm that
          this is the content I intend to publish.
        </span>
      </label>
      <button
        className="button button-primary"
        type="submit"
        disabled={
          !canPublish ||
          (status !== "unknown" &&
            (version?.readiness !== "ready" || !confirmed || !reason.trim())) ||
          status === "submitting"
        }
      >
        {status === "submitting"
          ? "Publishing…"
          : status === "unknown"
            ? "Check publication"
            : `Publish version ${version?.version_number ?? "unavailable"}`}
      </button>
      {message ? (
        <p
          role="status"
          className={`studio-command-result studio-command-${status}`}
        >
          {message}
        </p>
      ) : null}
    </form>
  );
}

export function StudioProgram({ programId }: { programId: string }) {
  const loader = useMemo(() => () => loadStudioProgram(programId), [programId]);
  const { canRead, retry, session, state } = useStudioData(
    loader,
    programId,
    programId,
  );
  const context = studioContextKey(session);
  const scoped =
    state.status === "ready" &&
    session.status === "ready" &&
    state.data.tenant_id === session.session.tenantId &&
    state.data.id === programId;
  return (
    <LoadBoundary
      canRead={canRead}
      onRetry={retry}
      sessionStatus={session.status}
      status={state.status}
      error={state.error}
    >
      {scoped && state.status === "ready" ? (
        <StudioCourseEditor
          key={context + ":" + programId}
          initialProgram={state.data}
          recoveryContext={context}
          videoRecoveryContext={studioVideoContextKey(session)}
          canWrite={canUseStudioPermission(session, "catalog_write", programId)}
          renderPublication={(version, refresh, setPending) =>
            version?.status === "draft" ||
            readStudioPublication(context, programId) ? (
              <PublishDraft
                key={version?.id ?? "publication-recovery"}
                programId={programId}
                programTitle={state.data.title}
                version={version}
                recoveryContext={context}
                onPublished={refresh}
                onPendingChange={setPending}
              />
            ) : (
              <p>
                This published version is read only. Its content remains
                preserved.
              </p>
            )
          }
        />
      ) : null}
    </LoadBoundary>
  );
}
