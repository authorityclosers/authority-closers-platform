"use client";

import { ChevronsUpDown, LogIn } from "lucide-react";
import Link from "next/link";
import type { MouseEvent, RefObject } from "react";
import type { PendingInvite } from "../organisation/organisation-api";
import type { SalesXrayWorkspace } from "../sales-xray-workspaces";
import type { Branding } from "./branding-store";
import {
  WorkspacePicker,
  WorkspaceTile,
  workspaceShortLine,
  workspaceName,
  type PickerWorkspace,
} from "./workspace-picker";
import styles from "./workspace-switcher.module.css";

type Workspace = SalesXrayWorkspace;

/**
 * The sidebar's switcher (design system v2): the current workspace, what it
 * is and your role, and one click to the list (workspace-picker.tsx):
 * others one tap away, invitations, and Create apart.
 */
export function WorkspaceSwitcher({
  workspaces,
  currentId,
  personName,
  branding = null,
  pending,
  open,
  setOpen,
  containerRef,
  onSelect,
  invites = [],
  joining = null,
  onJoin,
  onCreate,
}: {
  workspaces: readonly Workspace[];
  currentId: string | null;
  personName: string | null;
  /** The selected workspace's logo, when it has one. */
  branding?: Branding | null;
  pending: boolean;
  open: boolean;
  setOpen: (next: boolean) => void;
  containerRef: RefObject<HTMLDivElement | null>;
  onSelect: (tenantId: string) => void;
  /** Invitations waiting for you; each joins in one step. */
  invites?: readonly PendingInvite[];
  /** The invitation being accepted now. */
  joining?: string | null;
  onJoin?: (invite: PendingInvite) => void;
  /** Offered only where the server can create organisations. */
  onCreate?: () => void;
}) {
  const current =
    workspaces.find((workspace) => workspace.tenant_id === currentId) ??
    workspaces[0] ??
    null;
  const you = personName || "Your account";
  const shown: PickerWorkspace = current ?? {
    tenant_id: "",
    kind: "personal",
    name: you,
  };
  const title = current?.name ?? you;
  const waiting = invites.length;
  const logo =
    branding && current && branding.tenantId === current.tenant_id
      ? branding.logoUrl
      : null;
  return (
    <div className={styles.container} ref={containerRef}>
      <button
        type="button"
        className={styles.trigger}
        data-loading={pending ? "" : undefined}
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Current workspace: ${title}${
          waiting
            ? ` · ${waiting} ${waiting === 1 ? "invitation" : "invitations"} waiting`
            : ""
        }`}
        title={title}
      >
        <span className={styles.tileWrap}>
          <WorkspaceTile
            workspace={shown}
            logoUrl={logo}
            size="sm"
            personName={personName}
          />
          {waiting ? <i className={styles.dot} /> : null}
        </span>
        <span className={styles.copy}>
          <b>{workspaceName(shown)}</b>
          <small>{workspaceShortLine(shown)}</small>
        </span>
        <ChevronsUpDown
          size={14}
          className={styles.chevron}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div className={styles.menu} role="menu" aria-label="Switch account">
          <WorkspacePicker
            menu
            workspaces={workspaces}
            currentId={current?.tenant_id ?? null}
            onSelect={onSelect}
            onKeep={() => setOpen(false)}
            branding={branding}
            invites={invites}
            joining={joining}
            onJoin={onJoin}
            onCreate={onCreate}
            personName={personName}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Signed out there is no workspace to name: the switcher's place offers
 * sign-in instead, in the same size, so nothing moves when the session settles.
 */
export function GuestSwitcher({
  href,
  onSignIn,
}: {
  href: string;
  onSignIn: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  return (
    <div className={styles.container}>
      <Link className={styles.trigger} href={href} onClick={onSignIn}>
        <span className={styles.tile} data-kind="personal" aria-hidden="true">
          <LogIn size={14} />
        </span>
        <span className={styles.copy}>
          <b>Sign in</b>
          <small>to see your calls</small>
        </span>
      </Link>
    </div>
  );
}
