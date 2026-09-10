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

function useStudioData<T>(
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
    if (session.status === "ready")
      activateStudioRecoveryScope(studioContextKey(session));
    else if (session.status === "denied") activateStudioRecoveryScope("");
    if (!canRead) return;
    let active = true;
    void Promise.resolve()
      .then(loader)
      .then((data) => {
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
              error:
                "Studio data could not be loaded. No catalog state is being inferred.",
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

function LoadBoundary({
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
          <span className="section-eyebrow">Session boundary</span>
          <h2>Checking Academy Studio access</h2>
          <p>No catalog data is requested before tenant context is verified.</p>
        </div>
      </section>
    );
  }
  if (!canRead) {
    return (
      <section className="studio-boundary panel" role="status">
        <ShieldCheck aria-hidden="true" />
        <div>
          <span className="section-eyebrow">Authorization boundary</span>
          <h2>Academy Studio is unavailable</h2>
          <p>
            A verified selected-tenant session with the catalog_read permission
            is required. No program data was requested.
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
          <span className="section-eyebrow">Tenant-scoped read</span>
          <h2>Loading Academy Studio</h2>
          <p>Reading the authorized catalog without cached operational data.</p>
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
          <span className="section-eyebrow">Read failed closed</span>
          <h2>Studio data is unavailable</h2>
          <p>{error}</p>
          <button
            className="button button-secondary"
            type="button"
            onClick={onRetry}
          >
            Retry Studio read
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
  structure_invalid: "Catalog topology is invalid",
  provenance_incomplete: "Reviewed content provenance is incomplete",
  content_digest_mismatch: "Content changed after its recorded digest",
  supersession_required: "Published-version supersession is incomplete",
};

function Blockers({ blockers }: { blockers: readonly string[] }) {
  if (blockers.length === 0)
    return <span>Existing publication rules pass</span>;
  return (
    <ul className="studio-blockers">
      {blockers.map((blocker) => (
        <li key={blocker}>{blockerLabels[blocker] ?? blocker}</li>
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
              <span className="section-eyebrow">Your Studio scope</span>
              <h2 id="program-list-title">Programs</h2>
              <p>
                Open an available program to review its content and the actions
                assigned to you.
              </p>
            </div>
            <span className="status-badge status-badge-muted">
              {state.data.programs.length} visible
            </span>
          </div>
          {state.data.programs.length === 0 ? (
            <div className="studio-empty">
              <Database aria-hidden="true" />
              <div>
                <h3>No visible programs</h3>
                <p>No programs are currently available in your Studio scope.</p>
              </div>
            </div>
          ) : (
            <div className="studio-program-list">
              {state.data.programs.map((program) => (
                <article key={program.id}>
                  <div className="studio-program-title">
                    <span className="studio-scope">{program.scope}</span>
                    <h3>{program.title}</h3>
                    <code>{program.slug}</code>
                  </div>
                  <dl>
                    <div>
                      <dt>Visible versions</dt>
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
                          ? "Global read-only"
                          : "Selected tenant"}
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
                    Open program <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                </article>
              ))}
            </div>
          )}
          {state.data.truncated ? (
            <p className="studio-bounded-note">
              The program list is bounded to 100 records.
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
