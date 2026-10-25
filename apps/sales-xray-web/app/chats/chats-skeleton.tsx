"use client";

/**
 * The Chats screen's outline while it opens, light enough for the app's root
 * loading screen (design system v2, 20 Oct): only the kit, styles, the shell
 * and the session, never the Chats page, its API client or the Lead Desk.
 */

import { can } from "../organisation/roles";
import { MessagesSquare } from "lucide-react";
import type { ReactNode } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { Skeleton, SkeletonRow } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./chats.module.css";

/** The list beside the open chat (and, on wide screens, the lead). */
export function ChatsFrame({
  list,
  thread,
  open,
  panel,
}: {
  list: ReactNode;
  thread: ReactNode;
  open: boolean;
  /** The lead beside the chat (computers only; phones use a sheet). */
  panel?: ReactNode;
}) {
  return (
    <div
      className={styles.root}
      data-open={open ? "thread" : "list"}
      data-panel={panel ? "open" : undefined}
    >
      <aside className={styles.listPane} aria-label="Chats list">
        {list}
      </aside>
      <div className={styles.threadPane}>{thread}</div>
      {panel ? (
        <aside className={styles.panelPane} aria-label="Lead">
          {panel}
        </aside>
      ) : null}
    </div>
  );
}

export function PickHint() {
  return (
    <div className={styles.pickHint}>
      <span className={styles.emptyMark} aria-hidden="true">
        <MessagesSquare size={20} />
      </span>
      <p className={styles.emptyTitle}>Pick a chat</p>
      <p className={styles.emptyText}>
        WhatsApp, Messenger and Instagram, all in one place. Chats waiting for a
        reply are at the top.
      </p>
    </div>
  );
}

/**
 * Owners and admins sort chats by whose they are (Mine / Unassigned / All).
 * The session knows the role at the first paint, so that row is drawn from
 * the start instead of appearing later and pushing the list down
 * (orchestrator's pane pass, 20 Oct). Null while the session loads.
 */
export function useManagesChats(): boolean | null {
  const access = useWorkspaceAccess();
  const tenantId = access?.context?.tenantId;
  if (!tenantId || !access?.workspaces) return null;
  const role = access.workspaces.find(
    (workspace) => workspace.tenant_id === tenantId,
  )?.role;
  return can(role, "leads.manage");
}

/** The filter row as it stands (Liquid Glass polish, 22 Oct 2026): Name, whose
 * chats (managers), Waiting, and the channel, at their own sizes at 390 px. */
export function FiltersSkeleton({ scopes = false }: { scopes?: boolean }) {
  return (
    <div className={styles.filters} aria-hidden="true">
      <div className={styles.filterRow}>
        <Skeleton width={81} height={36} radius="pill" />
        {scopes ? <Skeleton width={143} height={34} radius="pill" /> : null}
        <Skeleton width={102} height={36} radius="pill" />
        <Skeleton width={125} height={34} radius="pill" />
      </div>
    </div>
  );
}

/** Same rows, same heights: the list keeps its place while it loads. */
export function ThreadListSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className={styles.listBody} aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className={styles.rowSkeleton}>
          <SkeletonRow avatar={40} lines={3} />
        </div>
      ))}
    </div>
  );
}

export function ChatsSkeleton() {
  // Unknown yet: keep the row's place (most who open Chats on a team manage it).
  const manages = useManagesChats();
  return (
    <AcquisitionShell authenticated={false} loading active="chats" mobileFit>
      <ChatsFrame
        open={false}
        list={
          <>
            <FiltersSkeleton scopes={manages !== false} />
            <ThreadListSkeleton />
          </>
        }
        thread={<PickHint />}
      />
    </AcquisitionShell>
  );
}
