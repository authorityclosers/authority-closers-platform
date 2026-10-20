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

import { PhoneCall } from "lucide-react";
import { useSyncExternalStore } from "react";

import { useUnreadChats } from "../chats/chats-badge";
import { readBadge, type Badge } from "./leads-client";
import styles from "./leads.module.css";

const EVERY_MS = 2 * 60 * 1000;
const AGAIN_MS = 20 * 1000;

let current: Badge | null = null;
let readAt = 0;
let timer: number | null = null;
let reading = false;
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
  if (reading || document.visibilityState !== "visible") return;
  if (!force && Date.now() - readAt < AGAIN_MS) return;
  reading = true;
  readAt = Date.now();
  void readBadge()
    .then(emit)
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

/** The Leads icon with its badge, for the rail and the phone tab bar. */
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
  const latest = useSyncExternalStore(
    live ? subscribe : idle,
    snapshot,
    serverSnapshot,
  );
  const badge = live ? latest : null;
  const unread = useUnreadChats(live && withChats);
  const late = badge?.overdue ?? 0;
  const due = badge?.to_call ?? 0;
  // Late calls first (red); otherwise what waits: calls due and unread chats.
  const count = late || due + unread;
  return (
    <span className={styles.tabIcon}>
      <PhoneCall size={size} strokeWidth={strokeWidth} aria-hidden="true" />
      {count ? (
        <span className={styles.tabBadge} data-tone={late ? "bad" : "accent"}>
          <span aria-hidden="true">{count > 99 ? "99+" : count}</span>
          <span className={styles.srOnly}>
            {late
              ? `, ${late} late`
              : [
                  due ? `, ${due} to call` : "",
                  unread ? `, ${unread} unread chats` : "",
                ].join("")}
          </span>
        </span>
      ) : null}
    </span>
  );
}
