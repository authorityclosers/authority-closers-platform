"use client";

/**
 * The Leads tab's badge (UX study item 3): red with the count of calls more
 * than an hour late, or teal with the count due now when none is late. One
 * shared reader serves the rail and the phone tab bar: it reads on open, when
 * the app or tab comes back to the front, and every two minutes while shown.
 * The Leads page also hands over its fresh counts, so the badge never lags it.
 * It reads only while the shell says so: signed in, loaded and not under test,
 * so a signed-out visitor never sends a read (pages count their reads).
 */

import { Contact } from "lucide-react";
import { useSyncExternalStore } from "react";

import { useUnreadChats } from "../chats/chats-badge";
import { onWorkspaceChange, workspaceGeneration } from "../workspace-change";
import { readBadge, type Badge } from "./badge-client";
import styles from "./leads-badge.module.css";

const EVERY_MS = 2 * 60 * 1000;
const AGAIN_MS = 20 * 1000;

let current: Badge | null = null;
let readAt = 0;
let timer: number | null = null;
let reading = false;
// "Off" where Leads doesn't apply (a 403 outside an organisation): no more
// reads until the app comes back to the front or the workspace changes.
let off = false;
const listeners = new Set<() => void>();

function emit(next: Badge | null) {
  if (next?.overdue === current?.overdue && next?.to_call === current?.to_call)
    return;
  current = next;
  listeners.forEach((listener) => listener());
}

/** The Leads page's own counts, straight after it loads. */
export function publishBadge(next: Badge): void {
  readAt = Date.now();
  emit(next);
}

function read(force = false) {
  if (off || reading || document.visibilityState !== "visible") return;
  if (!force && Date.now() - readAt < AGAIN_MS) return;
  reading = true;
  readAt = Date.now();
  // Counts for a workspace the page has left are dropped (owner bug #17).
  const asked = workspaceGeneration();
  void readBadge()
    .then((next) => {
      if (asked !== workspaceGeneration()) return;
      if (next === "off") {
        off = true;
        emit(null);
      } else emit(next);
    })
    .finally(() => {
      if (asked === workspaceGeneration()) reading = false;
    });
}

// The workspace changed in place: these counts were the old workspace's.
onWorkspaceChange((reread) => {
  reading = false;
  readAt = 0;
  off = false;
  emit(null);
  if (reread && listeners.size) read(true);
});

const onVisible = () => {
  off = false;
  read();
};

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

/** The counts the badge shows: late calls, else calls due and unread chats. */
function useLeadsCounts(live: boolean, withChats: boolean) {
  const latest = useSyncExternalStore(
    live ? subscribe : idle,
    snapshot,
    serverSnapshot,
  );
  const badge = live ? latest : null;
  const unread = useUnreadChats(live && withChats);
  const late = badge?.overdue ?? 0;
  const due = badge?.to_call ?? 0;
  return { late, due, unread, count: late || due + unread };
}

/**
 * What the badge says, for its link's name after the label ("Leads, 3 late"):
 * a screen reader hears the place first, then what waits there (the test
 * robot, 31 Oct 2026: it said "3, 3 late Leads"). The badge itself is hidden.
 */
export function useLeadsBadgeWords(live: boolean, withChats = false): string {
  const { late, due, unread } = useLeadsCounts(live, withChats);
  if (late) return `, ${late} late`;
  return [
    due ? `, ${due} to call` : "",
    unread ? `, ${unread} unread chats` : "",
  ].join("");
}

/** The Leads icon with its badge, for the rail and the phone tab bar; its
    link carries the words (useLeadsBadgeWords). */
export function LeadsTabIcon({
  size = 20,
  strokeWidth,
  live,
  withChats = false,
}: {
  size?: number;
  strokeWidth?: number;
  /** Signed in, loaded and not under test; otherwise no badge and no read. */
  live: boolean;
  /** Phones: Chats lives inside Leads, so unread chats count here too. */
  withChats?: boolean;
}) {
  // Late calls first (red); otherwise what waits: calls due and unread chats.
  const { late, count } = useLeadsCounts(live, withChats);
  return (
    <span className={styles.tabIcon}>
      <Contact size={size} strokeWidth={strokeWidth} aria-hidden="true" />
      {count ? (
        <span
          className={styles.tabBadge}
          data-tone={late ? "bad" : "accent"}
          aria-hidden="true"
        >
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </span>
  );
}
