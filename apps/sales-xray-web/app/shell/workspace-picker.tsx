"use client";

/**
 * Choosing where you work (design system v2; owner, 20 Oct: "workspaces
 * shifter needs to be made in a far better way").
 *
 * One list, used by the sidebar's switcher and the phone account sheet:
 * - the current workspace first and prominent, with what it is and your
 *   role in it;
 * - every other workspace one tap away;
 * - invitations waiting, each joined in one tap;
 * - "Create an organisation" apart from the list, as an action, never
 *   mistaken for a place you can switch to.
 */
import { roleLabel } from "../organisation/roles";
import { Building2, Check, MailOpen, Plus } from "lucide-react";

import type { PendingInvite } from "../organisation/organisation-api";
import type { SalesXrayWorkspace } from "../sales-xray-workspaces";
import type { Branding } from "./branding-store";
import { OrgLogo } from "./org-logo";
import styles from "./workspace-picker.module.css";

export type PickerWorkspace = Pick<
  SalesXrayWorkspace,
  "tenant_id" | "kind" | "name"
> &
  Partial<Pick<SalesXrayWorkspace, "role">>;

export function workspaceInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (name.slice(0, 2) || "·").toUpperCase();
}

const ROLE: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

/** "Personal · Just you", "Organisation · Admin". */
export function workspaceLine(workspace: PickerWorkspace): string {
  if (workspace.kind === "personal") return "Personal · Just you";
  const role = workspace.role ? ROLE[workspace.role] : null;
  return role ? `Organisation · ${role}` : "Organisation";
}

/**
 * The short line under the current workspace's name in the narrow switcher:
 * the role alone ("Owner"), since the name above says which organisation;
 * "Organisation · Owner" was cut mid-word in the rail (polish pass, 24 Oct
 * 2026). The picker's list keeps workspaceLine.
 */
export function workspaceShortLine(workspace: PickerWorkspace): string {
  if (workspace.kind === "personal") return "Just you";
  return (workspace.role ? ROLE[workspace.role] : null) ?? "Organisation";
}

/** Personal shows as "Personal", an organisation by its name. */
export function workspaceName(workspace: PickerWorkspace): string {
  return workspace.kind === "personal" ? "Personal" : workspace.name;
}

export function WorkspaceTile({
  workspace,
  logoUrl = null,
  size = "md",
  personName = null,
}: {
  workspace: PickerWorkspace;
  logoUrl?: string | null;
  size?: "sm" | "md" | "lg";
  /** Personal shows your own initials, never the word "Personal". */
  personName?: string | null;
}) {
  return (
    <span
      className={styles.tile}
      data-kind={workspace.kind}
      data-size={size}
      aria-hidden="true"
    >
      <OrgLogo
        src={logoUrl}
        fallback={
          workspace.kind === "organisation" ? (
            <Building2 size={size === "lg" ? 18 : 15} />
          ) : (
            workspaceInitials(
              (workspace.kind === "personal" && personName) || workspace.name,
            )
          )
        }
      />
    </span>
  );
}

export function WorkspacePicker({
  workspaces,
  currentId,
  onSelect,
  branding = null,
  invites = [],
  joining = null,
  onJoin,
  onCreate,
  onKeep,
  menu = false,
  personName = null,
}: {
  workspaces: readonly PickerWorkspace[];
  currentId: string | null;
  onSelect: (tenantId: string) => void;
  /** A tap on the current workspace: nothing to switch, so just close. */
  onKeep?: () => void;
  /** The selected workspace's logo, when it has one. */
  branding?: Branding | null;
  invites?: readonly PendingInvite[];
  joining?: string | null;
  onJoin?: (invite: PendingInvite) => void;
  /** Offered only where the server can create organisations. */
  onCreate?: () => void;
  /** Inside a menu button's popup: menu roles for the items. */
  menu?: boolean;
  /** For Personal's tile: your initials. */
  personName?: string | null;
}) {
  const current =
    workspaces.find((workspace) => workspace.tenant_id === currentId) ?? null;
  const others = workspaces.filter(
    (workspace) => workspace.tenant_id !== current?.tenant_id,
  );
  const logoFor = (tenantId: string) =>
    branding && branding.tenantId === tenantId ? branding.logoUrl : null;
  const itemRole = menu ? "menuitemradio" : undefined;
  return (
    <div className={styles.picker}>
      {current ? (
        <button
          type="button"
          className={styles.current}
          role={itemRole}
          aria-checked={menu ? true : undefined}
          aria-current={menu ? undefined : "true"}
          onClick={onKeep}
        >
          <WorkspaceTile
            workspace={current}
            logoUrl={logoFor(current.tenant_id)}
            size="lg"
            personName={personName}
          />
          <span className={styles.copy}>
            <b>{workspaceName(current)}</b>
            <small>{workspaceLine(current)}</small>
          </span>
          <Check size={16} className={styles.check} aria-label="Current" />
        </button>
      ) : null}
      {others.length ? (
        <>
          <p className={styles.label}>Switch to</p>
          {others.map((workspace) => (
            <button
              key={workspace.tenant_id}
              type="button"
              role={itemRole}
              aria-checked={menu ? false : undefined}
              className={styles.item}
              onClick={() => onSelect(workspace.tenant_id)}
            >
              <WorkspaceTile
                workspace={workspace}
                logoUrl={logoFor(workspace.tenant_id)}
                personName={personName}
              />
              <span className={styles.copy}>
                <b>{workspaceName(workspace)}</b>
                <small>{workspaceLine(workspace)}</small>
              </span>
            </button>
          ))}
        </>
      ) : null}
      {invites.length && onJoin ? (
        <>
          <p className={styles.label}>Invitations</p>
          {invites.map((invite) => (
            <button
              key={invite.inviteId}
              type="button"
              role={menu ? "menuitem" : undefined}
              className={styles.item}
              disabled={joining !== null}
              aria-label={`Join ${invite.organisationName} as ${
                invite.role === "admin" ? "an admin" : "a member"
              }`}
              onClick={() => onJoin(invite)}
            >
              <span
                className={styles.tile}
                data-kind="invite"
                aria-hidden="true"
              >
                <MailOpen size={15} />
              </span>
              <span className={styles.copy}>
                <b>{invite.organisationName}</b>
                <small>Invited as {roleLabel(invite.role).toLowerCase()}</small>
              </span>
              <span className={styles.join} aria-hidden="true">
                {joining === invite.inviteId ? "Joining…" : "Join"}
              </span>
            </button>
          ))}
        </>
      ) : null}
      {/* Create appears only where the server can do it (AUT-1694), and as
          an action of its own, apart from the places you can switch to. */}
      {onCreate ? (
        <button
          type="button"
          role={menu ? "menuitem" : undefined}
          className={styles.create}
          onClick={onCreate}
        >
          <Plus size={15} aria-hidden="true" />
          Create an organisation
        </button>
      ) : null}
    </div>
  );
}
