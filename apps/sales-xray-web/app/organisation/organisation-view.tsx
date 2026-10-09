"use client";

import {
  Building2,
  ChevronDown,
  Crown,
  Plus,
  RefreshCw,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import { callHref } from "../acquisition-client";
import { AcquisitionShell } from "../acquisition-shell";
import { callDate, callTone, submissionState } from "../call-status";
import { formatClock } from "../lightbox/time";
import { newCallHref } from "../new-call-navigation";
import { dismissNotice, notify } from "../notice-center";
import {
  readSalesXrayWorkspaces,
  type SalesXrayWorkspace as Workspace,
} from "../sales-xray-workspaces";
import { useWorkspaceAccess } from "../workspace-access";
import { CompanyDetailsPanel } from "./company-details-panel";
import {
  addMember,
  changeRole,
  noOrganisationSelected,
  notLive,
  OrgApiError,
  readActivity,
  readMembers,
  readOrganisation,
  removeMember,
  revokeInvite,
  saveDomains,
  transferOwnership,
  type OrgActivity,
  type OrgMember,
  type OrgRole,
  type Organisation,
} from "./organisation-api";
import styles from "./organisation.module.css";

type Base =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      workspaces: readonly Workspace[];
      selected: string | null;
    };
type Live<T> =
  | { status: "loading" }
  | { status: "off" }
  | { status: "missing" }
  | { status: "error" }
  | { status: "ready"; value: T };

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "members", label: "Members" },
  { id: "company", label: "Company" },
] as const;
type Tab = (typeof TABS)[number]["id"];
const isTab = (value: string | null): value is Tab =>
  TABS.some((item) => item.id === value);

const ROLES: OrgRole[] = ["owner", "admin", "member"];
const ROLE_LABEL: Record<OrgRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};
const CALLS_SHOWN = 8;
const ORG_NOTICE = "organisation-load";
const ACTION_NOTICE = "organisation-action";

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
}

/** Reserved test domains (RFC 2606/6761) only; never guessed from names. */
export function isTestEmail(email: string | null) {
  const domain = email?.split("@")[1]?.toLowerCase() ?? "";
  return (
    /\.(test|example|invalid|localhost)$/.test(domain) ||
    /^example\.(com|net|org)$/.test(domain)
  );
}

const memberName = (member: OrgMember) =>
  member.name || member.email || "Unnamed member";

/** Whole minutes; a call shorter than a minute is "<1", not zero. */
function minutes(value: number) {
  if (value > 0 && value < 1) return "<1";
  return Math.round(value).toLocaleString();
}

async function readBase(signal: AbortSignal): Promise<Base> {
  const choices = await readSalesXrayWorkspaces(signal);
  return {
    status: "ready",
    workspaces: choices.workspaces,
    selected: choices.selected_tenant_id,
  };
}

function useLive<T>(
  read: (signal: AbortSignal) => Promise<T>,
  enabled: boolean,
): [Live<T>, () => void, () => void] {
  const [state, setState] = useState<Live<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    read(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setState({ status: "ready", value });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({
          status: noOrganisationSelected(error)
            ? "missing"
            : notLive(error)
              ? "off"
              : "error",
        });
      });
    return () => controller.abort();
  }, [read, enabled, attempt]);
  return [
    state,
    useCallback(() => {
      setState({ status: "loading" });
      setAttempt((count) => count + 1);
    }, []),
    useCallback(() => setAttempt((count) => count + 1), []),
  ];
}

function initialTab(): Tab {
  if (typeof window === "undefined") return "overview";
  const value = new URLSearchParams(window.location.search).get("tab");
  return isTab(value) ? value : "overview";
}

/** Company, members and the organisation's calls in the last 30 days. */
export function OrganisationView() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const [base, setBase] = useState<Base>({ status: "loading" });
  const [baseAttempt, setBaseAttempt] = useState(0);
  const [tab, setTabState] = useState<Tab>(initialTab);
  const [missing, setMissing] = useState(false);

  const setTab = useCallback((next: Tab) => {
    setTabState(next);
    const url = new URL(window.location.href);
    if (next === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url);
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    readBase(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setBase(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setBase({ status: "error" });
      });
    return () => controller.abort();
  }, [
    authenticated,
    access?.context?.tenantId,
    access?.context?.sessionId,
    baseAttempt,
  ]);

  const current =
    base.status === "ready"
      ? (base.workspaces.find((item) => item.tenant_id === base.selected) ??
        null)
      : null;
  const isOrganisation = current?.kind === "organisation";
  const tenantId =
    authenticated &&
    isOrganisation &&
    current.tenant_id === access?.context?.tenantId
      ? current.tenant_id
      : null;
  const readCurrentOrganisation = useCallback(
    async (signal: AbortSignal) => {
      const value = await readOrganisation(signal);
      if (value.tenantId !== tenantId)
        throw new Error("Organisation tenant mismatch.");
      return value;
    },
    [tenantId],
  );
  const [org, reloadOrg, refreshOrganisation] = useLive(
    readCurrentOrganisation,
    isOrganisation && tenantId !== null,
  );
  const [members, reloadMembers] = useLive(readMembers, isOrganisation);
  const [activity, reloadActivity] = useLive(readActivity, isOrganisation);
  const live = org.status === "ready" && org.value.tenantId === tenantId;
  const myRole: OrgRole | null = live ? org.value.role : null;
  const canManage = live && (myRole === "owner" || myRole === "admin");
  const refreshAccess = useCallback(() => {
    refreshOrganisation();
    access?.retry();
  }, [refreshOrganisation, access]);
  const showPersonal = useCallback(() => setMissing(true), []);
  const personal =
    base.status === "ready" &&
    (!isOrganisation ||
      missing ||
      org.status === "missing" ||
      members.status === "missing");
  const orgFailed =
    base.status === "ready" &&
    !personal &&
    !live &&
    (org.status === "error" || org.status === "off" || tenantId === null);

  // A failed organisation read is a corner card, never a banner over the page.
  useEffect(() => {
    if (!orgFailed) return;
    notify({
      id: ORG_NOTICE,
      tone: "error",
      title: "The organisation could not be loaded.",
      message: "Names, roles and actions stay locked until it loads.",
      action: { label: "Try again", run: reloadOrg },
    });
    return () => dismissNotice(ORG_NOTICE);
  }, [orgFailed, reloadOrg]);

  const memberCount =
    org.status === "ready"
      ? org.value.memberCount
      : members.status === "ready"
        ? members.value.filter((member) => member.status === "active").length
        : null;
  const name = live ? org.value.name : (current?.name ?? "");

  return (
    <AcquisitionShell
      authenticated={authenticated}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <div className={styles.page} data-organisation-view>
        {base.status === "loading" || !authenticated ? (
          <PageSkeleton />
        ) : base.status === "error" ? (
          <section className={styles.state} role="alert">
            <span className={styles.stateIcon} aria-hidden="true">
              <Building2 size={20} />
            </span>
            <h1>The organisation could not be loaded</h1>
            <p>Check your connection, then try again.</p>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => {
                setBase({ status: "loading" });
                setBaseAttempt((count) => count + 1);
              }}
            >
              <RefreshCw size={14} aria-hidden="true" />
              Try again
            </button>
          </section>
        ) : personal ? (
          <PersonalState
            organisations={base.workspaces.filter(
              (item) => item.kind === "organisation",
            )}
          />
        ) : (
          <>
            <header className={styles.header}>
              <span className={styles.orgTile} aria-hidden="true">
                {initials(name)}
              </span>
              <div className={styles.headerCopy}>
                <h1>{name}</h1>
                <p>
                  <span>Organisation</span>
                  {memberCount !== null ? (
                    <span>
                      {memberCount} {memberCount === 1 ? "person" : "people"}
                    </span>
                  ) : null}
                  {myRole ? (
                    <span>
                      Your role: <b>{ROLE_LABEL[myRole]}</b>
                    </span>
                  ) : null}
                </p>
              </div>
            </header>

            <nav className={styles.tabs} aria-label="Organisation sections">
              {TABS.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  className={styles.tab}
                  aria-label={label}
                  aria-pressed={tab === id}
                  onClick={() => setTab(id)}
                >
                  {label}
                  {id === "members" && memberCount !== null ? (
                    <span className={styles.tabCount} aria-hidden="true">
                      {memberCount}
                    </span>
                  ) : null}
                </button>
              ))}
            </nav>

            <div key={tab} className={styles.panel}>
              {tab === "overview" && (
                <OverviewPanel
                  activity={activity}
                  members={members}
                  memberCount={memberCount}
                  team={canManage}
                  retry={reloadActivity}
                />
              )}

              {tab === "members" && (
                <MembersPanel
                  members={members}
                  reload={() => {
                    reloadMembers();
                    reloadOrg();
                  }}
                  canManage={canManage}
                  isOwner={live && myRole === "owner"}
                  yourPersonId={access?.context?.personId ?? null}
                  onMissing={() => setMissing(true)}
                />
              )}

              {tab === "company" && (
                <CompanyPanel
                  key={`${tenantId}:${org.status}`}
                  org={live ? org.value : null}
                  isOwner={live && myRole === "owner"}
                  reload={reloadOrg}
                  details={
                    <CompanyDetailsPanel
                      key={`${access?.context?.sessionId}:${tenantId}`}
                      tenantId={tenantId}
                      role={myRole}
                      authenticated={authenticated}
                      refresh={refreshOrganisation}
                      onAccessLost={refreshAccess}
                      onPersonal={showPersonal}
                    />
                  }
                />
              )}
            </div>
          </>
        )}
      </div>
    </AcquisitionShell>
  );
}

function PageSkeleton() {
  return (
    <div className={styles.skeleton} aria-label="Loading organisation">
      <div className={styles.skeletonHeader}>
        <span className={styles.skeletonTile} />
        <span className={styles.skeletonLines}>
          <i />
          <i />
        </span>
      </div>
      <span className={styles.skeletonTabs} />
      <SkeletonBlocks />
    </div>
  );
}

function SkeletonBlocks() {
  return (
    <>
      <span className={styles.skeletonStrip} />
      <span className={styles.skeletonTable} />
    </>
  );
}

function PersonalState({ organisations }: { organisations: Workspace[] }) {
  return (
    <section className={styles.state}>
      <span className={styles.stateIcon} aria-hidden="true">
        <Building2 size={20} />
      </span>
      <h1>You are on your personal account</h1>
      <p>
        An organisation brings your sales team together: its people, their calls
        and their reports in one place.
      </p>
      {organisations.length > 0 ? (
        <p className={styles.stateHint}>
          To open {organisations.map((item) => item.name).join(", ")}, switch
          workspace from the menu at the top of the sidebar.
        </p>
      ) : null}
    </section>
  );
}

type ActivityCall = OrgActivity["calls"][number];

/** Every figure comes from the same permitted calls that the table lists. */
function summarise(activity: OrgActivity) {
  const { calls, perDay, perRep } = activity;
  const fromDays = perDay.length > 0;
  const total = fromDays
    ? perDay.reduce(
        (sum, day) => ({
          calls: sum.calls + day.calls,
          minutes: sum.minutes + day.recordedMinutes,
          reports: sum.reports + day.reportsReady,
        }),
        { calls: 0, minutes: 0, reports: 0 },
      )
    : {
        calls: calls.length,
        minutes:
          calls.reduce((sum, call) => sum + call.durationSeconds, 0) / 60,
        reports: calls.filter((call) => call.hasReport).length,
      };
  const people =
    perRep.length > 0
      ? perRep.filter((rep) => rep.calls > 0).length
      : new Set(calls.map((call) => call.ownerPersonId)).size;
  const byDay = new Map(perDay.map((day) => [day.date, day.calls]));
  const today = new Date();
  const series = Array.from({ length: 30 }, (_, index) => {
    const day = new Date(
      Date.UTC(
        today.getUTCFullYear(),
        today.getUTCMonth(),
        today.getUTCDate() - (29 - index),
      ),
    );
    return byDay.get(day.toISOString().slice(0, 10)) ?? 0;
  });
  return { ...total, people, series };
}

function Kpi({
  label,
  value,
  context,
  series,
}: {
  label: string;
  value: ReactNode;
  context: ReactNode;
  series?: number[];
}) {
  // One or two busy days do not make a trend: show the number alone.
  const spark =
    series && series.filter((count) => count > 0).length >= 3 ? series : null;
  const top = spark ? Math.max(...spark) : 1;
  return (
    <div className={styles.kpi}>
      <dt>{label}</dt>
      <dd>
        <b>{value}</b>
        {spark ? (
          <span
            className={styles.spark}
            role="img"
            aria-label={`${label} per day over the last 30 days`}
          >
            {spark.map((count, index) => (
              <i
                key={index}
                data-empty={count === 0 ? "" : undefined}
                style={{ height: `${Math.max(8, (count / top) * 100)}%` }}
              />
            ))}
          </span>
        ) : null}
      </dd>
      <dd className={styles.kpiContext}>{context}</dd>
    </div>
  );
}

function OverviewPanel({
  activity,
  members,
  memberCount,
  team,
  retry,
}: {
  activity: Live<OrgActivity>;
  members: Live<OrgMember[]>;
  memberCount: number | null;
  team: boolean;
  retry: () => void;
}) {
  if (activity.status === "loading")
    return (
      <div className={styles.skeleton} aria-label="Loading activity">
        <SkeletonBlocks />
      </div>
    );
  if (activity.status !== "ready")
    return (
      <section className={styles.state}>
        <h2>
          {activity.status === "off"
            ? "Activity is not available on this server yet"
            : "Activity could not be loaded"}
        </h2>
        <p>Calls, minutes and reports for the last 30 days appear here.</p>
        {activity.status === "error" ? (
          <button type="button" className={styles.secondary} onClick={retry}>
            <RefreshCw size={14} aria-hidden="true" />
            Try again
          </button>
        ) : null}
      </section>
    );

  const totals = summarise(activity.value);
  return (
    <div className={styles.overview}>
      <section className={styles.section} aria-labelledby="org-period">
        <div className={styles.sectionHead}>
          <h2 id="org-period">Last 30 days</h2>
          <span>
            {team
              ? "Everyone in the organisation"
              : "Your calls in this organisation"}
          </span>
        </div>
        <dl className={styles.strip} data-columns={team ? 4 : 3}>
          <Kpi
            label="Calls"
            value={totals.calls}
            context={totals.calls === 1 ? "call saved" : "calls saved"}
            series={totals.series}
          />
          <Kpi
            label="Minutes recorded"
            value={minutes(totals.minutes)}
            context="length of those calls"
          />
          <Kpi
            label="Reports ready"
            value={totals.reports}
            context={`of ${totals.calls} ${totals.calls === 1 ? "call" : "calls"}`}
          />
          {team ? (
            <Kpi
              label="People with calls"
              value={totals.people}
              context={
                memberCount !== null
                  ? `of ${memberCount} ${memberCount === 1 ? "member" : "members"}`
                  : "members"
              }
            />
          ) : null}
        </dl>
      </section>

      <div className={styles.columns} data-team={team ? "" : undefined}>
        <CallsTable
          calls={activity.value.calls}
          total={totals.calls}
          team={team}
        />
        {team ? (
          <PeopleActivity activity={activity.value} members={members} />
        ) : null}
      </div>
    </div>
  );
}

function CallsTable({
  calls,
  total,
  team,
}: {
  calls: ActivityCall[];
  total: number;
  team: boolean;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? calls : calls.slice(0, CALLS_SHOWN);
  const title = team ? "Team calls" : "Your calls";
  return (
    <section className={styles.section} aria-labelledby="org-calls">
      <div className={styles.sectionHead}>
        <h2 id="org-calls">
          {title}
          <span className={styles.count}>{total}</span>
        </h2>
        <Link className={styles.textLink} href="/calls" prefetch={false}>
          Open Calls
        </Link>
      </div>
      {calls.length === 0 ? (
        <div className={styles.empty}>
          <b>No calls in the last 30 days</b>
          <p>
            {team
              ? "Calls saved by anyone in the organisation appear here with their report status."
              : "Your calls in this organisation appear here with their report status."}
          </p>
          <Link className={styles.secondary} href={newCallHref("/")}>
            <Plus size={14} aria-hidden="true" />
            Analyse a call
          </Link>
        </div>
      ) : (
        <div className={styles.surface}>
          <div className={styles.callTable} role="table" aria-label={title}>
            <div
              className={styles.callHead}
              role="row"
              data-team={team ? "" : undefined}
            >
              <span role="columnheader">Call</span>
              {team ? <span role="columnheader">Person</span> : null}
              <span role="columnheader">Date</span>
              <span role="columnheader" className={styles.num}>
                Length
              </span>
              <span role="columnheader">Report</span>
            </div>
            {shown.map((call) => {
              const submission = {
                id: call.id,
                createdAt: call.createdAt,
                durationSeconds: call.durationSeconds,
                state: call.state,
                hasReport: call.hasReport,
                label: null,
              };
              const person = call.ownerName ?? "Member";
              return (
                <Link
                  key={call.id}
                  href={callHref(call.id)}
                  prefetch={false}
                  className={styles.callRow}
                  role="row"
                  data-team={team ? "" : undefined}
                >
                  <span role="cell" className={styles.callName}>
                    {call.label ? (
                      <b>{call.label}</b>
                    ) : (
                      <b data-unnamed="">Unnamed call</b>
                    )}
                    <small className={styles.callMeta}>
                      {team ? `${person} · ` : ""}
                      {callDate(call.createdAt)}
                      {call.durationSeconds > 0
                        ? ` · ${formatClock(call.durationSeconds * 1000)}`
                        : ""}
                    </small>
                  </span>
                  {team ? (
                    <span role="cell" className={styles.callPerson}>
                      <i aria-hidden="true">{initials(person)}</i>
                      <span>{person}</span>
                    </span>
                  ) : null}
                  <span
                    role="cell"
                    className={styles.callDate}
                    title={new Date(call.createdAt).toLocaleString()}
                  >
                    {callDate(call.createdAt)}
                  </span>
                  <span
                    role="cell"
                    className={`${styles.num} ${styles.callLength}`}
                  >
                    {call.durationSeconds > 0
                      ? formatClock(call.durationSeconds * 1000)
                      : "—"}
                  </span>
                  <span
                    role="cell"
                    className={styles.callStatus}
                    data-tone={callTone(submission)}
                  >
                    <i aria-hidden="true" />
                    {submissionState(submission)}
                  </span>
                </Link>
              );
            })}
          </div>
          {calls.length > CALLS_SHOWN ? (
            <button
              type="button"
              className={styles.more}
              aria-expanded={all}
              onClick={() => setAll(!all)}
            >
              {all ? "Show fewer" : `Show all ${calls.length} calls`}
              <ChevronDown size={14} aria-hidden="true" />
            </button>
          ) : null}
          {total > calls.length ? (
            <p className={styles.footnote}>
              Showing the latest {calls.length} of {total} calls.
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

function PeopleActivity({
  activity,
  members,
}: {
  activity: OrgActivity;
  members: Live<OrgMember[]>;
}) {
  const [open, setOpen] = useState(false);
  const rows = useMemo(() => {
    const directory = members.status === "ready" ? members.value : [];
    const reps = new Map(activity.perRep.map((rep) => [rep.personId, rep]));
    const last = new Map<string, string>();
    for (const call of activity.calls)
      if (!last.has(call.ownerPersonId))
        last.set(call.ownerPersonId, call.createdAt);
    const people = directory
      .filter((member) => member.status === "active")
      .map((member) => {
        const rep = reps.get(member.personId ?? "");
        return {
          id: member.personId as string,
          name: memberName(member),
          email: member.email,
          test: isTestEmail(member.email),
          calls: rep?.calls ?? 0,
          minutes: rep?.recordedMinutes ?? 0,
          reports: rep?.reportsReady ?? 0,
          lastCall: last.get(member.personId ?? "") ?? null,
        };
      });
    // Reps whose directory row is not readable still count; never drop calls.
    for (const rep of activity.perRep)
      if (!people.some((person) => person.id === rep.personId))
        people.push({
          id: rep.personId,
          name: rep.name || "Member",
          email: null,
          test: false,
          calls: rep.calls,
          minutes: rep.recordedMinutes,
          reports: rep.reportsReady,
          lastCall: last.get(rep.personId) ?? null,
        });
    const names = new Map<string, number>();
    for (const person of people)
      names.set(person.name, (names.get(person.name) ?? 0) + 1);
    return people
      .map((person) => ({
        ...person,
        duplicate: (names.get(person.name) ?? 0) > 1,
      }))
      .sort(
        (a, b) =>
          Number(a.test) - Number(b.test) ||
          b.calls - a.calls ||
          b.minutes - a.minutes ||
          a.name.localeCompare(b.name),
      );
  }, [activity, members]);
  const active = rows.filter((row) => row.calls > 0 && !row.test);
  const quiet = rows.filter((row) => row.calls === 0 || row.test);
  const top = Math.max(1, ...rows.map((row) => row.calls));
  const shown = open ? [...active, ...quiet] : active;

  return (
    <section className={styles.section} aria-labelledby="org-people">
      <div className={styles.sectionHead}>
        <h2 id="org-people">Calls by person</h2>
      </div>
      <div className={styles.surface}>
        {members.status === "loading" ? (
          <p className={styles.footnote}>Loading people…</p>
        ) : null}
        {active.length === 0 && members.status !== "loading" ? (
          <p className={styles.footnote}>
            Nobody has saved a call in the last 30 days.
          </p>
        ) : null}
        <ul className={styles.people}>
          {shown.map((row) => (
            <li key={row.id} data-quiet={row.calls === 0 ? "" : undefined}>
              <i className={styles.avatar} aria-hidden="true">
                {initials(row.name)}
              </i>
              <span className={styles.personName}>
                <b>
                  <span className={styles.nameText}>{row.name}</span>
                  {row.test ? <span className={styles.tag}>Test</span> : null}
                </b>
                {row.duplicate && row.email ? <small>{row.email}</small> : null}
              </span>
              <span className={styles.personBar} aria-hidden="true">
                <i style={{ width: `${(row.calls / top) * 100}%` }} />
              </span>
              <span className={styles.personFigures}>
                <b>
                  {row.calls} {row.calls === 1 ? "call" : "calls"}
                </b>
                <small>
                  {row.calls > 0
                    ? `${minutes(row.minutes)} min · ${row.reports} ${row.reports === 1 ? "report" : "reports"}`
                    : "No calls"}
                </small>
              </span>
            </li>
          ))}
        </ul>
        {quiet.length > 0 ? (
          <button
            type="button"
            className={styles.more}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open
              ? "Show only people with calls"
              : `${quiet.length} more ${quiet.length === 1 ? "person" : "people"} with no calls or test accounts`}
            <ChevronDown size={14} aria-hidden="true" />
          </button>
        ) : null}
      </div>
    </section>
  );
}

function MembersPanel({
  members,
  reload,
  canManage,
  isOwner,
  yourPersonId,
  onMissing,
}: {
  members: Live<OrgMember[]>;
  reload: () => void;
  canManage: boolean;
  isOwner: boolean;
  yourPersonId: string | null;
  onMissing: () => void;
}) {
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<OrgRole>("member");
  const [busy, setBusy] = useState(false);
  const [invalid, setInvalid] = useState("");
  const [confirming, setConfirming] = useState<{
    message: string;
    verb: string;
    danger?: boolean;
    action: () => Promise<unknown>;
    added?: boolean;
  } | null>(null);
  const additionRole = isOwner ? newRole : "member";

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    dismissNotice(ACTION_NOTICE);
    try {
      await action();
      reload();
      return true;
    } catch (error) {
      if (noOrganisationSelected(error)) onMissing();
      else
        notify({
          id: ACTION_NOTICE,
          tone: "error",
          title: "That change was not saved.",
          message:
            error instanceof OrgApiError
              ? error.message
              : "Check your connection and try again.",
        });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async (event: FormEvent) => {
    event.preventDefault();
    const address = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
      setInvalid("Enter a full email address.");
      return;
    }
    setInvalid("");
    setConfirming({
      message: `Add ${address} as ${ROLE_LABEL[additionRole]}?`,
      verb: "Add",
      action: () => addMember(address, additionRole),
      added: true,
    });
  };

  const rows =
    members.status === "ready"
      ? members.value
          .filter((member) => canManage || member.personId === yourPersonId)
          .sort(
            (a, b) =>
              Number(isTestEmail(a.email)) - Number(isTestEmail(b.email)) ||
              ROLES.indexOf(a.role) - ROLES.indexOf(b.role) ||
              Number(a.status === "invited") - Number(b.status === "invited") ||
              memberName(a).localeCompare(memberName(b)),
          )
      : [];
  const disabled =
    !canManage || busy || confirming !== null || members.status !== "ready";
  const invited = rows.filter((member) => member.status === "invited").length;

  return (
    <section className={styles.section} aria-labelledby="org-members">
      <div className={styles.sectionHead}>
        <h2 id="org-members">
          People
          {members.status === "ready" ? (
            <span className={styles.count}>{rows.length - invited}</span>
          ) : null}
        </h2>
        {invited > 0 ? (
          <span>
            {invited} {invited === 1 ? "invite" : "invites"} waiting
          </span>
        ) : null}
      </div>
      <div className={styles.surface}>
        {canManage ? (
          <form className={styles.addRow} onSubmit={add} noValidate>
            <label
              className={styles.field}
              data-invalid={invalid ? "" : undefined}
            >
              <UserPlus size={15} aria-hidden="true" />
              <input
                type="email"
                placeholder="Add people by email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setInvalid("");
                }}
                disabled={disabled}
                aria-label="Email to add"
                aria-describedby={invalid ? "org-add-error" : undefined}
              />
            </label>
            <select
              className={styles.select}
              value={additionRole}
              onChange={(event) => setNewRole(event.target.value as OrgRole)}
              disabled={disabled}
              aria-label="Role for the new person"
            >
              {ROLES.filter(
                (item) => item === "member" || (isOwner && item === "admin"),
              ).map((item) => (
                <option key={item} value={item}>
                  {ROLE_LABEL[item]}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className={styles.primary}
              disabled={disabled}
            >
              Add
            </button>
            {invalid ? (
              <small
                id="org-add-error"
                className={styles.fieldError}
                role="alert"
              >
                {invalid}
              </small>
            ) : null}
          </form>
        ) : members.status === "ready" ? (
          <p className={styles.footnote}>
            Only owners and admins can add people or change roles.
          </p>
        ) : null}

        {confirming ? (
          <div
            className={styles.confirm}
            role="dialog"
            aria-label="Confirm member change"
          >
            <p>{confirming.message}</p>
            <div className={styles.confirmActions}>
              <button
                type="button"
                className={styles.ghost}
                disabled={busy}
                onClick={() => setConfirming(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={confirming.danger ? styles.danger : styles.primary}
                disabled={busy}
                onClick={() =>
                  void run(confirming.action).then((saved) => {
                    if (saved) {
                      if (confirming.added) setEmail("");
                      setConfirming(null);
                    }
                  })
                }
              >
                {busy ? "Saving…" : confirming.verb}
              </button>
            </div>
          </div>
        ) : null}

        <div className={styles.memberTable} role="table" aria-label="People">
          <div className={styles.memberHead} role="row">
            <span role="columnheader">Person</span>
            <span role="columnheader">Role</span>
            <span role="columnheader">Joined</span>
            <span role="columnheader">Last active</span>
            <span role="columnheader" aria-label="Actions" />
          </div>
          {rows.map((member) => {
            const isYou =
              member.personId !== null && member.personId === yourPersonId;
            const name = memberName(member);
            const manageable =
              canManage &&
              !isYou &&
              member.role !== "owner" &&
              (member.status === "invited" ||
                isOwner ||
                member.role === "member");
            return (
              <div
                key={`${member.status}:${member.personId ?? member.inviteId}`}
                className={styles.memberRow}
                role="row"
                data-invited={member.status === "invited" ? "" : undefined}
              >
                <span role="cell" className={styles.person}>
                  <i className={styles.avatar} aria-hidden="true">
                    {initials(name)}
                  </i>
                  <span className={styles.personName}>
                    <b>
                      <span className={styles.nameText}>{name}</span>
                      {isYou ? (
                        <span className={styles.you}> (you)</span>
                      ) : null}
                      {member.status === "invited" ? (
                        <span className={styles.tag} data-tone="info">
                          Invited
                        </span>
                      ) : null}
                      {isTestEmail(member.email) ? (
                        <span className={styles.tag}>Test</span>
                      ) : null}
                    </b>
                    <small>
                      {member.status === "invited" && !member.name
                        ? "Has not joined yet"
                        : member.email}
                    </small>
                  </span>
                </span>
                <span role="cell" className={styles.roleCell}>
                  {isOwner &&
                  member.status === "active" &&
                  !isYou &&
                  member.role !== "owner" ? (
                    <select
                      className={styles.roleSelect}
                      value={member.role}
                      disabled={busy || confirming !== null}
                      onChange={(event) => {
                        const nextRole = event.target.value as OrgRole;
                        setConfirming({
                          message: `Change ${name} to ${ROLE_LABEL[nextRole]}?`,
                          verb: "Change role",
                          action: () => changeRole(member.personId, nextRole),
                        });
                      }}
                      aria-label={`Role for ${name}`}
                    >
                      {ROLES.filter((item) => item !== "owner").map((item) => (
                        <option key={item} value={item}>
                          {ROLE_LABEL[item]}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className={styles.role} data-role={member.role}>
                      {member.role === "owner" ? (
                        <Crown size={12} aria-hidden="true" />
                      ) : null}
                      {ROLE_LABEL[member.role]}
                    </span>
                  )}
                </span>
                <span role="cell" className={styles.dateCell}>
                  <span className={styles.cellLabel}>Joined </span>
                  {member.joinedAt ? callDate(member.joinedAt) : "—"}
                </span>
                <span role="cell" className={styles.dateCell}>
                  <span className={styles.cellLabel}>Last active </span>
                  {member.lastActiveAt ? callDate(member.lastActiveAt) : "—"}
                </span>
                <span role="cell" className={styles.rowActions}>
                  {manageable ? (
                    <>
                      {isOwner && member.status === "active" ? (
                        <button
                          type="button"
                          className={styles.icon}
                          title="Make owner"
                          aria-label={`Make ${name} the owner`}
                          disabled={busy || confirming !== null}
                          onClick={() =>
                            setConfirming({
                              message: `Make ${name} the owner? You will become an admin.`,
                              verb: "Transfer ownership",
                              action: () => transferOwnership(member.personId),
                            })
                          }
                        >
                          <Crown size={15} />
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className={styles.icon}
                        title={
                          member.status === "invited"
                            ? "Revoke invite"
                            : "Remove"
                        }
                        aria-label={`${member.status === "invited" ? "Revoke invite for" : "Remove"} ${name}`}
                        disabled={busy || confirming !== null}
                        onClick={() =>
                          setConfirming(
                            member.status === "invited"
                              ? {
                                  message: `Revoke the invite for ${name}?`,
                                  verb: "Revoke invite",
                                  danger: true,
                                  action: () => revokeInvite(member.inviteId),
                                }
                              : {
                                  message: `Remove ${name} from the organisation?`,
                                  verb: "Remove",
                                  danger: true,
                                  action: () => removeMember(member.personId),
                                },
                          )
                        }
                      >
                        {member.status === "invited" ? (
                          <X size={15} />
                        ) : (
                          <Trash2 size={15} />
                        )}
                      </button>
                    </>
                  ) : null}
                </span>
              </div>
            );
          })}
          {members.status === "loading" ? (
            <div className={styles.rowSkeleton} aria-label="Loading members">
              <span />
              <span />
              <span />
            </div>
          ) : members.status !== "ready" ? (
            <div className={styles.tableNote}>
              <span>Members could not be loaded.</span>
              <button
                type="button"
                className={styles.secondary}
                onClick={reload}
              >
                <RefreshCw size={14} aria-hidden="true" />
                Try again
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function CompanyPanel({
  org,
  isOwner,
  reload,
  details,
}: {
  org: Organisation | null;
  isOwner: boolean;
  reload: () => void;
  details: ReactNode;
}) {
  const [domains, setDomains] = useState<string[]>(org?.verifiedDomains ?? []);
  const [autoJoin, setAutoJoin] = useState(org?.autoJoin ?? false);
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );

  const addDomain = () => {
    const domain = draft.trim().toLowerCase().replace(/^@/, "");
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(domain) || domains.includes(domain))
      return;
    setDomains([...domains, domain]);
    setDraft("");
    setState("idle");
  };

  const save = async () => {
    setState("saving");
    try {
      await saveDomains(domains, autoJoin);
      setState("saved");
      reload();
    } catch {
      setState("error");
    }
  };

  return (
    <div className={styles.settings}>
      {details}
      <section className={styles.setting} aria-labelledby="org-domains">
        <div className={styles.settingIntro}>
          <h2 id="org-domains">Email domains</h2>
          <p>
            People who sign in with an email on these domains are recognised as
            your staff.
          </p>
        </div>
        <div className={styles.settingBody}>
          <div className={styles.chips}>
            {domains.map((domain) => (
              <span key={domain} className={styles.chip}>
                @{domain}
                {isOwner ? (
                  <button
                    type="button"
                    aria-label={`Remove ${domain}`}
                    onClick={() => {
                      setDomains(domains.filter((item) => item !== domain));
                      setState("idle");
                    }}
                  >
                    <X size={12} />
                  </button>
                ) : null}
              </span>
            ))}
            {domains.length === 0 ? (
              <span className={styles.muted}>No domains yet.</span>
            ) : null}
          </div>
          {isOwner ? (
            <div className={styles.addRow}>
              <label className={styles.field}>
                <span className={styles.at} aria-hidden="true">
                  @
                </span>
                <input
                  placeholder="company.com"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addDomain();
                    }
                  }}
                  aria-label="Domain to add"
                />
              </label>
              <button
                type="button"
                className={styles.secondary}
                onClick={addDomain}
              >
                <Plus size={14} aria-hidden="true" /> Add domain
              </button>
            </div>
          ) : null}
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={autoJoin}
              onChange={(event) => {
                setAutoJoin(event.target.checked);
                setState("idle");
              }}
              disabled={!isOwner}
            />
            <span className={styles.switch} aria-hidden="true" />
            <span>
              <b>Join automatically</b>
              <small>
                People who sign in with these domains join as members without an
                invite.
              </small>
            </span>
          </label>
          <div className={styles.saveRow}>
            {isOwner ? (
              <button
                type="button"
                className={styles.primary}
                disabled={state === "saving"}
                onClick={() => void save()}
              >
                {state === "saving" ? "Saving…" : "Save domains"}
              </button>
            ) : null}
            <small
              className={styles.hint}
              role={state === "error" ? "alert" : "status"}
              data-tone={state === "error" ? "error" : undefined}
            >
              {!org
                ? "Domains appear once the organisation loads."
                : !isOwner
                  ? "Only the owner can change domains."
                  : state === "saved"
                    ? "Saved."
                    : state === "error"
                      ? "Not saved. Try again."
                      : ""}
            </small>
          </div>
        </div>
      </section>
    </div>
  );
}
