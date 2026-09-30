"use client";

import { Building2, Check, ChevronsUpDown, Mail, Plus } from "lucide-react";
import type { RefObject } from "react";

import styles from "./workspace-switcher.module.css";

export type WorkspaceKind = "personal" | "organisation";
type Workspace = { tenant_id: string; name: string };

/**
 * Personal accounts do not need a workspace (owner decision, 30 Sep 2026).
 * Until workspace choices carry their kind (AUT-422), the shared sign-up
 * workspace is shown as the person's own Personal account.
 */
export function workspaceKind(name: string): WorkspaceKind {
  return /public learners|closers academy/i.test(name)
    ? "personal"
    : "organisation";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (name.slice(0, 2) || "·").toUpperCase();
}

/**
 * The sidebar's account switcher: Personal (your own account) and the
 * organisations you belong to, each clearly marked, with create and join.
 */
export function WorkspaceSwitcher({
  workspaces,
  currentId,
  personName,
  pending,
  open,
  setOpen,
  containerRef,
  onSelect,
}: {
  workspaces: readonly Workspace[];
  currentId: string | null;
  personName: string | null;
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
  const kind = current ? workspaceKind(current.name) : "personal";
  const you = personName || "Your account";
  const title = kind === "personal" ? you : current!.name;
  const subtitle = kind === "personal" ? "Personal account" : "Organisation";
  const personal = workspaces.filter(
    (workspace) => workspaceKind(workspace.name) === "personal",
  );
  const organisations = workspaces.filter(
    (workspace) => workspaceKind(workspace.name) === "organisation",
  );

  const item = (workspace: Workspace, itemKind: WorkspaceKind) => {
    const selected = workspace.tenant_id === current?.tenant_id;
    const name = itemKind === "personal" ? you : workspace.name;
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
          {itemKind === "organisation" ? (
            <Building2 size={14} />
          ) : (
            initials(name)
          )}
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
          {kind === "organisation" ? <Building2 size={15} /> : initials(title)}
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
          <span className={styles.separator} />
          <button type="button" className={styles.action} disabled>
            <Plus size={15} aria-hidden="true" />
            Create an organisation
            <span className={styles.soon}>Soon</span>
          </button>
          <button type="button" className={styles.action} disabled>
            <Mail size={15} aria-hidden="true" />
            Join with an invite
            <span className={styles.soon}>Soon</span>
          </button>
        </div>
      )}
    </div>
  );
}
