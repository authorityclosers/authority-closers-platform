"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { useWorkspaceAccess } from "../workspace-access";
import {
  readUpdates,
  readNotifications,
  markUpdatesSeen,
  markNotificationsRead,
  type UpdateNote,
  type UpdateNotification,
} from "./updates-client";

type UpdatesState = Readonly<{
  notes: UpdateNote[];
  unseen_count: number;
  notifications: UpdateNotification[];
  unread_count: number;
  status: "loading" | "ready" | "error";
}>;
const EMPTY: UpdatesState = {
  notes: [],
  unseen_count: 0,
  notifications: [],
  unread_count: 0,
  status: "loading",
};

/** Each account/session/workspace owns its requests, receipts and last successful lists. */
export function createUpdatesStore(isCurrent = () => true) {
  let state = EMPTY;
  let revision = 0;
  let pending: Promise<void> | null = null;
  const listeners = new Set<() => void>();
  const publish = (patch: Partial<UpdatesState>) => {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  };
  const refresh = (): Promise<void> => {
    if (pending) return pending;
    const generation = revision;
    const request = Promise.all([readUpdates(), readNotifications()])
      .then(([notes, notifications]) => {
        if (revision === generation)
          publish({ ...notes, ...notifications, status: "ready" });
      })
      .catch(() => {
        if (revision === generation) publish({ status: "error" });
      })
      .finally(() => {
        if (pending === request) pending = null;
      });
    pending = request;
    return request;
  };
  // Serialize receipts so earlier counts cannot overwrite a newer acknowledgement.
  let writes = Promise.resolve();
  const acknowledge = (write: () => Promise<void>) => {
    const request = writes.then(write);
    writes = request.catch(() => {});
    return request;
  };
  const markSeen = (keys: string[]) =>
    acknowledge(async () => {
      if (!keys.length) return;
      if (!isCurrent()) throw new Error("updates_session_changed");
      const receipt = await markUpdatesSeen(keys);
      if (!isCurrent()) return;
      revision++;
      pending = null;
      publish({
        ...receipt,
        notes: state.notes.map((note) =>
          keys.includes(note.key) ? { ...note, seen: true } : note,
        ),
      });
      await refresh();
    });
  const markRead = (ids: string[]) =>
    acknowledge(async () => {
      if (!ids.length) return;
      if (!isCurrent()) throw new Error("updates_session_changed");
      const receipt = await markNotificationsRead(ids);
      if (!isCurrent()) return;
      revision++;
      pending = null;
      publish({
        ...receipt,
        notifications: state.notifications.map((entry) =>
          ids.includes(entry.id) ? { ...entry, read: true } : entry,
        ),
      });
      await refresh();
    });
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    refresh,
    markSeen,
    markRead,
  };
}
let owner: string | null = null;
let shared = createUpdatesStore();
const subscribers = new Set<() => void>();
const notify = () => subscribers.forEach((listener) => listener());
let unsubscribe = shared.subscribe(notify);
function bindUpdatesStore(key: string | null) {
  if (key !== owner) {
    unsubscribe();
    owner = key;
    shared = createUpdatesStore(() => owner === key);
    unsubscribe = shared.subscribe(notify);
    notify();
  }
  return shared;
}
function subscribeUpdates(listener: () => void) {
  subscribers.add(listener);
  return () => {
    subscribers.delete(listener);
  };
}
export function useShellUpdates(authenticated = true, enabled = true) {
  const access = useWorkspaceAccess();
  const context = access?.context;
  const key =
    authenticated && access?.authenticated === true && context
      ? JSON.stringify([context.personId, context.sessionId, context.tenantId])
      : null;
  const state = useSyncExternalStore(
    subscribeUpdates,
    () => (key !== null && owner === key ? shared.getSnapshot() : EMPTY),
    () => EMPTY,
  );
  useEffect(() => {
    const store = bindUpdatesStore(key);
    if (!key || !enabled) return;
    void store.refresh();
    const refresh = () => {
      void store.refresh();
    };
    window.addEventListener("focus", refresh);
    const interval = window.setInterval(refresh, 5 * 60 * 1000);
    return () => {
      window.removeEventListener("focus", refresh);
      window.clearInterval(interval);
    };
  }, [key, enabled]);
  const actions = useMemo(
    () => ({
      markSeen: (keys: string[]) =>
        key !== null && owner === key
          ? shared.markSeen(keys)
          : Promise.reject(new Error("updates_session_changed")),
      markRead: (ids: string[]) =>
        key !== null && owner === key
          ? shared.markRead(ids)
          : Promise.reject(new Error("updates_session_changed")),
    }),
    [key],
  );
  return {
    ...state,
    ...actions,
  };
}
