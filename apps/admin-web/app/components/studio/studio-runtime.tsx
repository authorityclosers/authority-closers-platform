"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
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
  loadStudioProgram,
  loadStudioPrograms,
  loadStudioReadiness,
  newIdempotencyKey,
  publishProgramVersion,
  type StudioProgramDetail,
} from "../../lib/admin-api";
import {
  canUseAdminPermission,
  useAdminSession,
} from "../../lib/admin-session";

type LoadState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: string };

const loadingState = { status: "loading", data: null, error: null } as const;

function useStudioData<T>(loader: () => Promise<T>, dependency: string) {
  const session = useAdminSession();
  const canRead = canUseAdminPermission(session, "catalog_read");
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${dependency}:${attempt}`;
  const [result, setResult] = useState<{
    dependency: string;
    state: LoadState<T>;
  }>({ dependency: requestKey, state: loadingState });

  useEffect(() => {
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
  }, [canRead, loader, requestKey]);

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
              <span className="section-eyebrow">
                Selected tenant + published global library
              </span>
              <h2 id="program-list-title">Programs</h2>
              <p>
                Tenant working versions are editable by their authorized
                commands. Global published content is visible here as read-only
                reference content.
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
                <p>
                  No tenant program or immutable global version was returned.
                </p>
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

function PublishDraft({
  onPublished,
  programTitle,
  version,
}: {
  onPublished: () => void;
  programTitle: string;
  version: StudioProgramDetail["versions"][number];
}) {
  const session = useAdminSession();
  const canPublish = canUseAdminPermission(session, "catalog_publish");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [status, setStatus] = useState<
    "idle" | "submitting" | "success" | "error"
  >("idle");
  const [message, setMessage] = useState("");
  const commandKey = useRef<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !canPublish ||
      !version.etag ||
      version.readiness !== "ready" ||
      !confirmed ||
      !reason.trim()
    )
      return;
    setStatus("submitting");
    setMessage("");
    try {
      commandKey.current ??= newIdempotencyKey();
      const result = await publishProgramVersion({
        programVersionId: version.id,
        reason: reason.trim(),
        ifMatch: version.etag,
        idempotencyKey: commandKey.current,
      });
      setStatus("success");
      setMessage(
        result.replayed
          ? "Existing publication result recovered."
          : "Version published and audited.",
      );
      onPublished();
    } catch {
      setStatus("error");
      setMessage(
        "Publication was rejected. Refresh and review the current readiness state.",
      );
    }
  }

  return (
    <form className="studio-publish-form" onSubmit={submit}>
      <div>
        <span className="section-eyebrow">Authorized transition</span>
        <h4>Publish version {version.version_number}</h4>
        <p>
          This uses the reviewed ETag, a fresh replay key, the selected tenant,
          and an append-only audit event in one transaction.
        </p>
      </div>
      {!canPublish ? (
        <p className="studio-permission-note">
          catalog_publish is not granted to this session.
        </p>
      ) : null}
      <label className="field">
        <span>Publication reason</span>
        <textarea
          value={reason}
          maxLength={500}
          required
          disabled={!canPublish || status === "submitting"}
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
          disabled={!canPublish || status === "submitting"}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>
          I reviewed {programTitle} version {version.version_number} against
          digest <code>{version.content_digest ?? "unavailable"}</code> and its
          listed publication blockers.
        </span>
      </label>
      <button
        className="button button-primary"
        type="submit"
        disabled={
          !canPublish ||
          version.readiness !== "ready" ||
          !confirmed ||
          !reason.trim() ||
          status === "submitting"
        }
      >
        {status === "submitting"
          ? "Publishing…"
          : `Publish version ${version.version_number}`}
      </button>
      {message ? (
        <p className={`studio-command-result studio-command-${status}`}>
          {message}
        </p>
      ) : null}
    </form>
  );
}

export function StudioProgram({ programId }: { programId: string }) {
  const [revision, setRevision] = useState(0);
  const loader = useMemo(() => () => loadStudioProgram(programId), [programId]);
  const { canRead, retry, session, state } = useStudioData(
    loader,
    `${programId}:${revision}`,
  );

  return (
    <LoadBoundary
      canRead={canRead}
      onRetry={retry}
      sessionStatus={session.status}
      status={state.status}
      error={state.error}
    >
      {state.status === "ready" ? (
        <div className="studio-detail-stack">
          <section className="panel studio-program-hero">
            <div>
              <span className="studio-scope">{state.data.scope}</span>
              <h2>{state.data.title}</h2>
              <p>{state.data.slug}</p>
            </div>
            <span className="status-badge status-badge-muted">
              {state.data.access === "global_read_only"
                ? "Global read-only"
                : "Selected tenant"}
            </span>
          </section>
          {state.data.versions.length === 0 ? (
            <section className="panel studio-empty">
              <Database aria-hidden="true" />
              <div>
                <h3>No visible versions</h3>
                <p>
                  This program has no version visible to this Studio context.
                </p>
              </div>
            </section>
          ) : (
            state.data.versions.map((version) => (
              <section className="panel studio-version-card" key={version.id}>
                <header>
                  <div>
                    <span className="studio-version-label">
                      Version {version.version_number}
                    </span>
                    <h3>{version.status}</h3>
                  </div>
                  <span
                    className={
                      version.readiness === "ready"
                        ? "studio-ready"
                        : "studio-blocked"
                    }
                  >
                    {version.readiness.replaceAll("_", " ")}
                  </span>
                </header>
                <div className="studio-version-meta">
                  <dl>
                    <div>
                      <dt>Source</dt>
                      <dd>{version.content_source_ref ?? "Unavailable"}</dd>
                    </div>
                    <div>
                      <dt>Reviewed by</dt>
                      <dd>{version.content_reviewed_by ?? "Unavailable"}</dd>
                    </div>
                    <div>
                      <dt>Reviewed at</dt>
                      <dd>{formatTimestamp(version.content_reviewed_at)}</dd>
                    </div>
                    <div>
                      <dt>Release</dt>
                      <dd>{version.release_id ?? "Unavailable"}</dd>
                    </div>
                    <div>
                      <dt>Content digest</dt>
                      <dd>{version.content_digest ?? "Unavailable"}</dd>
                    </div>
                  </dl>
                  <div className="studio-readiness-detail">
                    <strong>Publication readiness</strong>
                    <Blockers blockers={version.blockers} />
                  </div>
                </div>
                <div className="studio-module-list">
                  {version.modules.length === 0 ? (
                    <p>No modules are present in this version.</p>
                  ) : (
                    version.modules.map((module) => (
                      <article key={module.id}>
                        <div>
                          <span>
                            {String(module.position).padStart(2, "0")}
                          </span>
                          <h4>{module.title}</h4>
                          <small>
                            {module.prerequisite_module_ids.length} prerequisite
                            {module.prerequisite_module_ids.length === 1
                              ? ""
                              : "s"}
                          </small>
                        </div>
                        <ol>
                          {module.activities.map((activity) => (
                            <li key={activity.id}>
                              <span>{activity.position}</span>
                              <div>
                                <strong>{activity.title}</strong>
                                <small>
                                  {activity.kind}
                                  {activity.is_required
                                    ? " · required"
                                    : " · optional"}
                                </small>
                                {activity.prompt ? (
                                  <p>{activity.prompt}</p>
                                ) : null}
                              </div>
                            </li>
                          ))}
                        </ol>
                      </article>
                    ))
                  )}
                </div>
                {state.data.access === "selected_tenant" &&
                version.status === "draft" ? (
                  <PublishDraft
                    programTitle={state.data.title}
                    version={version}
                    onPublished={() => setRevision((current) => current + 1)}
                  />
                ) : null}
              </section>
            ))
          )}
          {state.data.versions_truncated ? (
            <p className="studio-bounded-note">
              Older immutable history is truncated; every tenant draft remains
              included.
            </p>
          ) : null}
        </div>
      ) : null}
    </LoadBoundary>
  );
}
