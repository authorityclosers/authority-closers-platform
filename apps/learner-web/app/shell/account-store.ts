"use client";

import {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
} from "react";
import {
  createLearnerApi,
  type LearnerApi,
  type MeResponse,
} from "../lib/learner-api";

export type Account = {
  me: MeResponse | null;
  workspaceName: string | null;
  avatarUrl: string | null;
};
const empty: Account = { me: null, workspaceName: null, avatarUrl: null };
export const AccountContext = createContext<Account>(empty);
export const useReflexAccount = () => useContext(AccountContext);

/** One identity read per browser tab, retained across route changes and remounts. */
export function createAccountStore(
  api: Pick<LearnerApi, "me" | "profileAvatar"> = createLearnerApi(),
  fetcher: typeof fetch = (...args) => fetch(...args),
) {
  let value = empty;
  let pending: Promise<void> | undefined;
  const listeners = new Set<() => void>();
  const publish = (next: Account) => {
    value = next;
    listeners.forEach((listener) => listener());
  };
  return {
    getSnapshot: () => value,
    getServerSnapshot: () => empty,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    updateAvatar: (avatarUrl: string) => publish({ ...value, avatarUrl }),
    load: () =>
      (pending ??= (async () => {
        try {
          const me = await api.me();
          publish({
            me,
            avatarUrl: me.avatar?.deliveryUrl ?? null,
            workspaceName: null,
          });
          const [avatar, workspace] = await Promise.allSettled([
            api.profileAvatar(),
            fetcher("/v1/me/workspaces", {
              credentials: "same-origin",
              cache: "no-store",
              redirect: "error",
              headers: { accept: "application/json" },
            }).then(async (response) => {
              if (!response.ok) return null;
              const body = await response.json();
              if (
                body.person_id !== me.person_id ||
                !Array.isArray(body.workspaces) ||
                body.workspaces.length < 2
              )
                return null;
              const selected = body.workspaces.find(
                (item: { tenant_id?: unknown; name?: unknown }) =>
                  item?.tenant_id === me.selected_tenant_id,
              );
              return typeof selected?.name === "string" ? selected.name : null;
            }),
          ]);
          const photo =
            avatar.status === "fulfilled" &&
            avatar.value.avatar?.state === "ready"
              ? avatar.value.avatar.delivery_url
              : null;
          // A profile edit received during these reads wins over the earlier response.
          publish({
            ...value,
            avatarUrl:
              value.avatarUrl !== (me.avatar?.deliveryUrl ?? null)
                ? value.avatarUrl
                : (photo ?? value.avatarUrl),
            workspaceName:
              workspace.status === "fulfilled" ? workspace.value : null,
          });
        } catch {
          // The screen's own session recovery remains responsible for sign-in.
        }
      })()),
  };
}
const accountStore = createAccountStore();
export function useAccountStore(store = accountStore) {
  const account = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getServerSnapshot,
  );
  useEffect(() => {
    void store.load();
  }, [store]);
  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      if (
        detail &&
        typeof detail === "object" &&
        "deliveryUrl" in detail &&
        typeof detail.deliveryUrl === "string"
      )
        store.updateAvatar(detail.deliveryUrl);
    };
    window.addEventListener("ac-profile-avatar-updated", update);
    return () =>
      window.removeEventListener("ac-profile-avatar-updated", update);
  }, [store]);
  return account;
}
