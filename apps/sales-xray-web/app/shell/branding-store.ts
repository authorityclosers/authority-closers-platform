"use client";

import { useEffect, useSyncExternalStore } from "react";

import { useWorkspaceAccess } from "../workspace-access";

/** The selected workspace's name and logo, as every member may read them. */
export type Branding = {
  tenantId: string;
  name: string;
  logoUrl: string | null;
};

const UUID = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
const LOGO_PATH = /^\/v1\/organisation\/logo\/[\da-f-]{36}$/i;

/** Strict: anything unexpected reads as "no logo", never as a crash. */
export function parseBranding(value: unknown): Branding | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  if (typeof data.tenant_id !== "string" || !UUID.test(data.tenant_id))
    return null;
  const logo = data.logo_url;
  return {
    tenantId: data.tenant_id,
    name: typeof data.name === "string" ? data.name : "",
    logoUrl: typeof logo === "string" && LOGO_PATH.test(logo) ? logo : null,
  };
}

let current: { key: string; branding: Branding | null } | null = null;
let pendingKey: string | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());

async function readBranding(): Promise<Branding | null> {
  const response = await fetch("/v1/organisation/branding", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json" },
  });
  // An older server without the route: no logo, initials stay.
  if (response.status === 404 || response.status === 405) return null;
  if (!response.ok) throw new Error("branding_read_failed");
  return parseBranding(await response.json());
}

function load(key: string) {
  if (current?.key === key || pendingKey === key) return;
  pendingKey = key;
  readBranding()
    .then((branding) => {
      if (pendingKey !== key) return;
      current = { key, branding };
      notify();
    })
    // A failed read keeps initials; the next screen that needs it asks again.
    .catch(() => undefined)
    .finally(() => {
      if (pendingKey === key) pendingKey = null;
    });
}

type Context = { personId: string; sessionId: string; tenantId: string };

/** One read per account, session and workspace. */
export const brandingKey = (context: Context | null | undefined) =>
  context
    ? JSON.stringify([context.personId, context.sessionId, context.tenantId])
    : null;

/** After a logo change: every tile showing this workspace updates at once. */
export function updateBranding(key: string, branding: Branding) {
  // A read that started before the change would bring the old logo back.
  pendingKey = null;
  current = { key, branding };
  notify();
}

export function resetBrandingForTests() {
  current = null;
  pendingKey = null;
  notify();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/**
 * The selected workspace's branding once read; null until then or without
 * one. Personal workspaces have no logo, so callers can skip the read.
 */
export function useBranding(enabled = true): Branding | null {
  const context = useWorkspaceAccess()?.context;
  const key = enabled ? brandingKey(context) : null;
  const snapshot = useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
  useEffect(() => {
    if (key) load(key);
  }, [key]);
  if (!key || snapshot?.key !== key) return null;
  const branding = snapshot.branding;
  return branding && branding.tenantId === context?.tenantId ? branding : null;
}
