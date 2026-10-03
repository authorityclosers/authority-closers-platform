"use client";

import { useEffect, useState } from "react";
import { PlatformMark } from "@ac/ui";
import {
  loadPlatformIdentity,
  type PlatformIdentity,
} from "@ac/operations-web/platform-identity";
import {
  loadPlatformOrganisations,
  loadOrganisationMembers,
  type OrganisationMember,
  type PlatformOrganisations,
} from "@ac/operations-web/organisations";
import {
  OrganisationAction,
  actionLabels,
  organisationError,
  type MemberAction,
} from "./organisation-action";
import shell from "../platform-console.module.css";
import styles from "./organisations.module.css";

const date = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "—";

export function OrganisationsConsole() {
  const [identity, setIdentity] = useState<PlatformIdentity | null>(null);
  const [directory, setDirectory] = useState<PlatformOrganisations | null>(
    null,
  );
  const [members, setMembers] = useState<OrganisationMember[] | null>(null);
  const [selected, setSelected] = useState("");
  const [action, setAction] = useState<MemberAction | null>(null);
  const [pending, setPending] = useState(true);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const organisation = directory?.organisations.find(
    (row) => row.tenant_id === selected,
  );
  const canRead = identity?.permissions.includes("platform_tenants_read");
  const canManage =
    canRead && identity?.permissions.includes("platform_organisations_manage");

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const fresh = await loadPlatformIdentity({ signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!fresh || !fresh.permissions.includes("platform_tenants_read")) {
        setError(
          "Your current assignment does not include the organisation directory.",
        );
        return;
      }
      setIdentity(fresh);
      const list = await loadPlatformOrganisations({
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setDirectory(list);
      if (selected) {
        const rows = await loadOrganisationMembers(selected, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) setMembers(rows.members);
      }
    })()
      .catch((failure) => {
        if (!controller.signal.aborted) setError(organisationError(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => controller.abort();
  }, [selected, revision]);

  function refresh(tenantId = selected) {
    setIdentity(null);
    setDirectory(null);
    setMembers(null);
    setAction(null);
    setError("");
    setPending(true);
    setSelected(tenantId);
    setRevision((value) => value + 1);
  }

  return (
    <div className={shell.shell}>
      <header className={shell.header}>
        <a href="/platform" className={shell.brand}>
          <PlatformMark />
          <span>
            Cohorva<small>Platform Admin</small>
          </span>
        </a>
        <nav className={styles.navigation} aria-label="Platform">
          <a href="/platform">Platform</a>
          {canRead && (
            <a href="/platform/organisations" aria-current="page">
              Organisations
            </a>
          )}
        </nav>
      </header>
      <main id="admin-content" className={shell.main}>
        <div className={shell.heading}>
          <div>
            <p>PLATFORM WORKSPACE</p>
            <h1>Organisations</h1>
            <span>Members, invitations and organisation access.</span>
          </div>
          <button disabled={pending || writing} onClick={() => refresh()}>
            Refresh
          </button>
        </div>
        {pending && <p role="status">Loading organisations…</p>}
        {error && (
          <p role="alert" className={shell.error}>
            {error}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {directory && (
          <section className={shell.panel} aria-labelledby="directory-heading">
            <h2 id="directory-heading">Organisation directory</h2>
            {directory.organisations.length === 0 ? (
              <p>No organisations are available.</p>
            ) : (
              <div className={styles.scroll}>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Members</th>
                      <th scope="col">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {directory.organisations.map((row) => (
                      <tr key={row.tenant_id}>
                        <td>
                          <button
                            disabled={pending || writing}
                            aria-pressed={selected === row.tenant_id}
                            onClick={() => {
                              setNotice("");
                              refresh(row.tenant_id);
                            }}
                          >
                            {row.name}
                          </button>
                        </td>
                        <td>{row.member_count}</td>
                        <td>{date(row.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
        {organisation && members && (
          <section
            className={`${shell.panel} ${styles.members}`}
            aria-labelledby="members-heading"
          >
            <h2 id="members-heading">{organisation.name} · Members</h2>
            {canManage && (
              <button
                disabled={writing || !!action}
                onClick={() => setAction({ kind: "add" })}
              >
                Add by email
              </button>
            )}
            {members.length === 0 ? (
              <p>No members or invitations are available.</p>
            ) : (
              <div className={styles.scroll}>
                <table>
                  <thead>
                    <tr>
                      {[
                        "Name",
                        "Email",
                        "Role",
                        "Status",
                        "Joined",
                        "Last active",
                        "Minutes · 30 days",
                        "Calls · 30 days",
                        ...(canManage ? ["Actions"] : []),
                      ].map((heading) => (
                        <th key={heading} scope="col">
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((member) => (
                      <tr key={member.person_id ?? member.invite_id}>
                        <td>{member.name ?? "—"}</td>
                        <td>{member.email ?? "—"}</td>
                        <td>{member.role}</td>
                        <td>{member.status}</td>
                        <td>{date(member.joined_at)}</td>
                        <td>{date(member.last_active_at)}</td>
                        <td>{member.minutes_used_30d}</td>
                        <td>{member.calls_30d}</td>
                        {canManage && (
                          <td className={styles.actions}>
                            {(member.status === "invited" && member.invite_id
                              ? (["revoke"] as const)
                              : member.status === "active" &&
                                  member.person_id &&
                                  member.role !== "owner"
                                ? (["role", "remove", "transfer"] as const)
                                : []
                            ).map((kind) => (
                              <button
                                key={kind}
                                disabled={writing || !!action}
                                onClick={() => setAction({ kind, member })}
                              >
                                {actionLabels[kind]}
                              </button>
                            ))}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {action && canManage && identity && (
              <OrganisationAction
                action={action}
                organisation={organisation}
                identity={identity}
                onBusy={setWriting}
                onCancel={() => setAction(null)}
                onAccessChanged={() => {
                  refresh();
                  setNotice(
                    "Access changed. Checking your current assignment.",
                  );
                }}
                onSuccess={() => {
                  setNotice("Change saved.");
                  refresh();
                }}
              />
            )}
          </section>
        )}
      </main>
    </div>
  );
}
