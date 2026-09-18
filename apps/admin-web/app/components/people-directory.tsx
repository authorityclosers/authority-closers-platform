"use client";

import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  RefreshCw,
  Search,
  Users,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AdminApiProblem,
  loadMemberDirectory,
  loadAdminLearnerDiagnosis,
  type DirectoryFilters,
  type DirectoryMember,
  type MemberDirectory,
  type AdminLearnerDiagnosis,
  type AdminSession,
} from "../lib/admin-api";
import {
  canUseAdminPermission,
  useAdminSession,
  useInvalidateAdminSession,
} from "../lib/admin-session";
import { LearnerDiagnosisView } from "./people-runtime";
import styles from "./people-directory.module.css";

const api = {
  directory: loadMemberDirectory,
  diagnose: loadAdminLearnerDiagnosis,
};
type DirectoryApi = typeof api;
const initialFilters: DirectoryFilters = {
  query: "",
  role: "all",
  status: "all",
  page: 1,
  page_size: 25,
};
const titleCase = (text: string) => text[0].toUpperCase() + text.slice(1);
function memberStatus(member: DirectoryMember) {
  if (member.account_status === "suspended") return "Suspended";
  if (member.membership_status === "inactive") return "Inactive";
  return member.email_verified ? "Active" : "Email pending";
}
function initials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("");
}

export function PeopleDirectory({
  services = api,
}: {
  services?: DirectoryApi;
}) {
  const state = useAdminSession();
  if (
    !canUseAdminPermission(state, "learner_diagnose") ||
    state.status !== "ready"
  ) {
    return (
      <section className={styles.message} role="status">
        <h2>People workspace</h2>
        <p>
          {state.status === "loading"
            ? "Loading your workspace…"
            : "Sign in with academy support access to view people."}
        </p>
      </section>
    );
  }
  return (
    <DirectoryWorkspace
      key={`${state.session.tenantId}:${state.session.personId}:${state.session.sessionId}`}
      session={state.session}
      services={services}
    />
  );
}

function DirectoryWorkspace({
  session,
  services,
}: {
  session: AdminSession;
  services: DirectoryApi;
}) {
  const invalidate = useInvalidateAdminSession();
  const [filters, setFilters] = useState(initialFilters);
  const [query, setQuery] = useState("");
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<MemberDirectory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lost, setLost] = useState(false);
  const [selected, setSelected] = useState<DirectoryMember | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    const timeout = setTimeout(() => {
      if (!current) return;
      current = false;
      controller.abort();
      setLoading(false);
      setError("The directory is taking longer than expected. Try again.");
    }, 15000);
    void services
      .directory({
        tenantId: session.tenantId,
        filters,
        signal: controller.signal,
      })
      .then((result) => {
        if (current) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((problem: unknown) => {
        if (!current) return;
        setLoading(false);
        if (
          problem instanceof AdminApiProblem &&
          [401, 403].includes(problem.status)
        ) {
          setData(null);
          setSelected(null);
          setLost(true);
          invalidate(session);
        } else
          setError("We couldn’t load people. Your search is saved; try again.");
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      current = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [filters, retry, services, session, invalidate]);
  useEffect(() => {
    if (selected) heading.current?.focus();
  }, [selected]);
  function reload(next = filters) {
    setData(null);
    setSelected(null);
    setError(null);
    setLoading(true);
    if (next === filters) setRetry((value) => value + 1);
    else setFilters(next);
  }
  function search(event: FormEvent) {
    event.preventDefault();
    reload({ ...filters, query: query.trim(), page: 1 });
  }
  function close() {
    setSelected(null);
    opener.current?.focus();
  }
  if (lost)
    return (
      <section className={styles.message} role="alert">
        <h2>Sign in to continue</h2>
        <p>Your workspace access changed.</p>
        <Link href="/login" className="button">
          Sign in
        </Link>
      </section>
    );
  const summary = data?.summary;
  return (
    <div className={styles.workspace}>
      <dl className={styles.metrics} aria-label="Academy member summary">
        {(
          [
            ["People", summary?.total],
            ["Active learners", summary?.active_learners],
            ["Active team", summary?.team],
            ["Email pending", summary?.unverified],
          ] as const
        ).map(([label, count]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{count ?? "—"}</dd>
          </div>
        ))}
      </dl>
      <section className={styles.directory} aria-labelledby="directory-title">
        <div className={styles.header}>
          <div>
            <h2 id="directory-title">Your people</h2>
            <p>
              {data ? data.tenant_name : "Academy workspace"} · Members and
              their course activity
            </p>
          </div>
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Refresh people"
            onClick={() => reload()}
            disabled={loading}
          >
            <RefreshCw size={17} />
          </button>
        </div>
        <form className={styles.filters} onSubmit={search}>
          <label className={styles.search}>
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">Search people</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={320}
              placeholder="Search name, email or username"
            />
            <button type="submit">Search</button>
          </label>
          <label>
            <span className="sr-only">Role</span>
            <select
              value={filters.role}
              onChange={(event) =>
                reload({
                  ...filters,
                  role: event.target.value as DirectoryFilters["role"],
                  page: 1,
                })
              }
            >
              <option value="all">All roles</option>
              {["learner", "support", "admin", "owner"].map((role) => (
                <option key={role} value={role}>
                  {titleCase(role)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="sr-only">Status</span>
            <select
              value={filters.status}
              onChange={(event) =>
                reload({
                  ...filters,
                  status: event.target.value as DirectoryFilters["status"],
                  page: 1,
                })
              }
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="unverified">Email pending</option>
              <option value="inactive">Inactive</option>
              <option value="suspended">Suspended</option>
            </select>
          </label>
        </form>
        {error ? (
          <div className={styles.message} role="alert">
            <h3>People couldn’t be loaded</h3>
            <p>{error}</p>
            <button className="button" onClick={() => reload()}>
              Try again
            </button>
          </div>
        ) : loading ? (
          <div
            className={styles.skeleton}
            role="status"
            aria-label="Loading people"
          >
            {[0, 1, 2, 3].map((row) => (
              <span key={row} />
            ))}
          </div>
        ) : (
          data && (
            <>
              {data.members.length ? (
                <div
                  className={styles.tableWrap}
                  tabIndex={0}
                  role="region"
                  aria-label="Academy people"
                >
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Person</th>
                        <th>Role</th>
                        <th>Status</th>
                        <th>Courses</th>
                        <th>Joined</th>
                        <th>
                          <span className="sr-only">Open record</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.members.map((member) => (
                        <tr
                          key={member.person_id}
                          data-selected={
                            selected?.person_id === member.person_id
                          }
                        >
                          <td>
                            <div className={styles.identity}>
                              <span
                                className={styles.avatar}
                                aria-hidden="true"
                              >
                                {initials(member.display_name)}
                              </span>
                              <div>
                                <strong>{member.display_name}</strong>
                                <small>
                                  {member.username
                                    ? `@${member.username}`
                                    : member.masked_email}
                                </small>
                              </div>
                            </div>
                          </td>
                          <td>{titleCase(member.membership_role)}</td>
                          <td>
                            <span
                              className={styles.status}
                              data-status={memberStatus(member)}
                            >
                              {memberStatus(member) === "Active" && (
                                <Check size={12} aria-hidden="true" />
                              )}
                              {memberStatus(member)}
                            </span>
                          </td>
                          <td>{member.active_enrollments}</td>
                          <td>
                            <time dateTime={member.joined_at}>
                              {new Date(member.joined_at).toLocaleDateString(
                                "en-GB",
                                {
                                  day: "numeric",
                                  month: "short",
                                  year: "numeric",
                                },
                              )}
                            </time>
                          </td>
                          <td>
                            <button
                              className={styles.open}
                              aria-label={`View ${member.display_name}`}
                              aria-expanded={
                                selected?.person_id === member.person_id
                              }
                              onClick={(event) => {
                                opener.current = event.currentTarget;
                                setSelected(member);
                              }}
                            >
                              View <ArrowRight size={15} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className={styles.message}>
                  <Users size={28} />
                  <h3>
                    {filters.query ||
                    filters.role !== "all" ||
                    filters.status !== "all"
                      ? "No matching people"
                      : "Your people will appear here"}
                  </h3>
                  <p>
                    {filters.query ||
                    filters.role !== "all" ||
                    filters.status !== "all"
                      ? "Try another name or clear your filters."
                      : "Members appear when their academy account has been created."}
                  </p>
                  {(filters.query ||
                    filters.role !== "all" ||
                    filters.status !== "all") && (
                    <button
                      className="button button-secondary"
                      onClick={() => {
                        setQuery("");
                        reload(initialFilters);
                      }}
                    >
                      Clear filters
                    </button>
                  )}
                </div>
              )}
              <div className={styles.pagination}>
                <span>
                  {data.matching_count
                    ? `${(data.page - 1) * data.page_size + (data.members.length ? 1 : 0)}–${(data.page - 1) * data.page_size + data.members.length} of ${data.matching_count} people`
                    : "0 people"}
                </span>
                <div>
                  <button
                    aria-label="Previous page"
                    disabled={filters.page === 1}
                    onClick={() =>
                      reload({ ...filters, page: filters.page - 1 })
                    }
                  >
                    <ArrowLeft size={15} /> Previous
                  </button>
                  <span>Page {data.page}</span>
                  <button
                    aria-label="Next page"
                    disabled={data.page * data.page_size >= data.matching_count}
                    onClick={() =>
                      reload({ ...filters, page: filters.page + 1 })
                    }
                  >
                    Next <ArrowRight size={15} />
                  </button>
                </div>
              </div>
            </>
          )
        )}
      </section>
      {selected && (
        <section
          className={styles.detail}
          aria-labelledby="member-title"
          onKeyDown={(event) => {
            if (event.key === "Escape") close();
          }}
        >
          <div className={styles.header}>
            <div>
              <span className={styles.eyebrow}>Member record</span>
              <h2 id="member-title" ref={heading} tabIndex={-1}>
                {selected.display_name}
              </h2>
              <p>
                {selected.masked_email}
                {selected.username ? ` · @${selected.username}` : ""}
              </p>
            </div>
            <button
              aria-label="Close member record"
              className={styles.iconButton}
              onClick={close}
            >
              <X size={20} />
            </button>
          </div>
          <dl className={styles.facts}>
            <div>
              <dt>Academy role</dt>
              <dd>{titleCase(selected.membership_role)}</dd>
            </div>
            <div>
              <dt>Account</dt>
              <dd>{memberStatus(selected)}</dd>
            </div>
            <div>
              <dt>Active enrollments</dt>
              <dd>{selected.active_enrollments}</dd>
            </div>
          </dl>
          <p className={styles.note}>
            Course enrollment and permission to access content are separate.
            Open learning records to inspect current access and saved progress.
          </p>
          {selected.membership_role === "learner" &&
          selected.membership_status === "active" &&
          selected.account_status === "active" ? (
            <MemberLearning
              key={selected.person_id}
              member={selected}
              session={session}
              services={services}
              onDenied={() => {
                setLost(true);
                setSelected(null);
                setData(null);
                invalidate(session);
              }}
            />
          ) : (
            <p className={styles.note}>
              Learning records are available for active learner memberships.
              This member’s role remains {selected.membership_role}.
            </p>
          )}
        </section>
      )}
      <p className={styles.footnote}>
        People and course counts are scoped to this academy. Support reads are
        recorded in its access history.
      </p>
    </div>
  );
}

function MemberLearning({
  member,
  session,
  services,
  onDenied,
}: {
  member: DirectoryMember;
  session: AdminSession;
  services: DirectoryApi;
  onDenied: () => void;
}) {
  const [data, setData] = useState<AdminLearnerDiagnosis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  useEffect(() => {
    if (data) title.current?.focus();
  }, [data]);
  async function open() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(null);
    const timeout = setTimeout(() => {
      controller.abort();
      active.current = null;
      setBusy(false);
      setError("This took too long. Try again.");
    }, 15000);
    try {
      const result = await services.diagnose({
        tenantId: session.tenantId,
        personId: member.person_id,
        purpose: "learner_support",
        signal: controller.signal,
      });
      if (!controller.signal.aborted) setData(result);
    } catch (problem) {
      if (controller.signal.aborted) return;
      if (
        problem instanceof AdminApiProblem &&
        [401, 403].includes(problem.status)
      )
        onDenied();
      else setError("Learning records couldn’t be loaded. Try again.");
    } finally {
      clearTimeout(timeout);
      if (!controller.signal.aborted) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  return (
    <div className={styles.learning}>
      <button className="button" disabled={busy} onClick={() => void open()}>
        {busy
          ? "Loading learning records…"
          : data
            ? "Refresh learning records"
            : "View learning records"}
      </button>
      <span className={styles.note}>Purpose: learner support</span>
      {error && <p role="alert">{error}</p>}
      {data && <LearnerDiagnosisView diagnosis={data} headingRef={title} />}
    </div>
  );
}
