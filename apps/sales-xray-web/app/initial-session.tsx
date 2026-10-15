"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { InitialSession } from "./server-reads";

/**
 * The session the server read for this document (dev: the internal API
 * origin), handed from the root layout to the app session without changing
 * the session wrapper's own contract.
 */
const InitialSessionContext = createContext<InitialSession | null>(null);

export function InitialSessionProvider({
  value,
  children,
}: {
  value: InitialSession | null;
  children: ReactNode;
}) {
  return (
    <InitialSessionContext.Provider value={value}>
      {children}
    </InitialSessionContext.Provider>
  );
}

/**
 * Pages that render their data on the server start from the server's
 * session instead of the browser's check (other pages keep the check).
 */
export const SERVER_RENDERED = new Set([
  "/dashboard",
  "/analysis/calls",
  "/organisation",
  // Coaching reads its data on the server itself (coaching-server.ts).
  "/coaching",
]);

/**
 * Server-read page data is for the first moments of this document: a page
 * that mounts again later (for example after signing in again in place)
 * reads in the browser.
 */
export const SEED_WINDOW_MS = 60_000;

// When this document's JavaScript started (this module loads with the page).
const DOCUMENT_STARTED = Date.now();

const text = (value: unknown): value is string =>
  typeof value === "string" && value.length > 0;
const field = (value: unknown, key: string): unknown =>
  value && typeof value === "object"
    ? (value as Record<string, unknown>)[key]
    : null;

/**
 * Who the server read this document's data for, as the app's identity key
 * (JSON of person, session and workspace), or null.
 */
export function serverIdentityKey(value: InitialSession | null): string | null {
  const person = field(value?.identity, "person_id");
  const session = field(value?.identity, "session_id");
  const tenant = field(value?.directory, "selected_tenant_id");
  return text(person) && text(session) && text(tenant)
    ? JSON.stringify([person, session, tenant])
    : null;
}

/**
 * Whether the page data the server read for this document may seed a page
 * that mounts now as `identityKey`: only for the exact person, session and
 * workspace the server read it for, and only while the document is new.
 * Decided once per mount.
 */
export function useServerSeedAllowed(identityKey: string | null): boolean {
  const value = useContext(InitialSessionContext);
  const [allowed] = useState(
    () =>
      identityKey !== null &&
      serverIdentityKey(value) === identityKey &&
      (typeof window === "undefined" ||
        Date.now() - DOCUMENT_STARTED < SEED_WINDOW_MS),
  );
  return allowed;
}

/** The server's session for this page, or null where the browser checks. */
export function useInitialSession(pathname: string | null) {
  const value = useContext(InitialSessionContext);
  const route = pathname?.replace(/\/$/, "") || "/";
  return value && SERVER_RENDERED.has(route) ? value : null;
}
