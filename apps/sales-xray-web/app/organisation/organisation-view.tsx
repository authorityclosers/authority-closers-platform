"use client";

import {
  Activity,
  Building2,
  Coins,
  Crown,
  Gauge,
  Globe,
  Mail,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
  UsersRound,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";

import { callHref, type Allowance } from "../acquisition-client";
import { AcquisitionShell } from "../acquisition-shell";
import { callDate } from "../call-status";
import { readAllowance } from "../dashboard/dashboard-data";
import { formatClock } from "../lightbox/time";
import {
  readSalesXrayWorkspaces,
  type SalesXrayWorkspace as Workspace,
} from "../sales-xray-workspaces";
import { useWorkspaceAccess } from "../workspace-access";
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
  { id: "overview", label: "Overview", icon: Building2 },
  { id: "members", label: "Members", icon: Users },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "teams", label: "Teams", icon: UsersRound },
  { id: "usage", label: "Usage & credits", icon: Gauge },
  { id: "company", label: "Company", icon: ShieldCheck },
] as const;
type Tab = (typeof TABS)[number]["id"];

const NOT_LIVE = "Coming soon.";
const ROLES: OrgRole[] = ["owner", "admin", "member"];
const ROLE_LABEL: Record<OrgRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
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
): [Live<T>, () => void] {
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
  ];
}

function Pending({
  icon,
  title,
  text,
  note = NOT_LIVE,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  note?: string;
}) {
  return (
    <div className={styles.pending}>
      <span className={styles.pendingIcon} aria-hidden="true">
        {icon}
      </span>
      <b>{title}</b>
      <p>{text}</p>
      <small>{note}</small>
    </div>
  );
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: ReactNode;
  note?: string;
}) {
  return (
    <div className={styles.stat} data-pending={note ? "" : undefined}>
      <span>{label}</span>
      <b>{value}</b>
      {note ? <small>{note}</small> : null}
    </div>
  );
}

/** Company, members, company-wide activity, teams, usage and credits. */
export function OrganisationView() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const [base, setBase] = useState<Base>({ status: "loading" });
  const [allowance, setAllowance] = useState<Allowance | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    readBase(controller.signal)
      .then(setBase)
      .catch(() => {
        if (!controller.signal.aborted) setBase({ status: "error" });
      });
    readAllowance(controller.signal)
      .then(setAllowance)
      .catch(() => {});
    return () => controller.abort();
  }, [authenticated]);

  const current =
    base.status === "ready"
      ? (base.workspaces.find((item) => item.tenant_id === base.selected) ??
        null)
      : null;
  const isOrganisation = current?.kind === "organisation";

  const [org, reloadOrg] = useLive(readOrganisation, isOrganisation);
  const [members, reloadMembers] = useLive(readMembers, isOrganisation);
  const [activity] = useLive(readActivity, isOrganisation);
  const live = org.status === "ready";
  const myRole: OrgRole | null = org.status === "ready" ? org.value.role : null;
  const canManage = live && (myRole === "owner" || myRole === "admin");

  return (
    <AcquisitionShell
      authenticated={authenticated}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <div className={styles.page} data-organisation-view>
        {base.status === "loading" || !authenticated ? (
          <div className={styles.skeleton} aria-label="Loading organisation">
            <span />
            <span />
            <span />
          </div>
        ) : base.status === "error" ? (
          <p className={styles.note} role="alert">
            The organisation could not be loaded. Refresh to try again.
          </p>
        ) : !isOrganisation ||
          missing ||
          org.status === "missing" ||
          members.status === "missing" ? (
          <PersonalCard
            organisations={base.workspaces.filter(
              (item) => item.kind === "organisation",
            )}
          />
        ) : (
          <>
            <header className={styles.header}>
              <span className={styles.orgTile} aria-hidden="true">
                {initials(
                  org.status === "ready" ? org.value.name : current.name,
                )}
              </span>
              <div className={styles.headerCopy}>
                <h1>
                  {org.status === "ready" ? org.value.name : current.name}
                </h1>
                <p>
                  Organisation
                  {org.status === "ready"
                    ? ` · ${org.value.memberCount} ${org.value.memberCount === 1 ? "person" : "people"}`
                    : ""}{" "}
                  · you are{" "}
                  <b className={styles.role}>
                    {myRole ? ROLE_LABEL[myRole] : "—"}
                  </b>
                </p>
              </div>
              <button
                type="button"
                className={styles.primary}
                disabled={!canManage}
                title={live ? undefined : NOT_LIVE}
                onClick={() => setTab("members")}
              >
                <UserPlus size={15} aria-hidden="true" /> Add people
              </button>
            </header>

            {!live && org.status !== "loading" ? (
              <p className={styles.banner} role="alert">
                The organisation could not be loaded.
                <button
                  type="button"
                  className={styles.secondary}
                  onClick={reloadOrg}
                >
                  <RefreshCw size={13} aria-hidden="true" />
                  Try again
                </button>
              </p>
            ) : null}

            <nav className={styles.tabs} aria-label="Organisation sections">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  className={styles.tab}
                  aria-pressed={tab === id}
                  onClick={() => setTab(id)}
                >
                  <Icon size={15} aria-hidden="true" />
                  {label}
                </button>
              ))}
            </nav>

            <div key={tab} className={styles.panel}>
              {tab === "overview" && (
                <div className={styles.grid}>
                  <Stat
                    label="Your role"
                    value={myRole ? ROLE_LABEL[myRole] : "—"}
                  />
                  <Stat
                    label="People"
                    value={org.status === "ready" ? org.value.memberCount : "—"}
                    note={live ? undefined : NOT_LIVE}
                  />
                  <Stat
                    label="Calls, last 30 days"
                    value={
                      activity.status === "ready"
                        ? activity.value.calls.length
                        : "—"
                    }
                    note={activity.status === "ready" ? undefined : NOT_LIVE}
                  />
                  <Stat label="Shared credits" value="—" note="Coming soon." />
                </div>
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

              {tab === "activity" && (
                <ActivityPanel activity={activity} members={members} />
              )}

              {tab === "teams" && (
                <Pending
                  icon={<UsersRound size={22} />}
                  title="Teams"
                  text="Group people into teams, like inside sales or field sales, and see each team's calls, progress and minutes."
                  note="Coming soon."
                />
              )}

              {tab === "usage" && (
                <div className={styles.usage}>
                  <div className={styles.stat}>
                    <span>Your minutes</span>
                    <b>
                      {allowance
                        ? allowance.unlimited
                          ? "Unlimited"
                          : `${Math.floor(allowance.available_seconds / 60)} left`
                        : "—"}
                    </b>
                    {allowance && !allowance.unlimited ? (
                      <span className={styles.bar} aria-hidden="true">
                        <i
                          style={{
                            width: `${Math.min(100, (allowance.available_seconds / Math.max(1, allowance.allowance_seconds)) * 100)}%`,
                          }}
                        />
                      </span>
                    ) : null}
                  </div>
                  <Pending
                    icon={<Coins size={22} />}
                    title="Shared credits"
                    text="One pool of minutes for the whole organisation, with a limit for each person if you want one."
                    note="Coming soon."
                  />
                  <Pending
                    icon={<Gauge size={22} />}
                    title="Usage by person"
                    text="Minutes and calls for every member, so owners and admins see who is using what."
                    note={
                      activity.status === "ready"
                        ? "See the Activity tab."
                        : NOT_LIVE
                    }
                  />
                </div>
              )}

              {tab === "company" && (
                <CompanyPanel
                  key={org.status}
                  name={current.name}
                  org={org.status === "ready" ? org.value : null}
                  isOwner={live && myRole === "owner"}
                  reload={reloadOrg}
                />
              )}
            </div>
          </>
        )}
      </div>
    </AcquisitionShell>
  );
}

function PersonalCard({ organisations }: { organisations: Workspace[] }) {
  return (
    <section className={styles.personal}>
      <span className={styles.bigTile} aria-hidden="true">
        <Building2 size={26} />
      </span>
      <h1>You are on your personal account</h1>
      <p>
        Organisations bring your sales team together: people, teams, shared
        minutes and everyone&apos;s calls in one place.
      </p>
      {organisations.length > 0 ? (
        <p className={styles.note}>
          Switch to {organisations.map((item) => item.name).join(", ")} from the
          account switcher at the top of the sidebar.
        </p>
      ) : null}
      <div className={styles.actions}>
        <button type="button" disabled>
          <Plus size={15} aria-hidden="true" /> Create an organisation
          <span className={styles.soon}>Soon</span>
        </button>
        <button type="button" disabled>
          <Mail size={15} aria-hidden="true" /> Join with an invite
          <span className={styles.soon}>Soon</span>
        </button>
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
  const [problem, setProblem] = useState("");
  const [confirming, setConfirming] = useState<{
    message: string;
    action: () => Promise<unknown>;
    added?: boolean;
  } | null>(null);
  const additionRole = isOwner ? newRole : "member";

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setProblem("");
    try {
      await action();
      reload();
      return true;
    } catch (error) {
      if (noOrganisationSelected(error)) onMissing();
      else
        setProblem(
          error instanceof OrgApiError
            ? error.message
            : "That change was not saved. Try again.",
        );
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async (event: FormEvent) => {
    event.preventDefault();
    const address = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
      setProblem("Enter a full email address.");
      return;
    }
    setProblem("");
    setConfirming({
      message: `Add ${address} as ${ROLE_LABEL[additionRole]}?`,
      action: () => addMember(address, additionRole),
      added: true,
    });
  };

  const rows =
    members.status === "ready"
      ? members.value.filter(
          (member) => canManage || member.personId === yourPersonId,
        )
      : [];
  const disabled =
    !canManage || busy || confirming !== null || members.status !== "ready";

  return (
    <div className={styles.members}>
      <form className={styles.addRow} onSubmit={add}>
        <label className={styles.emailField}>
          <Mail size={15} aria-hidden="true" />
          <input
            type="email"
            placeholder="name@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={disabled}
            aria-label="Email to add"
          />
        </label>
        <select
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
        <button type="submit" className={styles.primary} disabled={disabled}>
          <UserPlus size={15} aria-hidden="true" /> Add
        </button>
        {!canManage ? (
          <small className={styles.hint}>
            {members.status === "off" || members.status === "loading"
              ? NOT_LIVE
              : "Only owners and admins can add people."}
          </small>
        ) : null}
      </form>
      {confirming ? (
        <div
          className={styles.card}
          role="dialog"
          aria-label="Confirm member change"
        >
          <p>{confirming.message}</p>
          <div className={styles.actions}>
            <button
              type="button"
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
              Confirm
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirming(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      {problem ? (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      ) : null}

      <div className={styles.table} role="table" aria-label="People">
        <div className={styles.thead} role="row">
          <span role="columnheader">Person</span>
          <span role="columnheader">Role</span>
          <span role="columnheader">Calls · 30 days</span>
          <span role="columnheader">Minutes · 30 days</span>
          <span role="columnheader">Status</span>
          <span role="columnheader" aria-label="Actions" />
        </div>
        {rows.map((member, index) => {
          const isYou =
            member.personId !== null && member.personId === yourPersonId;
          const name =
            member.name || member.email?.split("@")[0] || "Unnamed member";
          return (
            <div
              key={`${member.status}:${member.personId ?? member.inviteId}`}
              className={styles.tr}
              role="row"
              style={{ "--i": index } as CSSProperties}
            >
              <span role="cell" className={styles.person}>
                <i aria-hidden="true">{initials(name)}</i>
                <span>
                  <b>
                    {name}
                    {isYou ? " (you)" : ""}
                  </b>
                  <small>{member.email}</small>
                  <small>
                    Joined {member.joinedAt ? callDate(member.joinedAt) : "—"} ·
                    Last active{" "}
                    {member.lastActiveAt ? callDate(member.lastActiveAt) : "—"}
                  </small>
                </span>
              </span>
              <span role="cell">
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
                  <b className={styles.role} data-role={member.role}>
                    {member.role === "owner" ? (
                      <Crown size={11} aria-hidden="true" />
                    ) : null}
                    {ROLE_LABEL[member.role]}
                  </b>
                )}
              </span>
              <span role="cell" className={styles.num}>
                {member.calls30d}
              </span>
              <span role="cell" className={styles.num}>
                {member.minutesUsed30d}
              </span>
              <span
                role="cell"
                className={styles.status}
                data-status={member.status}
              >
                <i aria-hidden="true" />
                {member.status === "invited" ? "Invited" : "Active"}
              </span>
              <span role="cell" className={styles.rowActions}>
                {canManage &&
                !isYou &&
                member.role !== "owner" &&
                (member.status === "invited" ||
                  isOwner ||
                  member.role === "member") ? (
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
                            message: `Transfer ownership to ${name}? You will become an admin.`,
                            action: () => transferOwnership(member.personId),
                          })
                        }
                      >
                        <Crown size={14} />
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className={styles.icon}
                      title={
                        member.status === "invited" ? "Revoke invite" : "Remove"
                      }
                      aria-label={`${member.status === "invited" ? "Revoke invite for" : "Remove"} ${name}`}
                      disabled={busy || confirming !== null}
                      onClick={() =>
                        setConfirming({
                          message:
                            member.status === "invited"
                              ? `Revoke the invite for ${name}?`
                              : `Remove ${name} from the organisation?`,
                          action: () =>
                            member.status === "invited"
                              ? revokeInvite(member.inviteId)
                              : removeMember(member.personId),
                        })
                      }
                    >
                      <Trash2 size={14} />
                    </button>
                  </>
                ) : null}
              </span>
            </div>
          );
        })}
        {members.status !== "ready" ? (
          <p className={styles.tableNote}>
            {members.status === "loading"
              ? "Loading members…"
              : "Members could not be loaded."}
            {members.status !== "loading" ? (
              <button
                type="button"
                className={styles.secondary}
                onClick={reload}
              >
                <RefreshCw size={13} aria-hidden="true" />
                Try again
              </button>
            ) : null}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ActivityPanel({
  activity,
  members,
}: {
  activity: Live<OrgActivity>;
  members: Live<OrgMember[]>;
}) {
  if (activity.status !== "ready")
    return (
      <Pending
        icon={<Activity size={22} />}
        title="Company-wide activity"
        text="Every member's calls, minutes, reports and test activity for the last 30 days, in one view for owners and admins."
        note={activity.status === "loading" ? "Checking…" : NOT_LIVE}
      />
    );
  const nameOf = (personId: string) =>
    (members.status === "ready"
      ? members.value.find((member) => member.personId === personId)
      : null) ?? null;
  const people = [...activity.value.members].sort(
    (a, b) => b.minutes - a.minutes,
  );
  const top = Math.max(1, ...people.map((person) => person.minutes));
  const totals = people.reduce(
    (sum, person) => ({
      calls: sum.calls + person.calls,
      minutes: sum.minutes + person.minutes,
      reports: sum.reports + person.reportsReady,
      active: sum.active + (person.calls > 0 ? 1 : 0),
    }),
    { calls: 0, minutes: 0, reports: 0, active: 0 },
  );
  return (
    <div className={styles.activity}>
      <div className={styles.grid}>
        <Stat label="Calls · 30 days" value={totals.calls} />
        <Stat label="Minutes analysed" value={Math.round(totals.minutes)} />
        <Stat label="Reports ready" value={totals.reports} />
        <Stat label="People active" value={totals.active} />
      </div>
      <div className={styles.split}>
        <section className={styles.card}>
          <h2>Minutes by person</h2>
          <ul className={styles.bars}>
            {people.map((person, index) => {
              const member = nameOf(person.personId);
              const label = member?.name || member?.email || "Member";
              return (
                <li
                  key={person.personId}
                  style={{ "--i": index } as CSSProperties}
                >
                  <span>{label}</span>
                  <span className={styles.barTrack} aria-hidden="true">
                    <i style={{ width: `${(person.minutes / top) * 100}%` }} />
                  </span>
                  <b>{Math.round(person.minutes)}</b>
                </li>
              );
            })}
          </ul>
        </section>
        <section className={styles.card}>
          <h2>Latest calls across the organisation</h2>
          <ul className={styles.calls}>
            {activity.value.calls.slice(0, 8).map((call) => (
              <li key={call.id}>
                <Link href={callHref(call.id)} prefetch={false}>
                  <b>{call.label ?? "Untitled call"}</b>
                  <small>
                    {call.ownerName ?? "Member"} · {callDate(call.createdAt)} ·{" "}
                    {call.durationSeconds > 0
                      ? formatClock(call.durationSeconds * 1000)
                      : "—"}
                  </small>
                  <span
                    className={styles.status}
                    data-status={call.hasReport ? "active" : "invited"}
                  >
                    <i aria-hidden="true" />
                    {call.hasReport ? "Report ready" : "In progress"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function CompanyPanel({
  name,
  org,
  isOwner,
  reload,
}: {
  name: string;
  org: Organisation | null;
  isOwner: boolean;
  reload: () => void;
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
    <div className={styles.company}>
      <section className={styles.card}>
        <h2>
          <Globe size={16} aria-hidden="true" /> Company email domains
        </h2>
        <p className={styles.cardNote}>
          Your organisation owns these domains. Anyone who signs in with an
          email on them is recognised as your staff.
        </p>
        <div className={styles.chips}>
          {domains.map((domain) => (
            <span key={domain} className={styles.chip}>
              @{domain}
              {isOwner ? (
                <button
                  type="button"
                  aria-label={`Remove ${domain}`}
                  onClick={() =>
                    setDomains(domains.filter((item) => item !== domain))
                  }
                >
                  <X size={12} />
                </button>
              ) : null}
            </span>
          ))}
          {domains.length === 0 ? (
            <span className={styles.cardNote}>No domains yet.</span>
          ) : null}
        </div>
        <div className={styles.addRow}>
          <label className={styles.emailField}>
            <Globe size={15} aria-hidden="true" />
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
              disabled={!isOwner}
              aria-label="Domain to add"
            />
          </label>
          <button
            type="button"
            className={styles.ghost}
            onClick={addDomain}
            disabled={!isOwner}
          >
            <Plus size={14} aria-hidden="true" /> Add domain
          </button>
        </div>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={autoJoin}
            onChange={(event) => setAutoJoin(event.target.checked)}
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
          <button
            type="button"
            className={styles.primary}
            disabled={!isOwner || state === "saving"}
            onClick={() => void save()}
          >
            {state === "saving" ? "Saving…" : "Save"}
          </button>
          <small className={styles.hint} role="status">
            {!org
              ? NOT_LIVE
              : !isOwner
                ? "Only the owner can change domains."
                : state === "saved"
                  ? "Saved."
                  : state === "error"
                    ? "Not saved. Try again."
                    : ""}
          </small>
        </div>
      </section>
      <section className={styles.card}>
        <h2>
          <Building2 size={16} aria-hidden="true" /> Company details
        </h2>
        <form
          className={styles.form}
          onSubmit={(event) => event.preventDefault()}
        >
          <label>
            <span>Company name</span>
            <input value={name} readOnly />
          </label>
          {["Website", "Industry", "Team size", "City", "GST number"].map(
            (label) => (
              <label key={label}>
                <span>{label}</span>
                <input placeholder="Not set" disabled />
              </label>
            ),
          )}
        </form>
        <p className={styles.cardNote}>Editing company details: {NOT_LIVE}</p>
      </section>
    </div>
  );
}
