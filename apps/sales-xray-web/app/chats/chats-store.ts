"use client";

/**
 * One reader of the chats list for the whole app (orchestrator's dev pass,
 * 20 Oct: the list was read in bursts and every 2-3 s per tab, on a busy
 * server). The Chats page, the desk card and the tab badges all read from
 * here, so there is never more than one read in flight:
 *
 * - every 15 s while a Chats screen is open and the tab is in view,
 *   every 2 minutes while only a badge shows;
 * - nothing while the tab is hidden; once on coming back or on focus, at most
 *   every 5 s;
 * - at once after a send (`refreshChats({ force: true })`).
 */

import { useEffect, useSyncExternalStore } from "react";

import { LeadsError } from "../leads/leads-client";
import { onWorkspaceChange, workspaceGeneration } from "../workspace-change";
import { readChats, type ChatList } from "./chats-client";

export const PAGE_EVERY_MS = 15 * 1000;
export const BADGE_EVERY_MS = 2 * 60 * 1000;
export const MIN_GAP_MS = 5 * 1000;

export type ChatsState = {
  list: ChatList | null;
  error: LeadsError | null;
  /** Bumped by every finished read, so screens can tell a new answer. */
  version: number;
};

let state: ChatsState = { list: null, error: null, version: 0 };
let inflight: Promise<void> | null = null;
let readAt = 0;
let timer: number | null = null;
let screens = 0;
// A 403 (Leads works only inside an organisation): the timer stops reading
// until the app comes back to the front or the workspace changes (Lead OS,
// 27 Oct 2026).
let forbidden = false;
const listeners = new Set<() => void>();

const emit = () => listeners.forEach((listener) => listener());
const visible = () =>
  typeof document === "undefined" || document.visibilityState === "visible";

/** Read the list now, unless a read is running or one finished moments ago. */
export function refreshChats({ force = false } = {}): Promise<void> {
  if (inflight) return inflight;
  if (!force && Date.now() - readAt < MIN_GAP_MS) return Promise.resolve();
  readAt = Date.now();
  // An answer for a workspace the page has left is dropped (owner bug #17).
  const asked = workspaceGeneration();
  const request = readChats()
    .then((list) => {
      if (asked !== workspaceGeneration()) return;
      state = { list, error: null, version: state.version + 1 };
    })
    .catch((reason: unknown) => {
      if (asked !== workspaceGeneration()) return;
      if (reason instanceof LeadsError && reason.status === 403)
        forbidden = true;
      state = {
        ...state,
        error:
          reason instanceof LeadsError
            ? reason
            : new LeadsError("Your chats didn't load. Try again.", 0),
        version: state.version + 1,
      };
    })
    .finally(() => {
      if (inflight === request) inflight = null;
      if (asked !== workspaceGeneration()) return;
      readAt = Date.now();
      emit();
    });
  inflight = request;
  return request;
}

// The workspace changed in place: the list was the old workspace's.
onWorkspaceChange((reread) => {
  state = { list: null, error: null, version: state.version + 1 };
  inflight = null;
  readAt = 0;
  forbidden = false;
  emit();
  if (reread && listeners.size) void refreshChats({ force: true });
});

function schedule() {
  if (timer !== null) window.clearTimeout(timer);
  timer = null;
  if (!listeners.size) return;
  timer = window.setTimeout(
    () => {
      if (visible() && !forbidden) void refreshChats({ force: true });
      schedule();
    },
    screens > 0 ? PAGE_EVERY_MS : BADGE_EVERY_MS,
  );
}

const onBack = () => {
  if (!visible()) return;
  forbidden = false;
  void refreshChats();
};

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    if (!state.list || Date.now() - readAt > PAGE_EVERY_MS) void refreshChats();
    schedule();
    document.addEventListener("visibilitychange", onBack);
    window.addEventListener("focus", onBack);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size) return;
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
    document.removeEventListener("visibilitychange", onBack);
    window.removeEventListener("focus", onBack);
  };
}

const snapshot = () => state;
const serverSnapshot = (): ChatsState => ({
  list: null,
  error: null,
  version: 0,
});
const SERVER = serverSnapshot();
const idle = () => () => undefined;

/**
 * The shared list. `screen` marks a Chats screen (15 s); badges leave it off
 * (2 minutes). `live` false reads nothing (signed out, loading, under test).
 */
export function useChats({
  live,
  screen = false,
}: {
  live: boolean;
  screen?: boolean;
}): ChatsState {
  useEffect(() => {
    if (!live || !screen) return;
    screens += 1;
    schedule();
    return () => {
      screens -= 1;
      schedule();
    };
  }, [live, screen]);
  return useSyncExternalStore(live ? subscribe : idle, snapshot, () => SERVER);
}

/** For tests: forget everything read so far. */
export function resetChatsStore(): void {
  if (timer !== null) window.clearTimeout(timer);
  timer = null;
  state = { list: null, error: null, version: 0 };
  inflight = null;
  readAt = 0;
  screens = 0;
  forbidden = false;
}
