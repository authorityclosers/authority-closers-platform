"use client";

import { useEffect, useSyncExternalStore } from "react";

import {
  readPendingInvites,
  type PendingInvite,
} from "../organisation/organisation-api";
import { useWorkspaceAccess } from "../workspace-access";

/**
 * Invitations waiting for the signed-in person, read once per account and
 * session. `live` is false where the server has no invitations yet, so
 * nothing that depends on them (joining, creating) is offered there.
 */
export type InvitesState = {
  ready: boolean;
  live: boolean;
  invites: readonly PendingInvite[];
};

type Snapshot = { key: string; invites: PendingInvite[] | null };

let current: Snapshot | null = null;
let pendingKey: string | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

function load(key: string, force = false) {
  if (!force && (current?.key === key || pendingKey === key)) return;
  pendingKey = key;
  readPendingInvites()
    .then((invites) => {
      if (pendingKey !== key) return;
      current = { key, invites };
      emit();
    })
    // A failed read offers nothing new; the next page load asks again.
    .catch(() => undefined)
    .finally(() => {
      if (pendingKey === key) pendingKey = null;
    });
}

type Context = { personId: string; sessionId: string };

export const invitesKey = (context: Context | null | undefined) =>
  context ? JSON.stringify([context.personId, context.sessionId]) : null;

/** Read again, e.g. after an answer said an invitation is no longer open. */
export function refreshInvites() {
  if (current) load(current.key, true);
}

/** An accepted invitation leaves the list at once. */
export function dropInvite(inviteId: string) {
  if (!current?.invites) return;
  current = {
    ...current,
    invites: current.invites.filter((invite) => invite.inviteId !== inviteId),
  };
  emit();
}

export function resetInvitesForTests() {
  current = null;
  pendingKey = null;
  emit();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

const NONE: InvitesState = { ready: false, live: false, invites: [] };

export function useInvites(enabled = true): InvitesState {
  const context = useWorkspaceAccess()?.context;
  const key = enabled ? invitesKey(context) : null;
  const snapshot = useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
  useEffect(() => {
    if (key) load(key);
  }, [key]);
  if (!key || snapshot?.key !== key) return NONE;
  return {
    ready: true,
    live: snapshot.invites !== null,
    invites: snapshot.invites ?? [],
  };
}
