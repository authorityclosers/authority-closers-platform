"use client";

/**
 * What the bell has just received, as a light notice: a report ready, a lead
 * given to you, a paused analysis, an invite, or what's new. Since 27 Oct
 * 2026 it is the top banner (ui/alerts.tsx, work that needs the seller), not
 * a corner card: the bottom corner is for app problems only, so the two never
 * share it (orchestrator for the owner). The banner leaves by itself and the
 * line stays unread in the bell, the full list. One banner at a time: the
 * newest event, once per event on this device.
 */

import { useEffect, useRef } from "react";

import { clearAlert, raiseAlert } from "../ui/alerts";
import {
  claimUpdateCard,
  eligibleEvents,
  eligibleUpdate,
} from "./update-card-rules";
import {
  isRelativeUpdateHref,
  parseNotifications,
  type UpdateNotification,
} from "./updates-client";
import type { useShellUpdates } from "./updates-store";

type Updates = ReturnType<typeof useShellUpdates>;

/** How long the banner stays; the bell keeps the line. */
export const ACTIVITY_BANNER_MS = 8_000;

const VERB: Record<UpdateNotification["kind"], string> = {
  report_ready: "Open report",
  lead_assigned: "Open lead",
  analysis_paused: "See why",
  invite_received: "Open invite",
  bug_solved: "Open",
  updates: "What's new",
};

const POPPED_KEY = "sx-activity-popped";
const popped = new Set<string>();

/** Whether this event's banner already showed here (this tab, or this session). */
function poppedBefore(id: string): boolean {
  if (popped.has(id)) return true;
  try {
    const kept = JSON.parse(
      window.sessionStorage.getItem(POPPED_KEY) ?? "[]",
    ) as unknown;
    return Array.isArray(kept) && kept.includes(id);
  } catch {
    return false;
  }
}

function rememberPopped(ids: readonly string[]) {
  ids.forEach((id) => popped.add(id));
  try {
    window.sessionStorage.setItem(
      POPPED_KEY,
      JSON.stringify([...popped].slice(-50)),
    );
  } catch {
    // A private window keeps nothing: memory still stops a second banner.
  }
}

/** The mounted bell's account and workspace, its way to open a line, and the
    banners it has up (to clear once read or gone). */
type Raiser = Readonly<{
  contextKey: string;
  openEvent: (href: string) => void;
  active: Set<string>;
}>;
let raiser: Raiser | null = null;

/** The newest of these lines not shown on this device yet; the others wait in
    the bell, and none of them pops later. */
function raiseNewest(to: Raiser, entries: readonly UpdateNotification[]) {
  const fresh = eligibleEvents(entries).filter(
    (event) => !poppedBefore(`${to.contextKey}:${event.id}`),
  );
  rememberPopped(fresh.map((event) => `${to.contextKey}:${event.id}`));
  const event = fresh[0];
  if (!event) return;
  const id = `event:${to.contextKey}:${event.id}`;
  to.active.add(id);
  const href = event.href;
  raiseAlert({
    id,
    level: "normal",
    title: event.title,
    message: event.body,
    timeout: ACTIVITY_BANNER_MS,
    ...(isRelativeUpdateHref(href)
      ? { action: { label: VERB[event.kind], run: () => to.openEvent(href) } }
      : {}),
  });
}

/**
 * Bell lines a page already holds before the bell's own first read, which
 * waits until the page is 3 s old: raised now by the bell's rules, so that read
 * finds them shown (QA robot 10572d93, 1 Nov 2026: Leads' "<name> is your lead
 * now" line arrived at 3.2 s and pushed Leads down 52 px). The entries are
 * /v1/notifications lines; anything that is not one raises nothing, and so does
 * a call before the shell's bell is ready.
 */
export function raiseNotificationLines(entries: unknown) {
  if (!raiser) return;
  let lines: UpdateNotification[];
  try {
    lines = parseNotifications({
      notifications: entries,
      unread_count: 0,
    }).notifications;
  } catch {
    return;
  }
  raiseNewest(raiser, lines);
}

export function UpdateNotices({
  updates,
  contextKey,
  openNews,
  openEvent,
}: {
  updates: Updates;
  contextKey: string | null;
  openNews: () => void;
  openEvent: (href: string) => void;
}) {
  const active = useRef(new Set<string>());
  useEffect(() => {
    const ids = active.current;
    return () => {
      ids.forEach(clearAlert);
      ids.clear();
    };
  }, [contextKey]);
  // Lines a page raises early share this bell's account, banners and memory.
  useEffect(() => {
    if (!contextKey) return;
    const mine: Raiser = { contextKey, openEvent, active: active.current };
    raiser = mine;
    return () => {
      if (raiser === mine) raiser = null;
    };
  }, [contextKey, openEvent]);

  useEffect(() => {
    if (!contextKey) return;
    const note = eligibleUpdate(updates.notes);
    let storage: Storage | null = null;
    try {
      storage = window.sessionStorage;
    } catch {}
    if (note && claimUpdateCard(storage)) {
      const id = `update:${contextKey}:${note.key}`;
      active.current.add(id);
      raiseAlert({
        id,
        level: "normal",
        title: note.title,
        message: note.items[0],
        action: { label: VERB.updates, run: openNews },
        timeout: ACTIVITY_BANNER_MS,
      });
    }
    raiseNewest(
      { contextKey, openEvent, active: active.current },
      updates.notifications,
    );
    for (const item of updates.notes.filter((n) => n.seen)) {
      const id = `update:${contextKey}:${item.key}`;
      clearAlert(id);
      active.current.delete(id);
    }
    for (const item of updates.notifications.filter((n) => n.read)) {
      const id = `event:${contextKey}:${item.id}`;
      clearAlert(id);
      active.current.delete(id);
    }
    // A line gone from the bell takes its banner too, as a read one does (QA
    // robot bbc3aca3, 1 Nov 2026: a lead given to someone else or deleted).
    // Only from a list that loaded: one that failed proves nothing gone.
    if (updates.notifications_status !== "ready") return;
    const listed = new Set(
      updates.notifications.map((item) => `event:${contextKey}:${item.id}`),
    );
    for (const id of [...active.current]) {
      if (!id.startsWith(`event:${contextKey}:`) || listed.has(id)) continue;
      clearAlert(id);
      active.current.delete(id);
    }
  }, [contextKey, updates, openNews, openEvent]);
  return null;
}
