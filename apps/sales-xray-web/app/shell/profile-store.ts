"use client";

import { useEffect, useState } from "react";
import {
  readAccountProfile,
  type AccountProfileRecord,
} from "../account-profile-client";
import { useWorkspaceAccess } from "../workspace-access";
import { updateShellState } from "./shell-store";

export const PROFILE_UPDATED_EVENT = "sales-xray:profile-updated";
let owner: string | null = null;
let pending: Promise<AccountProfileRecord> | null = null;

export function invalidateShellProfile() {
  owner = null;
  pending = null;
  updateShellState({ profileName: null });
}

/** A document-local, account/session/workspace-bound read survives component unmounts. */
export function readShellProfile(key: string): Promise<AccountProfileRecord> {
  if (owner !== key) invalidateShellProfile();
  owner = key;
  if (pending) return pending;
  const request = readAccountProfile()
    .then((profile) => {
      if (pending !== request) throw new Error("profile_read_superseded");
      updateShellState({ profileName: profile.name?.trim() || null });
      return profile;
    })
    .catch((error: unknown) => {
      if (pending === request) pending = null;
      throw error;
    });
  pending = request;
  return request;
}

export function useShellProfile(authenticated: boolean, enabled = true) {
  const access = useWorkspaceAccess();
  const context = access?.context;
  const key = context
    ? JSON.stringify([context.personId, context.sessionId, context.tenantId])
    : "document";
  const signedIn = authenticated && (!access || access.authenticated === true);
  const signedOut = access ? access.authenticated === false : !authenticated;
  const [value, setValue] = useState<{
    key: string;
    profile: AccountProfileRecord;
  } | null>(null);
  useEffect(() => {
    if (!signedIn) {
      if (signedOut) invalidateShellProfile();
      return;
    }
    if (!enabled) return;
    let active = true;
    let generation = 0;
    const refresh = () => {
      const current = ++generation;
      void readShellProfile(key)
        .then((profile) => {
          if (active && current === generation) setValue({ key, profile });
        })
        .catch(() => {
          if (active && current === generation) setValue(null);
        });
    };
    if (access?.profile === undefined) refresh();
    window.addEventListener(PROFILE_UPDATED_EVENT, refresh);
    return () => {
      active = false;
      window.removeEventListener(PROFILE_UPDATED_EVENT, refresh);
    };
  }, [signedIn, signedOut, enabled, key, access?.profile]);
  return signedIn
    ? value?.key === key
      ? value.profile
      : (access?.profile ?? null)
    : null;
}
