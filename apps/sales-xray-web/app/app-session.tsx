"use client";

import { RefreshCw } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { callIdFromPath } from "./analysis-routes";
import { UUID_RE } from "./prospects-client";
import { PurchaseShell } from "./plans/purchase-shell";
import styles from "./plans/plans.module.css";
import { readSalesXrayWorkspaces } from "./sales-xray-workspaces";
import { parseWorkspaceChoices, StandaloneStudio } from "./standalone-studio";
import {
  WorkspaceAccessProvider,
  type WorkspaceAccessValue,
} from "./workspace-access";

const SHELL_ROUTES = new Set([
  "/",
  "/dashboard",
  "/calls",
  "/prospects",
  "/account",
  "/organisation",
  "/analysis",
  "/analysis/new",
  "/analysis/calls",
]);

function isShellRoute(pathname: string | null) {
  if (!pathname) return false;
  // Static exports use trailing slashes for the same application pages.
  const route = pathname.replace(/\/$/, "") || "/";
  const prospectId = route.match(/^\/prospects\/([^/]+)$/)?.[1];
  return (
    SHELL_ROUTES.has(route) ||
    callIdFromPath(route) !== null ||
    (prospectId !== undefined && UUID_RE.test(prospectId))
  );
}

/** Confirm the same AC identity/directory without mounting the app frame. */
function PurchaseSession({ children }: { children: ReactNode }) {
  const [attempt, setAttempt] = useState(0);
  const [access, setAccess] = useState<Omit<
    WorkspaceAccessValue,
    "retry"
  > | null>(null);
  const retry = () => {
    setAccess(null);
    setAttempt((value) => value + 1);
  };
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    void (async () => {
      const response = await fetch("/v1/me/workspaces", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal,
        headers: { accept: "application/json" },
      });
      if (response.status === 401) {
        if (!signal.aborted)
          setAccess({
            status: "unauthenticated",
            authenticated: false,
            context: null,
          });
        return;
      }
      if (!response.ok) throw new Error("workspace_read_rejected");
      const identity = parseWorkspaceChoices(await response.json());
      if (!identity) throw new Error("workspace_shape_invalid");
      const directory = await readSalesXrayWorkspaces(signal);
      if (signal.aborted) return;
      setAccess({
        status:
          directory.selected_tenant_id !== null
            ? "ready"
            : directory.workspaces.length
              ? "chooser"
              : "empty",
        authenticated: true,
        workspaces: directory.workspaces,
        context:
          directory.selected_tenant_id !== null
            ? {
                personId: identity.person_id,
                sessionId: identity.session_id,
                tenantId: directory.selected_tenant_id,
              }
            : null,
      });
    })().catch(() => {
      if (!signal.aborted)
        setAccess({
          status: "unavailable",
          authenticated: null,
          context: null,
        });
    });
    return () => controller.abort();
  }, [attempt]);

  if (!access || access.status === "unavailable")
    return (
      <PurchaseShell>
        <p role="status">
          {access
            ? "Workspace access could not be checked. Try again in a moment."
            : "Checking your account…"}
        </p>
        {access && (
          <button type="button" className={styles.secondaryBtn} onClick={retry}>
            <RefreshCw size={13} aria-hidden="true" />
            Try again
          </button>
        )}
      </PurchaseShell>
    );
  return (
    <WorkspaceAccessProvider value={{ ...access, retry }}>
      {children}
    </WorkspaceAccessProvider>
  );
}

/**
 * Checks the session once per full-page load (layout mount).
 * Pages that live inside the Lightbox shell get StandaloneStudio;
 * plans confirms the same identity inside its focused purchase shell;
 * other pages (login, auth, review fixtures) receive their children directly.
 */
export function AppSession({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname?.replace(/\/$/, "") === "/plans") {
    return <PurchaseSession>{children}</PurchaseSession>;
  }
  if (isShellRoute(pathname)) {
    return <StandaloneStudio>{children}</StandaloneStudio>;
  }
  return <>{children}</>;
}
