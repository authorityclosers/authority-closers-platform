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
import {
  Badge,
  Button,
  Card,
  Empty,
  Kpi,
  Panel,
  Skeleton,
  Table,
  Tiles,
  Toolbar,
  kitStyles,
  type Tone,
} from "../ui/kit";
import { Avatar } from "../ui/kit-client";
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
const STATUS_TONE: Record<string, Tone> = {
  Active: "good",
  "Email pending": "warn",
  Inactive: "neutral",
  Suspended: "bad",
};

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
      <section className={kitStyles.panel} role="status">
        <div className={kitStyles.empty}>
          <p className={kitStyles.emptyTitle}>People workspace</p>
          <p className={kitStyles.emptyText}>
            {state.status === "loading"
              ? "Loading your workspace…"
              : "Sign in with academy support access to view people."}
          </p>
        </div>
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
      <section className={kitStyles.panel} role="alert">
        <div className={kitStyles.empty}>
          <p className={kitStyles.emptyTitle}>Sign in to continue</p>
          <p className={kitStyles.emptyText}>Your workspace access changed.</p>
          <Link href="/login" className={kitStyles.button}>
            Sign in
          </Link>
        </div>
      </section>
    );
  const summary = data?.summary;
  const filtered = Boolean(
    filters.query || filters.role !== "all" || filters.status !== "all",
  );
  const joined = (iso: string) =>
    new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  const viewButton = (member: DirectoryMember, label = "View") => (
    <Button
      variant="ghost"
      aria-label={`View ${member.display_name}`}
      aria-expanded={selected?.person_id === member.person_id}
      onClick={(event) => {
        opener.current = event.currentTarget;
        setSelected(member);
      }}
    >
      {label} <ArrowRight size={14} aria-hidden="true" />
    </Button>
  );
  return (
    <div className={styles.workspace}>
      <Tiles label="Academy member summary">
        <Kpi label="People" value={summary?.total ?? "—"} />
        <Kpi label="Active learners" value={summary?.active_learners ?? "—"} />
        <Kpi label="Active team" value={summary?.team ?? "—"} />
        <Kpi
          label="Email pending"
          value={summary?.unverified ?? "—"}
          tone={summary?.unverified ? "warn" : undefined}
        />
      </Tiles>
      <div className={styles.columns} data-detail={selected ? "" : undefined}>
        <Panel
          title="Your people"
          sub={`${data ? data.tenant_name : "Academy workspace"} · members and their course activity`}
          tools={
            <Button
              variant="icon"
              aria-label="Refresh people"
              onClick={() => reload()}
              disabled={loading}
            >
              <RefreshCw size={16} aria-hidden="true" />
            </Button>
          }
          foot={
            data ? (
              <span className={styles.pagination}>
                <span>
                  {data.matching_count
                    ? `${(data.page - 1) * data.page_size + (data.members.length ? 1 : 0)}–${(data.page - 1) * data.page_size + data.members.length} of ${data.matching_count} people`
                    : "0 people"}
                </span>
                <span className={styles.pager}>
                  <Button
                    aria-label="Previous page"
                    disabled={filters.page === 1}
                    onClick={() =>
                      reload({ ...filters, page: filters.page - 1 })
                    }
                  >
                    <ArrowLeft size={14} aria-hidden="true" /> Previous
                  </Button>
                  <span>Page {data.page}</span>
                  <Button
                    aria-label="Next page"
                    disabled={data.page * data.page_size >= data.matching_count}
                    onClick={() =>
                      reload({ ...filters, page: filters.page + 1 })
                    }
                  >
                    Next <ArrowRight size={14} aria-hidden="true" />
                  </Button>
                </span>
              </span>
            ) : undefined
          }
        >
          <form className={styles.filters} onSubmit={search} role="search">
            <Toolbar label="Find people">
              <input
                type="search"
                aria-label="Search people"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                maxLength={320}
                placeholder="Search name, email or username"
              />
              <select
                aria-label="Role"
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
              <select
                aria-label="Status"
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
              <Button type="submit" variant="primary">
                <Search size={14} aria-hidden="true" />
                Search
              </Button>
            </Toolbar>
          </form>
          {error ? (
            <div className={kitStyles.empty} role="alert">
              <p className={kitStyles.emptyTitle}>People couldn’t be loaded</p>
              <p className={kitStyles.emptyText}>{error}</p>
              <Button onClick={() => reload()}>Try again</Button>
            </div>
          ) : loading ? (
            <div
              className={styles.skeleton}
              role="status"
              aria-label="Loading people"
              aria-busy="true"
            >
              {[0, 1, 2, 3, 4].map((row) => (
                <Skeleton key={row} height={20} />
              ))}
            </div>
          ) : data && data.members.length ? (
            <Table
              label="Academy people"
              cards={data.members.map((member) => (
                <Card key={member.person_id}>
                  <strong>{member.display_name}</strong>
                  <span>
                    {titleCase(member.membership_role)} · {memberStatus(member)}{" "}
                    · {member.active_enrollments} courses
                  </span>
                  <span>{viewButton(member, "Open record")}</span>
                </Card>
              ))}
            >
              <thead>
                <tr>
                  <th scope="col">Person</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col" data-num="">
                    Courses
                  </th>
                  <th scope="col">Joined</th>
                  <th scope="col">
                    <span className={kitStyles.srOnly}>Open record</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.members.map((member) => (
                  <tr
                    key={member.person_id}
                    data-selected={
                      selected?.person_id === member.person_id ? "" : undefined
                    }
                  >
                    <th scope="row">
                      <span className={styles.identity}>
                        <Avatar name={member.display_name} size={28} />
                        <span>
                          <strong>{member.display_name}</strong>
                          <small>
                            {member.username
                              ? `@${member.username}`
                              : member.masked_email}
                          </small>
                        </span>
                      </span>
                    </th>
                    <td>{titleCase(member.membership_role)}</td>
                    <td>
                      <Badge
                        tone={STATUS_TONE[memberStatus(member)] ?? "neutral"}
                      >
                        {memberStatus(member) === "Active" ? (
                          <Check size={12} aria-hidden="true" />
                        ) : null}
                        {memberStatus(member)}
                      </Badge>
                    </td>
                    <td data-num="">{member.active_enrollments}</td>
                    <td>
                      <time dateTime={member.joined_at}>
                        {joined(member.joined_at)}
                      </time>
                    </td>
                    <td>{viewButton(member)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : data ? (
            <Empty
              icon={Users}
              title={
                filtered ? "No matching people" : "Your people will appear here"
              }
              text={
                filtered
                  ? "Try another name or clear your filters."
                  : "Members appear when their academy account has been created."
              }
              action={
                filtered ? (
                  <Button
                    onClick={() => {
                      setQuery("");
                      reload(initialFilters);
                    }}
                  >
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          ) : null}
        </Panel>
        {selected ? (
          <section
            className={`${kitStyles.panel} ${styles.detail}`}
            aria-labelledby="member-title"
            onKeyDown={(event) => {
              if (event.key === "Escape") close();
            }}
          >
            <div className={kitStyles.panelHead}>
              <span className={styles.detailHead}>
                <small>Member record</small>
                <h2
                  id="member-title"
                  ref={heading}
                  tabIndex={-1}
                  className={kitStyles.panelTitle}
                >
                  {selected.display_name}
                </h2>
              </span>
              <Button
                variant="icon"
                aria-label="Close member record"
                onClick={close}
              >
                <X size={18} aria-hidden="true" />
              </Button>
            </div>
            <div className={styles.detailBody}>
              <p className={kitStyles.muted}>
                {selected.masked_email}
                {selected.username ? ` · @${selected.username}` : ""}
              </p>
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
                Open learning records to inspect current access and saved
                progress.
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
            </div>
          </section>
        ) : null}
      </div>
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
      <Button variant="primary" disabled={busy} onClick={() => void open()}>
        {busy
          ? "Loading learning records…"
          : data
            ? "Refresh learning records"
            : "View learning records"}
      </Button>
      <span className={styles.note}>Purpose: learner support</span>
      {error && (
        <p role="alert" className={kitStyles.fieldError}>
          {error}
        </p>
      )}
      {data && <LearnerDiagnosisView diagnosis={data} headingRef={title} />}
    </div>
  );
}
