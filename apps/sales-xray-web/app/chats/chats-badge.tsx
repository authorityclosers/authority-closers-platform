"use client";

/**
 * The Chats tab's unread badge, for the rail and the phone tab bar: how many
 * conversations have a message this person hasn't opened yet. One shared
 * reader, like the Leads badge: it reads on open, when the app or tab comes
 * back to the front and every two minutes while shown, and only while the
 * shell says so (signed in, loaded, not under test). The Chats page hands
 * over each fresh list and every chat it opens, so the badge never lags it.
 */

import { MessagesSquare } from "lucide-react";
import { useMemo, useSyncExternalStore } from "react";

import { useWorkspaceAccess } from "../workspace-access";
import {
  isUnread,
  markSeen,
  readChats,
  readSeen,
  type ChatThread,
  type SeenMarks,
} from "./chats-client";
import styles from "./chats.module.css";

const EVERY_MS = 2 * 60 * 1000;
const AGAIN_MS = 20 * 1000;
const NONE: SeenMarks = {};

let current: ChatThread[] | null = null;
let seen: { personId: string; marks: SeenMarks } | null = null;
let readAt = 0;
let timer: number | null = null;
let reading = false;
const listeners = new Set<() => void>();
const seenListeners = new Set<() => void>();

const emit = () => listeners.forEach((listener) => listener());

/** The Chats page's own list, straight after it loads. */
export function publishChats(threads: ChatThread[]): void {
  readAt = Date.now();
  current = threads;
  emit();
}

/** This person's seen marks, read from the browser once and then kept here. */
function seenFor(personId: string | null): SeenMarks {
  if (!personId) return NONE;
  if (seen?.personId !== personId)
    seen = { personId, marks: readSeen(personId) };
  return seen.marks;
}

/** A chat was opened: its dot (and the badge) go at once. */
export function rememberSeen(
  personId: string,
  thread: Pick<ChatThread, "key" | "lastAt">,
): void {
  const before = seenFor(personId);
  const marks = markSeen(personId, before, thread);
  if (marks === before) return;
  seen = { personId, marks };
  seenListeners.forEach((listener) => listener());
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

function read(force = false) {
  if (reading || document.visibilityState !== "visible") return;
  if (!force && Date.now() - readAt < AGAIN_MS) return;
  reading = true;
  readAt = Date.now();
  void readChats()
    .then((list) => {
      current = list.threads;
      emit();
    })
    .catch(() => undefined)
    .finally(() => {
      reading = false;
    });
}

const onVisible = () => read();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    read(true);
    timer = window.setInterval(() => read(true), EVERY_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size) return;
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("focus", onVisible);
  };
}

const snapshot = () => current;
const serverSnapshot = () => null;
/** Not live: no reads, no timer, no listeners. */
const idle = () => () => undefined;

/** How many chats have unopened messages, for this person in this browser. */
export function useUnreadChats(live: boolean): number {
  const access = useWorkspaceAccess();
  const personId = live ? (access?.context?.personId ?? null) : null;
  const threads = useSyncExternalStore(
    live ? subscribe : idle,
    snapshot,
    serverSnapshot,
  );
  const marks = useSeenMarks(personId);
  return useMemo(
    () =>
      live && threads
        ? threads.filter((thread) => isUnread(thread, marks)).length
        : 0,
    [live, threads, marks],
  );
}

/** The Chats icon with its unread count, for the rail and the phone tab bar. */
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
