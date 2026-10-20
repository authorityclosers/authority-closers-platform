"use client";

/**
 * Unread chats: how many conversations have a message this person hasn't
 * opened yet, for the desktop rail's Chats icon and the phone's Leads tab
 * (owner, 20 Oct: five phone tabs, Chats inside Leads). The list comes from
 * the one shared reader (chats-store.ts) with the server's unread counts (read
 * marks, every device); this browser's marks only bridge the moments between
 * reading a chat and the server's next count.
 */

import { MessagesSquare } from "lucide-react";
import { useMemo, useSyncExternalStore } from "react";

import { useWorkspaceAccess } from "../workspace-access";
import {
  isUnread,
  markRead,
  markSeen,
  readSeen,
  type ChatThread,
  type SeenMarks,
} from "./chats-client";
import styles from "./chats.module.css";
import { useChats } from "./chats-store";

const NONE: SeenMarks = {};

let seen: { personId: string; marks: SeenMarks } | null = null;
const seenListeners = new Set<() => void>();

/** This person's seen marks, read from the browser once and then kept here. */
function seenFor(personId: string | null): SeenMarks {
  if (!personId) return NONE;
  if (seen?.personId !== personId)
    seen = { personId, marks: readSeen(personId) };
  return seen.marks;
}

// The newest mark sent to the server per chat, so a chat is marked once per message.
const posted = new Map<string, string>();

/**
 * A chat was read up to `readTo`, the newest message on screen: its dot (and
 * the badge) go at once here, and the server keeps the mark for every device.
 */
export function rememberSeen(
  personId: string,
  thread: Pick<
    ChatThread,
    "key" | "lastAt" | "channel" | "leadId" | "accountId" | "unread"
  >,
  readTo: string = thread.lastAt,
  accountId: string | null = thread.accountId ?? null,
): void {
  const before = seenFor(personId);
  const marks = markSeen(personId, before, { key: thread.key, lastAt: readTo });
  if (marks !== before) {
    seen = { personId, marks };
    seenListeners.forEach((listener) => listener());
  }
  // A server without read marks sends no count; nothing to tell it then.
  const sent = posted.get(`${personId}:${thread.key}`);
  if (typeof thread.unread !== "number" || (sent && sent >= readTo)) return;
  posted.set(`${personId}:${thread.key}`, readTo);
  markRead({ ...thread, accountId }, readTo).catch(() =>
    posted.delete(`${personId}:${thread.key}`),
  );
}

function followSeen(listener: () => void): () => void {
  seenListeners.add(listener);
  return () => {
    seenListeners.delete(listener);
  };
}

/** The chats this person has opened, up to which message (this browser). */
export function useSeenMarks(personId: string | null): SeenMarks {
  return useSyncExternalStore(
    followSeen,
    () => seenFor(personId),
    () => NONE,
  );
}

/** How many chats have unopened messages, for this person in this browser. */
export function useUnreadChats(live: boolean): number {
  const access = useWorkspaceAccess();
  const personId = live ? (access?.context?.personId ?? null) : null;
  const { list } = useChats({ live });
  const marks = useSeenMarks(personId);
  return useMemo(
    () =>
      live && list
        ? list.threads.filter((thread) => isUnread(thread, marks)).length
        : 0,
    [live, list, marks],
  );
}

/** The Chats icon with its unread count, for the desktop rail. */
export function ChatsTabIcon({
  size = 20,
  strokeWidth,
  live,
}: {
  size?: number;
  strokeWidth?: number;
  /** Signed in, loaded and not under test; otherwise no badge and no read. */
  live: boolean;
}) {
  const count = useUnreadChats(live);
  return (
    <span className={styles.tabIcon}>
      <MessagesSquare
        size={size}
        strokeWidth={strokeWidth}
        aria-hidden="true"
      />
      {count ? (
        <span className={styles.tabBadge}>
          <span aria-hidden="true">{count > 99 ? "99+" : count}</span>
          <span className={styles.srOnly}>{`, ${count} unread`}</span>
        </span>
      ) : null}
    </span>
  );
}
