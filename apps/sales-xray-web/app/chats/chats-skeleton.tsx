/**
 * The Chats screen's outline while it opens, light enough for the app's root
 * loading screen (design system v2, 20 Oct): only the kit, styles and the
 * shell, never the Chats page, its API client or the Lead Desk.
 */

import { MessagesSquare } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { Skeleton } from "../ui/kit";
import styles from "./chats.module.css";
import switchStyles from "./leads-chats-switch.module.css";

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

export function FiltersSkeleton() {
  return (
    <div className={styles.filters} aria-hidden="true">
      <span className={styles.search} data-placeholder />
      <div className={styles.chips}>
        <Skeleton width={84} height={28} />
        <Skeleton width={96} height={28} />
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
          <Skeleton width={40} height={40} />
          <span>
            <Skeleton width="58%" height={13} />
            <Skeleton width="86%" height={12} />
            <Skeleton width="40%" height={10} />
          </span>
        </div>
      ))}
    </div>
  );
}

/** Phones: the Leads | Chats switch as it will stand, before the counts. */
function SwitchOutline() {
  return (
    <div className={styles.switchSlot}>
      <nav className={switchStyles.switch} aria-label="Leads or chats">
        <Link href="/leads" prefetch={false}>
          Leads
        </Link>
        <Link href="/chats" prefetch={false} aria-current="page">
          Chats
        </Link>
      </nav>
    </div>
  );
}

export function ChatsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="chats" mobileFit>
      <ChatsFrame
        open={false}
        list={
          <>
            <SwitchOutline />
            <FiltersSkeleton />
            <ThreadListSkeleton />
          </>
        }
        thread={<PickHint />}
      />
    </AcquisitionShell>
  );
}
