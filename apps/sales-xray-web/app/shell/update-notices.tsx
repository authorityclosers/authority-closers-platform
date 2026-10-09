"use client";

import { useEffect, useRef } from "react";
import { dismissNotice, notify } from "../notice-center";
import {
  claimUpdateCard,
  eligibleEvents,
  eligibleUpdate,
} from "./update-card-rules";
import { isRelativeUpdateHref } from "./updates-client";
import type { useShellUpdates } from "./updates-store";

type Updates = ReturnType<typeof useShellUpdates>;

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
      ids.forEach(dismissNotice);
      ids.clear();
    };
  }, [contextKey]);

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
      notify({
        id,
        tone: "info",
        title: note.title,
        message: note.items[0],
        timeout: 0,
        action: { label: "What's new", run: openNews },
        onDismiss: () => updates.markSeen([note.key]),
      });
    }
    for (const event of eligibleEvents(updates.notifications)) {
      const id = `event:${contextKey}:${event.id}`;
      active.current.add(id);
      const href = event.href;
      notify({
        id,
        tone: "info",
        title: event.title,
        message: event.body,
        timeout: 0,
        ...(isRelativeUpdateHref(href)
          ? { action: { label: "Open", run: () => openEvent(href) } }
          : {}),
        onDismiss: () => updates.markRead([event.id]),
      });
    }
    for (const item of updates.notes.filter((n) => n.seen)) {
      const id = `update:${contextKey}:${item.key}`;
      dismissNotice(id);
      active.current.delete(id);
    }
    for (const item of updates.notifications.filter((n) => n.read)) {
      const id = `event:${contextKey}:${item.id}`;
      dismissNotice(id);
      active.current.delete(id);
    }
  }, [contextKey, updates, openNews, openEvent]);
  return null;
}
