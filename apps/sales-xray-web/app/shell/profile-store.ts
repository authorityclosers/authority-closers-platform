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
// Your last profile, by person: a workspace switch keeps your own face and
// name in the frame while the new workspace's read is on its way (owner bugs
// #17 and #50: no blank circle before, during or after a switch).
let face: { personId: string; profile: AccountProfileRecord } | null = null;

/** Forget the read, for another workspace's or account's to come. */
function forgetRead() {
  owner = null;
  pending = null;
  updateShellState({ profileName: null });
}

/** Signed out, or the profile changed: forget it all, your face too. */
export function invalidateShellProfile() {
  forgetRead();
  face = null;
}

/** A document-local, account/session/workspace-bound read survives component unmounts. */
export function readShellProfile(key: string): Promise<AccountProfileRecord> {
  // Another workspace: a new read, while your face stays on screen.
  if (owner !== key) forgetRead();
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

/**
 * `keepFace`: until this workspace's read answers, the frame's avatar and
 * name show the same person's last profile instead of nothing.
 */
export function useShellProfile(
  authenticated: boolean,
  enabled = true,
  keepFace = false,
) {
  const access = useWorkspaceAccess();
  const context = access?.context;
  const personId = context?.personId ?? null;
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
          if (personId && owner === key) face = { personId, profile };
          if (active && current === generation) setValue({ key, profile });
        })
        .catch(() => {
          if (active && current === generation) setValue(null);
        });
    };
    refresh();
    window.addEventListener(PROFILE_UPDATED_EVENT, refresh);
    return () => {
      active = false;
      window.removeEventListener(PROFILE_UPDATED_EVENT, refresh);
    };
  }, [signedIn, signedOut, enabled, key, personId]);
  if (!signedIn) return null;
  if (value?.key === key) return value.profile;
  return keepFace && personId && face?.personId === personId
    ? face.profile
    : null;
}
