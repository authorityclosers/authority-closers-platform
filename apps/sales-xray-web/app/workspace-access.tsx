"use client";

import { createContext, useContext } from "react";

export type WorkspaceAccessStatus =
  | "loading"
  | "unauthenticated"
  | "ready"
  | "empty"
  | "unavailable"
  | "chooser"
  | "selecting";

export type WorkspaceAccessValue = Readonly<{
  status: WorkspaceAccessStatus;
  /** True only after the server has confirmed an authenticated AC session. */
  authenticated: boolean | null;
  /** Server-confirmed account, session and selected workspace identity. */
  context: Readonly<{
    personId: string;
    sessionId: string;
    tenantId: string;
  }> | null;
  retry: () => void;
}>;

export const WorkspaceAccessContext =
  createContext<WorkspaceAccessValue | null>(null);

export function WorkspaceAccessProvider({
  value,
  children,
}: Readonly<{
  value: WorkspaceAccessValue;
  children: React.ReactNode;
}>) {
  return (
    <WorkspaceAccessContext.Provider value={value}>
      {children}
    </WorkspaceAccessContext.Provider>
  );
}

export function useWorkspaceAccess() {
  return useContext(WorkspaceAccessContext);
}
