"use client";

/**
 * Home's reads and their health (persona QA, 31 Oct 2026: when /v1 failed, Home
 * sat on grey boxes for ever, with no error and no Retry).
 *
 * - Each read keeps its last good answer for the workspace: a read that fails
 *   shows what was there before, not grey boxes.
 * - After 8 s with a read still missing or failed, one calm corner card says
 *   so with Retry, which reads everything again; it goes once all is in.
 * - A workspace switch forgets every answer (workspace-change.ts).
 * - Offline, Home says so (useOnline) and the card stays quiet; back online,
 *   everything is read again (QA robot 331fa263, 1 Nov 2026).
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import { dismissNotice, notify } from "../notice-center";
import { onWorkspaceChange } from "../workspace-change";

type Health = "pending" | "ok" | "failed";

const kept = new Map<string, unknown>();
const health = new Map<string, Health>();
const listeners = new Set<() => void>();
let round = 0;
let version = 0;

function emit() {
  version += 1;
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

onWorkspaceChange(() => {
  kept.clear();
  health.clear();
  emit();
});

/** Read everything on Home again (the corner card's Retry). */
export function retryHome() {
  round += 1;
  emit();
}

/** Tests: start from nothing. */
export function resetHomeReads() {
  kept.clear();
  health.clear();
  round = 0;
  emit();
}

type Got<T> = { key: string; value: T | null; failed: boolean };

/** One of Home's reads: its answer (or the last good one) and whether it failed. */
export function useHomeRead<T>(
  key: string,
  read: (signal: AbortSignal) => Promise<T>,
): { value: T | null; failed: boolean } {
  const tick = useSyncExternalStore(
    subscribe,
    () => round,
    () => 0,
  );
  const [got, setGot] = useState<Got<T>>(() => ({
    key,
    value: (kept.get(key) as T | undefined) ?? null,
    failed: false,
  }));
  useEffect(() => {
    const controller = new AbortController();
    health.set(key, "pending");
    emit();
    read(controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return;
        kept.set(key, value);
        health.set(key, "ok");
        setGot({ key, value, failed: false });
        emit();
      },
      () => {
        if (controller.signal.aborted) return;
        health.set(key, "failed");
        setGot({
          key,
          value: (kept.get(key) as T | undefined) ?? null,
          failed: true,
        });
        emit();
      },
    );
    return () => {
      controller.abort();
      if (health.get(key) === "pending") health.delete(key);
    };
    // The read is the caller's inline function: the key says what it reads.
  }, [key, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  // Another key (a side or a period): its last good answer at once.
  return got.key === key
    ? { value: got.value, failed: got.failed }
    : { value: (kept.get(key) as T | undefined) ?? null, failed: false };
}

const NOTICE = "home-load";

/** The corner card: 8 s after Home (or Retry) asked, if anything is still
 *  missing or failed. */
function watchOnline(listener: () => void) {
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}

/** Whether the browser has a connection (it says so on "online" and "offline"). */
export function useOnline(): boolean {
  return useSyncExternalStore(
    watchOnline,
    () => navigator.onLine,
    () => true,
  );
}

export function HomeLoadWatch() {
  const online = useOnline();
  // Back online: read everything again.
  useEffect(() => {
    window.addEventListener("online", retryHome);
    return () => window.removeEventListener("online", retryHome);
  }, []);
  // Every change in a read's health draws this again.
  useSyncExternalStore(
    subscribe,
    () => version,
    () => 0,
  );
  const tick = useSyncExternalStore(
    subscribe,
    () => round,
    () => 0,
  );
  const [late, setLate] = useState<number | null>(null);
  useEffect(() => {
    const timer = window.setTimeout(() => setLate(tick), 8_000);
    return () => window.clearTimeout(timer);
  }, [tick]);
  const states = [...health.values()];
  // Offline, Home's own line says why; no "Couldn't load" card on top of it.
  const stuck =
    online &&
    late === tick &&
    states.some((state) => state === "failed" || state === "pending");
  useEffect(() => {
    if (!stuck) {
      dismissNotice(NOTICE);
      return;
    }
    notify({
      id: NOTICE,
      tone: "info",
      noReport: true,
      title: "Couldn't load",
      action: {
        label: "Retry",
        run: () => {
          dismissNotice(NOTICE);
          retryHome();
        },
      },
      onDismiss: async () => undefined,
    });
  }, [stuck]);
  useEffect(() => () => dismissNotice(NOTICE), []);
  return null;
}
