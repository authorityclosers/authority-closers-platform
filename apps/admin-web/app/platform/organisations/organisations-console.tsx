"use client";

import { Building2, RefreshCw, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
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
import {
  Badge,
  Button,
  Empty,
  Page,
  PageHeader,
  Panel,
  Skeleton,
  Table,
  Unavailable,
  kitStyles,
} from "../../ui/kit";
import styles from "./organisations.module.css";
import { istStamp } from "../../lib/time";

const date = (value: string | null) => istStamp(value);

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
    <Page>
      <PageHeader
        title="Organisations"
        context={["Members, invitations and organisation access"]}
        actions={
          <Button disabled={pending || writing} onClick={() => refresh()}>
            <RefreshCw size={14} aria-hidden="true" />
            Refresh
          </Button>
        }
      />
      {pending ? (
        <p role="status" className={kitStyles.srOnly}>
          Loading organisations…
        </p>
      ) : null}
      {error ? (
        <Unavailable title="The organisation directory" reason={error} />
      ) : null}
      {notice ? (
        <p role="status" className={styles.notice}>
          {notice}
        </p>
      ) : null}
      {pending && !directory ? (
        <Panel title="Organisation directory">
          <div className={styles.skeleton} aria-hidden="true">
            {[0, 1, 2, 3].map((row) => (
              <Skeleton key={row} height={20} />
            ))}
          </div>
        </Panel>
      ) : null}
      {directory ? (
        <Panel
          title="Organisation directory"
          sub={`${directory.organisations.length} organisations`}
        >
          {directory.organisations.length === 0 ? (
            <Empty icon={Building2} title="No organisations are available." />
          ) : (
            <Table label="Organisation directory">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col" data-num="">
                    Members
                  </th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {directory.organisations.map((row) => (
                  <tr
                    key={row.tenant_id}
                    data-selected={selected === row.tenant_id ? "" : undefined}
                    className={styles.row}
                  >
                    <td>
                      <button
                        className={styles.nameButton}
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
                    <td data-num="">{row.member_count}</td>
                    <td>{date(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>
      ) : null}
      {organisation && members ? (
        <Panel
          title={`${organisation.name} · Members`}
          tools={
            canManage ? (
              <Button
                variant="primary"
                disabled={writing || !!action}
                onClick={() => setAction({ kind: "add" })}
              >
                Add by email
              </Button>
            ) : null
          }
        >
          {members.length === 0 ? (
            <Empty
              icon={UsersRound}
              title="No members or invitations are available."
            />
          ) : (
            <Table label={`${organisation.name} members`}>
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
                    <td>
                      <Badge
                        tone={
                          member.status === "active"
                            ? "good"
                            : member.status === "invited"
                              ? "accent"
                              : "neutral"
                        }
                      >
                        {member.status}
                      </Badge>
                    </td>
                    <td>{date(member.joined_at)}</td>
                    <td>{date(member.last_active_at)}</td>
                    <td data-num="">{member.minutes_used_30d}</td>
                    <td data-num="">{member.calls_30d}</td>
                    {canManage ? (
                      <td className={styles.actions}>
                        {(member.status === "invited" && member.invite_id
                          ? (["revoke"] as const)
                          : member.status === "active" &&
                              member.person_id &&
                              member.role !== "owner"
                            ? (["role", "remove", "transfer"] as const)
                            : []
                        ).map((kind) => (
                          <Button
                            key={kind}
                            variant="ghost"
                            disabled={writing || !!action}
                            onClick={() => setAction({ kind, member })}
                          >
                            {actionLabels[kind]}
                          </Button>
                        ))}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {action && canManage && identity ? (
            <OrganisationAction
              action={action}
              organisation={organisation}
              identity={identity}
              onBusy={setWriting}
              onCancel={() => setAction(null)}
              onAccessChanged={() => {
                refresh();
                setNotice("Access changed. Checking your current assignment.");
              }}
              onSuccess={() => {
                setNotice("Change saved.");
                refresh();
              }}
            />
          ) : null}
        </Panel>
      ) : null}
    </Page>
  );
}
