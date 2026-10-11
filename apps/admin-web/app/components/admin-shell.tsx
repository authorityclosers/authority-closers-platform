"use client";

/**
 * The frame for admin screens that have not been rebuilt on the kit yet. The
 * console shell (app/ui/shell.tsx) now draws navigation, the top bar and the
 * account row, and provides the admin session; this only adds the page header
 * and keeps the old rule that a screen's body waits for a verified session.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import {
  AdminSessionProvider,
  canUseAdminPermission,
  useAdminSession,
} from "../lib/admin-session";
import { Page, PageHeader, Skeleton, kitStyles } from "../ui/kit";

/** Set by the console shell, which already provides the admin session. */
export const ConsoleSessionContext = createContext(false);

export type AdminArea =
  | "overview"
  | "people"
  | "catalog"
  | "operations"
  | "sales-xray";
export type AdminSupportArea = "correction" | "grant";
export type AdminSurface = "organization" | "people" | "studio" | "operations";

function AdminRouteContent({
  active,
  children,
}: {
  active: AdminArea;
  children: ReactNode;
}) {
  const state = useAdminSession();
  const router = useRouter();
  const studioOnly =
    state.status === "ready" && !canUseAdminPermission(state, "admin_surface");
  useEffect(() => {
    if (studioOnly && active === "overview") router.replace("/studio/programs");
  }, [studioOnly, active, router]);
  if (state.status === "loading") {
    return (
      <section
        className={kitStyles.panel}
        role="status"
        aria-busy="true"
        aria-label="Checking workspace access"
      >
        <div className={kitStyles.empty}>
          <Skeleton width="40%" height={14} />
          <Skeleton width="60%" height={12} />
          <span className={kitStyles.srOnly}>Checking workspace access</span>
        </div>
      </section>
    );
  }
  if (state.status !== "ready" || (studioOnly && active !== "catalog")) {
    return (
      <section className={kitStyles.panel} role="status">
        <div className={kitStyles.empty}>
          <p className={kitStyles.emptyTitle}>
            {studioOnly && active === "overview"
              ? "Opening Academy Studio"
              : "Access unavailable"}
          </p>
          <p className={kitStyles.emptyText}>
            {studioOnly
              ? "Your current access is limited to your assigned Studio work."
              : "Your session could not be verified. Sign in again to continue."}
          </p>
          <Link
            className={kitStyles.button}
            href={studioOnly ? "/studio/programs" : "/login"}
          >
            {studioOnly ? "Open Academy Studio" : "Sign in"}
          </Link>
        </div>
      </section>
    );
  }
  return children;
}

export function AdminShell({
  active,
  title,
  description,
  sessionBoundary,
  children,
}: {
  active: AdminArea;
  activeSupport?: AdminSupportArea;
  eyebrow?: string;
  title: string;
  description: string;
  surface?: AdminSurface;
  footerText?: string;
  sessionBoundary?: ReactNode;
  children: ReactNode;
}) {
  const insideConsole = useContext(ConsoleSessionContext);
  const page = (
    <Page>
      <PageHeader title={title} context={[description]} />
      {sessionBoundary ?? (
        <AdminRouteContent active={active}>{children}</AdminRouteContent>
      )}
    </Page>
  );
  // Rendered on its own (tests, or outside the console), it checks the session itself.
  return insideConsole ? (
    page
  ) : (
    <AdminSessionProvider>{page}</AdminSessionProvider>
  );
}
