"use client";

import { createContext, useContext, useEffect, useMemo } from "react";

import { useUploadSession } from "./hooks/upload-session";

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
  /** Open account access while keeping selected browser File objects. */
  requestAccountSignIn?: () => void;
  /** Return true only when this click may continue to the existing upload checks. */
  requestAnalysisAccess?: () => boolean;
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
  const upload = useUploadSession();
  const observation = useMemo(
    () => ({
      status: value.status,
      authenticated: value.authenticated,
      context: value.context,
    }),
    [value.authenticated, value.context, value.status],
  );
  useEffect(() => {
    upload?.observeAccount(observation);
  }, [observation, upload]);
  return (
    <WorkspaceAccessContext.Provider value={value}>
      {children}
    </WorkspaceAccessContext.Provider>
  );
}

export function useWorkspaceAccess() {
  return useContext(WorkspaceAccessContext);
}
