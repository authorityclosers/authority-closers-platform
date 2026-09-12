"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AdminApiProblem,
  lookupAdminLearners,
  loadAdminLearnerDiagnosis,
  type AdminDiagnosisPurpose,
  type AdminLearnerCandidate,
  type AdminLearnerDiagnosis,
  type AdminLearnerLookup,
  type AdminSession,
} from "../lib/admin-api";
import { canUseAdminPermission, useAdminSession } from "../lib/admin-session";

export const PEOPLE_READ_TIMEOUT_MS = 15_000;
const defaultApi = {
  lookup: lookupAdminLearners,
  diagnose: loadAdminLearnerDiagnosis,
};
type PeopleApi = typeof defaultApi;

function label(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/^./, (first) => first.toUpperCase());
}

function ReadTime({ value }: { value: string }) {
  return <time dateTime={value}>{new Date(value).toLocaleString()}</time>;
}

export function PeopleRuntime({ api = defaultApi }: { api?: PeopleApi }) {
  const state = useAdminSession();
  if (state.status === "loading")
    return <p role="status">Checking workspace access…</p>;
  if (
    state.status !== "ready" ||
    !canUseAdminPermission(state, "learner_diagnose")
  ) {
    return (
      <section className="panel people-message">
        <h2>Learner records are unavailable</h2>
        <p>Your current workspace access does not include learner diagnosis.</p>
      </section>
    );
  }
  return (
    <PeopleWorkspace
      key={`${state.session.tenantId}:${state.session.personId}:${state.session.sessionId}`}
      session={state.session}
      api={api}
    />
  );
}

function PeopleWorkspace({
  session,
  api,
}: {
  session: AdminSession;
  api: PeopleApi;
}) {
  const [purpose, setPurpose] = useState<AdminDiagnosisPurpose | "">("");
  const [lookup, setLookup] = useState<AdminLearnerLookup | null>(null);
  const [selected, setSelected] = useState<AdminLearnerCandidate | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [diagnosis, setDiagnosis] = useState<AdminLearnerDiagnosis | null>(
    null,
  );
  const [busy, setBusy] = useState<"lookup" | "diagnosis" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accessLost, setAccessLost] = useState(false);
  const epoch = useRef(0);
  const active = useRef<AbortController | null>(null);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);

  useEffect(
    () => () => {
      ++epoch.current;
      active.current?.abort();
      if (timeout.current) clearTimeout(timeout.current);
    },
    [],
  );
  useEffect(() => {
    if (diagnosis) resultHeading.current?.focus();
  }, [diagnosis]);

  function clearResults() {
    ++epoch.current;
    active.current?.abort();
    active.current = null;
    if (timeout.current) clearTimeout(timeout.current);
    setBusy(null);
    setLookup(null);
    setSelected(null);
    setConfirmed(false);
    setDiagnosis(null);
    setError(null);
  }

  async function read<T>(
    kind: "lookup" | "diagnosis",
    request: (signal: AbortSignal) => Promise<T>,
    accept: (value: T) => void,
  ) {
    if (active.current || accessLost) return;
    const controller = new AbortController();
    active.current = controller;
    const current = ++epoch.current;
    setBusy(kind);
    setError(null);
    timeout.current = setTimeout(() => {
      if (epoch.current !== current) return;
      ++epoch.current;
      controller.abort();
      active.current = null;
      setBusy(null);
      setError("The request took too long. Please try again.");
    }, PEOPLE_READ_TIMEOUT_MS);
    try {
      const value = await request(controller.signal);
      if (current === epoch.current && !controller.signal.aborted)
        accept(value);
    } catch (problem) {
      if (current !== epoch.current) return;
      if (
        problem instanceof AdminApiProblem &&
        [401, 403].includes(problem.status)
      ) {
        setLookup(null);
        setSelected(null);
        setDiagnosis(null);
        setAccessLost(true);
      } else {
        setError(
          problem instanceof AdminApiProblem && problem.status === 404
            ? "This learner record is no longer available in this academy. Search again."
            : problem instanceof AdminApiProblem && problem.status === 422
              ? "Check the learner email or username and choose a review purpose."
              : "We couldn’t load the learner record. Please try again.",
        );
      }
    } finally {
      if (current === epoch.current) {
        if (timeout.current) clearTimeout(timeout.current);
        active.current = null;
        setBusy(null);
      }
    }
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!purpose || active.current || accessLost) return;
    const query = String(
      new FormData(event.currentTarget).get("query") ?? "",
    ).trim();
    if (
      query.length < 3 ||
      query.length > 320 ||
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(query)
    ) {
      setError("Enter the learner’s full email address or public username.");
      return;
    }
    setLookup(null);
    setSelected(null);
    setConfirmed(false);
    setDiagnosis(null);
    void read(
      "lookup",
      (signal) =>
        api.lookup({ query, purpose, tenantId: session.tenantId, signal }),
      setLookup,
    );
  }

  if (accessLost)
    return (
      <section className="panel people-message" role="alert">
        <h2>Workspace access needs to be checked</h2>
        <p>Your session or permission changed. Sign in again to continue.</p>
        <Link className="button" href="/login">
          Sign in again
        </Link>
      </section>
    );

  return (
    <div className="people-workspace">
      <section className="panel" aria-labelledby="people-search-title">
        <div className="people-intro">
          <span className="section-eyebrow">Learner support</span>
          <h2 id="people-search-title">Find a learner</h2>
          <p>
            Search by full email address or public username. Results include
            active learners in this academy.
          </p>
        </div>
        <form onSubmit={search} method="post">
          <fieldset className="people-search-fields" disabled={busy !== null}>
            <legend className="sr-only">Learner search</legend>
            <label className="field">
              <span>Email or username</span>
              <input
                name="query"
                type="search"
                required
                minLength={3}
                maxLength={320}
                autoComplete="off"
                onInput={clearResults}
                placeholder="Full email or public username"
              />
            </label>
            <label className="field">
              <span>Review purpose</span>
              <select
                required
                value={purpose}
                onChange={(event) => {
                  clearResults();
                  setPurpose(event.target.value as AdminDiagnosisPurpose | "");
                }}
              >
                <option value="">Choose a purpose</option>
                <option value="learner_support">Learner support</option>
                <option value="safeguarding_review">Safeguarding review</option>
                <option value="accessibility_review">
                  Accessibility review
                </option>
              </select>
            </label>
            <button className="button" type="submit" disabled={!purpose}>
              {busy === "lookup" ? "Searching…" : "Find learner"}
            </button>
          </fieldset>
        </form>
        <p className="surface-footnote">
          Searches and record views are recorded in the academy’s audit history.
        </p>
        {busy && (
          <p role="status">
            {busy === "lookup"
              ? "Searching learner records…"
              : "Loading learner diagnosis…"}
          </p>
        )}
        {error && (
          <p className="people-message" role="alert">
            {error}
          </p>
        )}
      </section>
      {lookup && (
        <section
          className="panel people-results"
          aria-labelledby="people-results-title"
        >
          <h2 id="people-results-title">Search results</h2>
          {lookup.candidates.length === 0 ? (
            <p role="status">
              No matching active learner was found in this academy. Check the
              full email address or public username.
            </p>
          ) : (
            lookup.candidates.map((candidate) => (
              <article className="people-candidate" key={candidate.person_id}>
                <div>
                  <h3>{candidate.display_name}</h3>
                  <p>
                    {candidate.username ? `@${candidate.username} · ` : ""}
                    {candidate.masked_email}
                  </p>
                  <span className="state-label">Active learner</span>
                </div>
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={busy !== null}
                  aria-pressed={selected?.person_id === candidate.person_id}
                  onClick={() => {
                    setSelected(candidate);
                    setConfirmed(false);
                    setDiagnosis(null);
                    setError(null);
                  }}
                >
                  {selected?.person_id === candidate.person_id
                    ? "Selected"
                    : "Select learner"}
                </button>
              </article>
            ))
          )}
          {lookup.truncated && (
            <p>
              Only part of the matching results is shown. Refine your search.
            </p>
          )}
          {selected && (
            <div className="people-review-confirm">
              <label>
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={busy !== null}
                  onChange={(event) => {
                    setConfirmed(event.target.checked);
                    setDiagnosis(null);
                  }}
                />
                <span>
                  I am viewing {selected.display_name}’s record for the selected
                  review purpose.
                </span>
              </label>
              <button
                className="button"
                type="button"
                disabled={!confirmed || !purpose || busy !== null}
                onClick={() => {
                  if (purpose && confirmed) {
                    setDiagnosis(null);
                    void read(
                      "diagnosis",
                      (signal) =>
                        api.diagnose({
                          personId: selected.person_id,
                          tenantId: session.tenantId,
                          purpose,
                          signal,
                        }),
                      setDiagnosis,
                    );
                  }
                }}
              >
                {busy === "diagnosis" ? "Opening…" : "Open learner diagnosis"}
              </button>
            </div>
          )}
        </section>
      )}
      {diagnosis && (
        <section
          className="panel people-diagnosis"
          aria-labelledby="people-diagnosis-title"
        >
          <div className="people-intro">
            <span className="section-eyebrow">Learner diagnosis</span>
            <h2 id="people-diagnosis-title" tabIndex={-1} ref={resultHeading}>
              {diagnosis.display_name}
            </h2>
            <p>
              {diagnosis.username ? `@${diagnosis.username} · ` : ""}
              {diagnosis.masked_email}
            </p>
            <p>
              Updated <ReadTime value={diagnosis.as_of} /> ·{" "}
              {label(diagnosis.purpose)}
            </p>
          </div>
          {diagnosis.enrollments.length === 0 && (
            <p>No course enrollments were returned for this learner.</p>
          )}
          {diagnosis.truncated && (
            <p role="status">
              This view contains a limited selection of enrollments. Other
              enrollments may be present.
            </p>
          )}
          {diagnosis.enrollments.map((enrollment) => (
            <article className="people-course" key={enrollment.enrollment_id}>
              <h3>{enrollment.program_title}</h3>
              <dl className="people-facts">
                <div>
                  <dt>Course version</dt>
                  <dd>{enrollment.version_number}</dd>
                </div>
                <div>
                  <dt>Enrollment</dt>
                  <dd>{label(enrollment.enrollment_status)}</dd>
                </div>
                <div>
                  <dt>Access</dt>
                  <dd>{label(enrollment.entitlement_status)}</dd>
                </div>
                <div>
                  <dt>Required activities complete</dt>
                  <dd>
                    {enrollment.progress
                      ? `${enrollment.progress.completed_count} of ${enrollment.progress.denominator}`
                      : "Unavailable"}
                  </dd>
                </div>
              </dl>
              {enrollment.truncated && (
                <p role="status">
                  Some activity, draft or evidence records are omitted from this
                  bounded view.
                </p>
              )}
              {enrollment.progress ? (
                <>
                  <p className="people-next">
                    <strong>Next activity: </strong>
                    {enrollment.progress.next_activity_id
                      ? (enrollment.progress.activity_states.find(
                          (activity) =>
                            activity.activity_id ===
                            enrollment.progress?.next_activity_id,
                        )?.title ?? "Not included in this view")
                      : "No next activity returned"}
                  </p>
                  <div className="people-activities">
                    {enrollment.progress.activity_states.map((activity) => {
                      const draft = enrollment.drafts.find(
                        (item) => item.activity_id === activity.activity_id,
                      );
                      const evidence = enrollment.evidence.filter(
                        (item) => item.activity_id === activity.activity_id,
                      );
                      return (
                        <details
                          className="people-activity"
                          key={activity.activity_id}
                        >
                          <summary>
                            <span>
                              <strong>{activity.title}</strong>
                              <small>
                                {label(activity.kind)} ·{" "}
                                {activity.required ? "Required" : "Optional"}
                              </small>
                            </span>
                            <span className="state-label">
                              {label(activity.state)}
                            </span>
                          </summary>
                          <div>
                            <p>{label(activity.reason)}</p>
                            <p>
                              {draft ? (
                                <>
                                  Saved draft · revision {draft.revision} ·{" "}
                                  <ReadTime value={draft.saved_at} />
                                </>
                              ) : enrollment.drafts_truncated ? (
                                "No saved draft included in this view."
                              ) : (
                                "No saved draft returned."
                              )}
                            </p>
                            {evidence.length ? (
                              <ul className="people-evidence">
                                {evidence.map((item, index) => (
                                  <li
                                    key={`${item.evidence_type}:${item.captured_at}:${index}`}
                                  >
                                    {label(item.evidence_type)}
                                    {item.submission_status
                                      ? ` · ${label(item.submission_status)}`
                                      : ""}{" "}
                                    ·{" "}
                                    <ReadTime
                                      value={
                                        item.submitted_at ?? item.captured_at
                                      }
                                    />
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p>
                                {enrollment.evidence_truncated
                                  ? "No evidence included in this view."
                                  : "No evidence returned."}
                              </p>
                            )}
                          </div>
                        </details>
                      );
                    })}
                  </div>
                </>
              ) : (
                <p>
                  Current progress is unavailable. Review the enrollment and
                  access status before continuing support.
                </p>
              )}
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
