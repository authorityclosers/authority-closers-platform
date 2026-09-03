"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  AdminSessionDenied,
  loadAdminSession,
  type AdminPermission,
  type AdminSession,
} from "./admin-api";

export type AdminSessionState =
  | Readonly<{ status: "loading"; session: null; error: null }>
  | Readonly<{ status: "ready"; session: AdminSession; error: null }>
  | Readonly<{
      status: "denied" | "error";
      session: null;
      error: string;
    }>;

const initialState: AdminSessionState = {
  status: "loading",
  session: null,
  error: null,
};

const AdminSessionContext = createContext<AdminSessionState>(initialState);

export function canUseAdminPermission(
  state: AdminSessionState,
  permission: AdminPermission,
): boolean {
  return (
    state.status === "ready" &&
    state.session.permissions.includes("admin_surface") &&
    state.session.permissions.includes(permission)
  );
}

export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AdminSessionState>(initialState);

  useEffect(() => {
    let mounted = true;
    void loadAdminSession()
      .then((session) => {
        if (mounted) setState({ status: "ready", session, error: null });
      })
      .catch((error: unknown) => {
        if (!mounted) return;
        if (error instanceof AdminSessionDenied) {
          setState({
            status: "denied",
            session: null,
            error: error.message,
          });
          return;
        }
        setState({
          status: "error",
          session: null,
          error: "The product session could not be checked.",
        });
      });

    return () => {
      mounted = false;
    };
  }, []);

  const value = useMemo(() => state, [state]);
  return (
    <AdminSessionContext.Provider value={value}>
      {children}
    </AdminSessionContext.Provider>
  );
}

export function useAdminSession(): AdminSessionState {
  return useContext(AdminSessionContext);
}

export function AdminSessionStatus() {
  const state = useAdminSession();
  if (state.status === "loading") {
    return (
      <div
        className="environment-chip"
        aria-label="Checking product admin session"
      >
        <span className="status-dot" aria-hidden="true" />
        <span>Checking session</span>
        <small>Verifying /v1/me + /v1/context</small>
      </div>
    );
  }
  if (state.status === "ready") {
    return (
      <div
        className="environment-chip"
        aria-label="Product admin session verified"
      >
        <span className="status-dot status-dot-live" aria-hidden="true" />
        <span>Session verified</span>
        <small>
          {state.session.membershipRole} · {state.session.email}
        </small>
      </div>
    );
  }
  return (
    <div
      className="environment-chip environment-chip-denied"
      aria-label="Product admin session denied"
    >
      <span className="status-dot status-dot-error" aria-hidden="true" />
      <span>Admin access unavailable</span>
      <small>
        {state.status === "denied" ? "Permission denied" : "Retry required"}
      </small>
    </div>
  );
}
