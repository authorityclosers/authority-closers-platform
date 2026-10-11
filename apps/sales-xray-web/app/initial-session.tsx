"use client";

import { createContext, useContext, type ReactNode } from "react";

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
export const SERVER_RENDERED = new Set(["/dashboard", "/analysis/calls"]);

/** The server's session for this page, or null where the browser checks. */
export function useInitialSession(pathname: string | null) {
  const value = useContext(InitialSessionContext);
  const route = pathname?.replace(/\/$/, "") || "/";
  return value && SERVER_RENDERED.has(route) ? value : null;
}
