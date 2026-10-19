"use client";

/**
 * Who is signed in, at the top of the rail, and under that person every
 * organisation and account Admin can see, grouped by what it is. Picking one
 * opens its calls. The list comes with the page, so nothing shifts when it
 * opens.
 */
import Link from "next/link";
import { ChevronsUpDown, Settings2 } from "lucide-react";

import type { ConsoleAccess } from "../lib/nav";
import {
  KIND_BADGE,
  KIND_GROUP,
  KIND_HINT,
  KIND_TONE,
  groupWorkspaces,
  type Workspace,
} from "../lib/workspaces";
import { Badge } from "./kit";
import styles from "./shell.module.css";
import { usePopover } from "./use-popover";

const ROLE: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  learner: "Learner",
};

export function initialsOf(access: ConsoleAccess) {
  const source = access.displayName || access.email || "?";
  return (
    source
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => Array.from(part)[0])
      .join("")
      .toUpperCase() || "?"
  );
}

export function personName(access: ConsoleAccess) {
  return (
    access.displayName ||
    access.email ||
    (access.state === "preview" ? "Local preview" : "Your account")
  );
}

/** The rail's second line: just the role, so the narrow rail never cuts it. */
export function shortRole(access: ConsoleAccess) {
  if (access.state === "preview") return "Local preview";
  if (access.state !== "verified") return "Session not confirmed";
  return access.role ? (ROLE[access.role] ?? access.role) : "Signed in";
}

/** "Owner · AC Operations · platform access": what this person can do here. */
export function roleLine(access: ConsoleAccess) {
  if (access.state === "preview") return "No session in this preview";
  if (access.state !== "verified") return "Session not confirmed";
  const parts = [
    access.role ? `${ROLE[access.role] ?? access.role} · AC Operations` : null,
    access.platform.length ? "platform access" : null,
  ].filter(Boolean);
  return parts.join(" · ") || "Signed in";
}

function counts(item: Workspace) {
  const people = `${item.members} ${item.members === 1 ? "person" : "people"}`;
  if (item.kind === "operations") return `${people} · no calls`;
  return `${people} · ${item.calls.toLocaleString("en-IN")} ${
    item.calls === 1 ? "call" : "calls"
  }`;
}

export function AccountMenu({
  access,
  workspaces,
}: {
  access: ConsoleAccess;
  workspaces: readonly Workspace[] | null;
}) {
  const {
    open,
    toggle,
    close: closeMenu,
    panelId,
    box,
    trigger,
  } = usePopover();

  const groups = workspaces ? groupWorkspaces(workspaces) : [];

  return (
    <div className={styles.person} ref={box}>
      <button
        type="button"
        ref={trigger}
        className={styles.personButton}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Signed in as ${personName(access)}. Organisations and accounts`}
        title={access.email ?? undefined}
        onClick={toggle}
      >
        <span className={styles.avatar} aria-hidden="true">
          {initialsOf(access)}
        </span>
        <span className={styles.accountText}>
          <strong>{personName(access)}</strong>
          <small>{shortRole(access)}</small>
        </span>
        <ChevronsUpDown
          size={14}
          aria-hidden="true"
          className={styles.personChevron}
        />
      </button>

      <div
        id={panelId}
        className={styles.personPanel}
        hidden={!open}
        role="region"
        aria-label="Signed-in person and workspaces"
      >
        <div className={styles.personHead}>
          <span className={styles.avatar} aria-hidden="true">
            {initialsOf(access)}
          </span>
          <span className={styles.accountText}>
            <strong>{personName(access)}</strong>
            <small>{access.email ?? roleLine(access)}</small>
            {access.email ? <small>{roleLine(access)}</small> : null}
          </span>
        </div>

        {groups.length ? (
          <div className={styles.personGroups}>
            <p className={styles.personTitle}>Organisations and accounts</p>
            {groups.map((group) => (
              <section
                key={group.kind}
                className={styles.personGroup}
                aria-label={KIND_GROUP[group.kind]}
              >
                <p className={styles.groupLabel}>
                  {KIND_GROUP[group.kind]}
                  <span className={styles.personCount}>
                    {group.items.length}
                  </span>
                </p>
                {group.items.map((item) => {
                  const body = (
                    <>
                      <span className={styles.workspaceName}>
                        <strong>{item.name}</strong>
                        <Badge tone={KIND_TONE[item.kind]}>
                          {KIND_BADGE[item.kind]}
                        </Badge>
                      </span>
                      <small>
                        {counts(item)}
                        {item.status !== "active" ? ` · ${item.status}` : ""}
                      </small>
                      {item.name !== item.registeredName ? (
                        <small title="The name in the registry">
                          Registered as “{item.registeredName}”
                        </small>
                      ) : null}
                    </>
                  );
                  return item.kind === "operations" ? (
                    <div
                      key={item.id}
                      className={styles.workspaceRow}
                      title={KIND_HINT[item.kind]}
                    >
                      {body}
                    </div>
                  ) : (
                    <Link
                      key={item.id}
                      href={`/calls?organisation=${encodeURIComponent(item.id)}`}
                      className={styles.workspaceRow}
                      title={`${KIND_HINT[item.kind]}. Open its calls`}
                      prefetch={false}
                      onClick={closeMenu}
                    >
                      {body}
                    </Link>
                  );
                })}
              </section>
            ))}
          </div>
        ) : null}

        {workspaces ? (
          <Link
            href="/platform/organisations"
            className={styles.personFoot}
            prefetch={false}
            onClick={closeMenu}
          >
            <Settings2 size={14} aria-hidden="true" />
            Manage organisations and members
          </Link>
        ) : null}
      </div>
    </div>
  );
}
