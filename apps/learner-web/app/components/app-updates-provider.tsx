"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createAppUpdatesApi,
  type AppUpdateFeed,
  type AppUpdatesApi,
} from "../lib/app-updates-api";
import { ApiError, isAbortError } from "../lib/learner-api";
import styles from "./notifications-runtime.module.css";

type UpdateState =
  | { status: "loading"; feed?: never }
  | { status: "ready"; feed: AppUpdateFeed }
  | { status: "error" | "signed_out" | "forbidden"; feed?: never };
type UpdatesContext = {
  state: UpdateState;
  pendingId: string | null;
  saveError: string | null;
  refresh: () => void;
  markRead: (id: string) => Promise<void>;
};
const Context = createContext<UpdatesContext | null>(null);
const defaultApi = createAppUpdatesApi();
const REQUEST_TIMEOUT = 12_000;
const failureState = (error: unknown): UpdateState => ({
  status:
    error instanceof ApiError && error.status === 401
      ? "signed_out"
      : error instanceof ApiError && error.status === 403
        ? "forbidden"
        : "error",
});

export function AppUpdatesProvider({
  children,
  api = defaultApi,
}: {
  children: ReactNode;
  api?: AppUpdatesApi;
}) {
  const [state, setState] = useState<UpdateState>({ status: "loading" });
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  const activeWrite = useRef<AbortController | null>(null);
  const writeSettled = useRef<Promise<void> | null>(null);
  const saving = useRef(false);
  const cancelActive = useCallback(() => {
    generation.current += 1;
    active.current?.abort();
  }, []);
  const load = useCallback(async () => {
    const epoch = ++generation.current;
    active.current?.abort();
    setState({ status: "loading" });
    // Returning to the tab must hide stale account data immediately, but must
    // not abort a read receipt or fetch the old count before it commits.
    if (writeSettled.current) await writeSettled.current;
    if (epoch !== generation.current) return;
    const controller = new AbortController();
    active.current = controller;
    setPendingId(null);
    setSaveError(null);
    setState({ status: "loading" });
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    try {
      const feed = await api.list(controller.signal);
      if (epoch === generation.current && !controller.signal.aborted)
        setState({ status: "ready", feed });
    } catch (error) {
      if (epoch === generation.current) setState(failureState(error));
    } finally {
      clearTimeout(timer);
    }
  }, [api]);

  useEffect(() => {
    // Async completion only; do not move private data into a module/global cache.
    const start = setTimeout(() => void load(), 0);
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    const onReturn = () => {
      if (document.visibilityState === "hidden" || refreshTimer !== null)
        return;
      cancelActive();
      setState({ status: "loading" });
      refreshTimer = setTimeout(() => {
        refreshTimer = null;
        void load();
      }, 0);
    };
    window.addEventListener("focus", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      clearTimeout(start);
      if (refreshTimer !== null) clearTimeout(refreshTimer);
      cancelActive();
      activeWrite.current?.abort();
      window.removeEventListener("focus", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [load, cancelActive]);

  async function markRead(id: string) {
    if (
      state.status !== "ready" ||
      saving.current ||
      !state.feed.items.some((item) => item.id === id && !item.read)
    )
      return;
    saving.current = true;
    setPendingId(id);
    setSaveError(null);
    const owner = state.feed;
    const epoch = ++generation.current;
    active.current?.abort();
    const controller = new AbortController();
    activeWrite.current = controller;
    let settleWrite!: () => void;
    const settlement = new Promise<void>((resolve) => {
      settleWrite = resolve;
    });
    writeSettled.current = settlement;
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    try {
      const feed = await api.markRead(id, controller.signal);
      if (epoch !== generation.current || controller.signal.aborted) return;
      if (
        feed.person_id !== owner.person_id ||
        feed.tenant_id !== owner.tenant_id
      ) {
        setState({ status: "signed_out" });
        return;
      }
      setState({ status: "ready", feed });
    } catch (error) {
      if (epoch !== generation.current) return;
      if (
        error instanceof ApiError &&
        (error.status === 401 || error.status === 403)
      )
        setState(failureState(error));
      else
        setSaveError(
          isAbortError(error)
            ? "Saving took too long. Refresh to check, or try again."
            : "Couldn’t confirm this as read. Try again.",
        );
    } finally {
      clearTimeout(timer);
      saving.current = false;
      if (writeSettled.current === settlement) writeSettled.current = null;
      if (activeWrite.current === controller) activeWrite.current = null;
      settleWrite();
      if (epoch === generation.current) {
        setPendingId(null);
      }
    }
  }
  return (
    <Context.Provider
      value={{
        state,
        pendingId,
        saveError,
        refresh: () => void load(),
        markRead,
      }}
    >
      {children}
    </Context.Provider>
  );
}

export function useAppUpdates() {
  return useContext(Context);
}

export function AppUpdateUnreadIndicator() {
  const updates = useAppUpdates();
  const count =
    updates?.state.status === "ready" ? updates.state.feed.unread_count : 0;
  return count > 0 ? (
    <span className={styles.unreadIndicator} aria-hidden="true">
      {count}
    </span>
  ) : null;
}
