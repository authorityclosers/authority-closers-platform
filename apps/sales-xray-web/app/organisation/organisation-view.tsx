"use client";

import {
  Building2,
  Coins,
  Gauge,
  Mail,
  Plus,
  ShieldCheck,
  UserPlus,
  Users,
  UsersRound,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { Allowance } from "../acquisition-client";
import { AcquisitionShell } from "../acquisition-shell";
import { readAllowance } from "../dashboard/dashboard-data";
import { useShellProfile } from "../shell/profile-store";
import { workspaceKind } from "../shell/workspace-switcher";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./organisation.module.css";

type Workspace = { tenant_id: string; name: string };
type OrgState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      workspaces: Workspace[];
      selected: string | null;
      role: string | null;
    };

const TABS = [
  { id: "overview", label: "Overview", icon: Building2 },
  { id: "members", label: "Members", icon: Users },
  { id: "teams", label: "Teams", icon: UsersRound },
  { id: "usage", label: "Usage & credits", icon: Gauge },
  { id: "company", label: "Company", icon: ShieldCheck },
] as const;
type Tab = (typeof TABS)[number]["id"];

const API_NOTE = "Arrives with the organisation API (AUT-422).";

function roleLabel(role: string | null): string {
  if (role === "owner") return "Owner";
  if (role === "admin") return "Admin";
  return role ? "Member" : "—";
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
}

async function readOrganisation(signal: AbortSignal): Promise<OrgState> {
  const get = (path: string) =>
    fetch(path, { credentials: "same-origin", signal }).then((response) => {
      if (!response.ok) throw new Error(String(response.status));
      return response.json() as Promise<Record<string, unknown>>;
    });
  const [choices, context] = await Promise.all([
    get("/v1/me/workspaces"),
    get("/v1/context").catch(() => null),
  ]);
  const workspaces = Array.isArray(choices.workspaces)
    ? (choices.workspaces as Workspace[]).filter(
        (item) =>
          typeof item?.tenant_id === "string" && typeof item?.name === "string",
      )
    : [];
  return {
    status: "ready",
    workspaces,
    selected:
      typeof choices.selected_tenant_id === "string"
        ? choices.selected_tenant_id
        : null,
    role:
      context && typeof context.membership_role === "string"
        ? context.membership_role
        : null,
  };
}

function Pending({
  icon,
  title,
  text,
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className={styles.pending}>
      <span className={styles.pendingIcon} aria-hidden="true">
        {icon}
      </span>
      <b>{title}</b>
      <p>{text}</p>
      <small>{API_NOTE}</small>
    </div>
  );
}

/** Company, members, teams, usage and shared credits for an organisation. */
export function OrganisationView() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const profile = useShellProfile(authenticated);
  const [state, setState] = useState<OrgState>({ status: "loading" });
  const [allowance, setAllowance] = useState<Allowance | null>(null);
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    readOrganisation(controller.signal)
      .then(setState)
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });
    readAllowance(controller.signal)
      .then(setAllowance)
      .catch(() => {});
    return () => controller.abort();
  }, [authenticated]);

  const current =
    state.status === "ready"
      ? (state.workspaces.find((item) => item.tenant_id === state.selected) ??
        null)
      : null;
  const isOrganisation =
    current !== null && workspaceKind(current.name) === "organisation";
  const organisations =
    state.status === "ready"
      ? state.workspaces.filter(
          (item) => workspaceKind(item.name) === "organisation",
        )
      : [];
  const you = profile?.name?.trim() || "You";
  const usedMinutes =
    allowance && !allowance.unlimited
      ? Math.max(
          0,
          Math.round(
            (allowance.allowance_seconds - allowance.available_seconds) / 60,
          ),
        )
      : null;
  const role = state.status === "ready" ? state.role : null;

  return (
    <AcquisitionShell
      authenticated={authenticated}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <div className={styles.page} data-organisation-view>
        {state.status === "loading" || !authenticated ? (
          <div className={styles.skeleton} aria-label="Loading organisation">
            <span />
            <span />
            <span />
          </div>
        ) : state.status === "error" ? (
          <p className={styles.note} role="alert">
            The organisation could not be loaded. Refresh to try again.
          </p>
        ) : !isOrganisation ? (
          <section className={styles.personal}>
            <span className={styles.bigTile} aria-hidden="true">
              <Building2 size={26} />
            </span>
            <h1>You are on your personal account</h1>
            <p>
              Organisations bring your sales team together: members, teams,
              shared minutes and everyone&apos;s usage in one place.
            </p>
            {organisations.length > 0 ? (
              <p className={styles.note}>
                Switch to {organisations.map((item) => item.name).join(", ")}{" "}
                from the account switcher at the top of the sidebar.
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
        ) : (
          <>
            <header className={styles.header}>
              <span className={styles.orgTile} aria-hidden="true">
                {initials(current.name)}
              </span>
              <div className={styles.headerCopy}>
                <h1>{current.name}</h1>
                <p>
                  Organisation · you are{" "}
                  <b className={styles.role}>{roleLabel(role)}</b>
                </p>
              </div>
              <button type="button" className={styles.invite} disabled>
                <UserPlus size={15} aria-hidden="true" /> Invite people
                <span className={styles.soon}>Soon</span>
              </button>
            </header>

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
                  <div className={styles.stat}>
                    <span>Your role</span>
                    <b>{roleLabel(role)}</b>
                  </div>
                  <div className={styles.stat}>
                    <span>Your minutes used</span>
                    <b>{usedMinutes ?? "—"}</b>
                  </div>
                  <div className={styles.stat} data-pending="">
                    <span>Members</span>
                    <b>—</b>
                    <small>{API_NOTE}</small>
                  </div>
                  <div className={styles.stat} data-pending="">
                    <span>Shared credits</span>
                    <b>—</b>
                    <small>Comes with organisation plans (AUT-410).</small>
                  </div>
                </div>
              )}

              {tab === "members" && (
                <div className={styles.table} role="table" aria-label="Members">
                  <div className={styles.thead} role="row">
                    <span role="columnheader">Person</span>
                    <span role="columnheader">Role</span>
                    <span role="columnheader">Minutes used</span>
                    <span role="columnheader">Status</span>
                  </div>
                  <div className={styles.tr} role="row">
                    <span role="cell" className={styles.person}>
                      <i aria-hidden="true">{initials(you)}</i>
                      <span>
                        <b>{you} (you)</b>
                        <small>{profile?.email ?? ""}</small>
                      </span>
                    </span>
                    <span role="cell">
                      <b className={styles.role}>{roleLabel(role)}</b>
                    </span>
                    <span role="cell">{usedMinutes ?? "—"}</span>
                    <span role="cell" className={styles.active}>
                      <i aria-hidden="true" /> Active
                    </span>
                  </div>
                  <p className={styles.tableNote}>
                    Other members, admins and invites show here. {API_NOTE}
                  </p>
                </div>
              )}

              {tab === "teams" && (
                <Pending
                  icon={<UsersRound size={22} />}
                  title="Teams"
                  text="Group people into teams, like inside sales or field sales, and see each team's calls, progress and minutes."
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
                  />
                  <Pending
                    icon={<Gauge size={22} />}
                    title="Usage by person"
                    text="Minutes and calls for every member, by week or month, so owners and admins can see who is using what."
                  />
                </div>
              )}

              {tab === "company" && (
                <form
                  className={styles.form}
                  onSubmit={(event) => event.preventDefault()}
                >
                  <label>
                    <span>Company name</span>
                    <input value={current.name} readOnly />
                  </label>
                  {[
                    "Website or domain",
                    "Industry",
                    "Team size",
                    "City",
                    "GST number",
                  ].map((label) => (
                    <label key={label}>
                      <span>{label}</span>
                      <input placeholder="Not set" disabled />
                    </label>
                  ))}
                  <p className={styles.note}>
                    Editing company details: {API_NOTE}
                  </p>
                </form>
              )}
            </div>
          </>
        )}
      </div>
    </AcquisitionShell>
  );
}
