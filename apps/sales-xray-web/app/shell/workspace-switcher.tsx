"use client";

import { Building2, Check, ChevronsUpDown, LogIn } from "lucide-react";
import Link from "next/link";
import type { MouseEvent, RefObject } from "react";
import type { SalesXrayWorkspace } from "../sales-xray-workspaces";
import type { Branding } from "./branding-store";
import { OrgLogo } from "./org-logo";

import styles from "./workspace-switcher.module.css";

type WorkspaceKind = SalesXrayWorkspace["kind"];
type Workspace = SalesXrayWorkspace;

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (name.slice(0, 2) || "·").toUpperCase();
}

/**
 * The sidebar's account switcher: Personal (your own account) and the
 * organisations you belong to, each clearly marked.
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
}) {
  const current =
    workspaces.find((workspace) => workspace.tenant_id === currentId) ??
    workspaces[0] ??
    null;
  const kind = current?.kind ?? "personal";
  const you = personName || "Your account";
  const title = current?.name ?? you;
  const subtitle = kind === "personal" ? "Personal account" : "Organisation";
  const personal = workspaces.filter(
    (workspace) => workspace.kind === "personal",
  );
  const organisations = workspaces.filter(
    (workspace) => workspace.kind === "organisation",
  );

  const logoFor = (tenantId: string | undefined) =>
    branding && branding.tenantId === tenantId ? branding.logoUrl : null;

  const item = (workspace: Workspace, itemKind: WorkspaceKind) => {
    const selected = workspace.tenant_id === current?.tenant_id;
    const name = workspace.name;
    return (
      <button
        key={workspace.tenant_id}
        type="button"
        role="menuitemradio"
        aria-checked={selected}
        className={styles.item}
        data-selected={selected ? "" : undefined}
        onClick={() => onSelect(workspace.tenant_id)}
      >
        <span className={styles.tile} data-kind={itemKind} aria-hidden="true">
          <OrgLogo
            src={logoFor(workspace.tenant_id)}
            fallback={
              itemKind === "organisation" ? (
                <Building2 size={14} />
              ) : (
                initials(name)
              )
            }
          />
        </span>
        <span className={styles.itemCopy}>
          <b>{name}</b>
          <small>
            {itemKind === "personal" ? "Just you" : "Your organisation"}
          </small>
        </span>
        {selected ? (
          <Check size={15} className={styles.check} aria-hidden="true" />
        ) : null}
      </button>
    );
  };

  return (
    <div className={styles.container} ref={containerRef}>
      <button
        type="button"
        className={styles.trigger}
        data-loading={pending ? "" : undefined}
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Current workspace: ${title}`}
        title={title}
      >
        <span className={styles.tile} data-kind={kind} aria-hidden="true">
          <OrgLogo
            src={logoFor(current?.tenant_id)}
            fallback={
              kind === "organisation" ? (
                <Building2 size={15} />
              ) : (
                initials(title)
              )
            }
          />
        </span>
        <span className={styles.copy}>
          <b>{title}</b>
          <small>{subtitle}</small>
        </span>
        <ChevronsUpDown
          size={14}
          className={styles.chevron}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div className={styles.menu} role="menu" aria-label="Switch account">
          {personal.length > 0 && (
            <>
              <p className={styles.group}>Personal</p>
              {personal.map((workspace) => item(workspace, "personal"))}
            </>
          )}
          <p className={styles.group}>Organisations</p>
          {organisations.length > 0 ? (
            organisations.map((workspace) => item(workspace, "organisation"))
          ) : (
            <p className={styles.empty}>You are not in an organisation yet.</p>
          )}
          {/* Create and join appear when the server can do them (AUT-1694);
              the menu never shows a promise it cannot keep. */}
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
