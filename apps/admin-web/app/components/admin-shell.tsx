"use client";

import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  BookOpenCheck,
  LayoutDashboard,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  X,
  MessagesSquare,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import { PLATFORM_BRAND, PlatformMark } from "@ac/ui";
import { useAdminWorkspaceControls } from "./admin-workspace-controls";
import styles from "./admin-shell.module.css";

import {
  AdminSessionProvider,
  AdminSessionStatus,
  canEnterStudio,
  canManageSalesXray,
  canUseAdminPermission,
  useAdminSession,
} from "../lib/admin-session";

export type AdminArea =
  | "overview"
  | "people"
  | "catalog"
  | "operations"
  | "sales-xray";
export type AdminSupportArea = "correction" | "grant";
export type AdminSurface = "organization" | "people" | "studio" | "operations";

type NavigationItem = {
  area: AdminArea;
  href: string;
  label: string;
  icon: LucideIcon;
  permissions: readonly string[];
};

const navigation: NavigationItem[] = [
  {
    area: "overview",
    href: "/",
    label: "Overview",
    icon: LayoutDashboard,
    permissions: ["admin_surface"],
  },
  {
    area: "people",
    href: "/people",
    label: "People",
    icon: UsersRound,
    permissions: ["learner_diagnose"],
  },
  {
    area: "catalog",
    href: "/studio",
    label: "Academy Studio",
    icon: BookOpenCheck,
    permissions: ["catalog_read"],
  },
  {
    area: "operations",
    href: "/learning-operations",
    label: "Learning operations",
    icon: Activity,
    permissions: ["job_retry", "recovery_reconcile"],
  },
  {
    area: "sales-xray",
    href: "/sales-xray",
    label: "Sales Xray",
    icon: MessagesSquare,
    permissions: ["admin_surface"],
  },
];

const supportNavigation: Array<{
  area: AdminSupportArea;
  href: string;
  label: string;
  permission: string;
}> = [
  {
    area: "correction",
    href: "/people/corrections",
    label: "Progress corrections",
    permission: "learning_correct",
  },
  {
    area: "grant",
    href: "/people/grants",
    label: "Course access",
    permission: "enrollment_grant",
  },
];

function AdminNavigation({
  active,
  activeSupport,
}: {
  active: AdminArea;
  activeSupport?: AdminSupportArea;
}) {
  const state = useAdminSession();
  const permissions = new Set(
    state.status === "ready" ? state.session.permissions : [],
  );
  const providerControlsVisible = canManageSalesXray(state);
  const visibleNavigation = navigation.filter(
    ({ area, permissions: required }) =>
      area === "sales-xray"
        ? providerControlsVisible
        : area === "catalog"
          ? canEnterStudio(state)
          : required.some((permission) => permissions.has(permission)),
  );
  const visibleSupport = supportNavigation.filter(({ permission }) =>
    permissions.has(permission),
  );

  return (
    <>
      <p className="sidebar-label">Workspace</p>
      <nav className="sidebar-nav" aria-label="Operations">
        {visibleNavigation.map(({ area, href, label, icon: Icon }) => {
          const isActive = active === area;
          const isCurrent = isActive && activeSupport === undefined;

          return (
            <Link
              className={isActive ? "active" : undefined}
              href={href}
              key={area}
              title={label}
              aria-label={label}
              aria-current={isCurrent ? "page" : undefined}
            >
              <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      {visibleSupport.length > 0 ? (
        <div className="sidebar-subnav">
          <p className="sidebar-label">Learner support</p>
          <nav aria-label="Support actions">
            {visibleSupport.map(({ area, href, label }) => (
              <Link
                className={activeSupport === area ? "active" : undefined}
                href={href}
                key={href}
                aria-current={activeSupport === area ? "page" : undefined}
              >
                <span>{label}</span>
                <span aria-hidden="true">↗</span>
              </Link>
            ))}
          </nav>
        </div>
      ) : null}
    </>
  );
}

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
      <section className="panel" role="status">
        <h2>Checking workspace access</h2>
        <p>Your workspace will open once your session is verified.</p>
      </section>
    );
  }
  if (state.status !== "ready" || (studioOnly && active !== "catalog")) {
    return (
      <section className="panel" role="status">
        <h2>
          {studioOnly && active === "overview"
            ? "Opening Academy Studio"
            : "Access unavailable"}
        </h2>
        <p>
          {studioOnly
            ? "Your current access is limited to your assigned Studio work."
            : "Your session could not be verified. Sign in again to continue."}
        </p>
        {studioOnly ? (
          <Link className="button button-primary" href="/studio/programs">
            Open Academy Studio
          </Link>
        ) : (
          <Link className="button button-primary" href="/login">
            Sign in
          </Link>
        )}
      </section>
    );
  }
  return children;
}

function AdminTenantContext() {
  const state = useAdminSession();
  const ready = state.status === "ready";
  return (
    <div className="tenant-switcher" aria-label="Tenant context">
      <span className="tenant-avatar" aria-hidden="true">
        {ready ? "AC" : "—"}
      </span>
      <span>
        <strong>{ready ? "Academy workspace" : "Workspace pending"}</strong>
        <small>
          {ready
            ? `${state.session.membershipRole} · context verified`
            : state.status === "loading"
              ? "Waiting for session verification"
              : "No verified tenant context"}
        </small>
      </span>
    </div>
  );
}

function AdminWorkspace({
  active,
  activeSupport,
  eyebrow,
  title,
  description,
  surface = "organization",
  footerText,
  sessionBoundary,
  children,
}: {
  active: AdminArea;
  activeSupport?: AdminSupportArea;
  eyebrow: string;
  title: string;
  description: string;
  surface?: AdminSurface;
  footerText?: string;
  sessionBoundary?: ReactNode;
  children: ReactNode;
}) {
  const state = useAdminSession();
  const {
    collapsed,
    toggleCollapsed,
    mobileOpen,
    openMobile,
    closeMobile,
    sidebarRef,
    triggerRef,
    signingOut,
    signOutError,
    requestSignOut,
  } = useAdminWorkspaceControls();
  return (
    <div
      className={`admin-shell clarity-shell surface-${surface} ${styles.shell}`}
      data-collapsed={collapsed}
      data-mobile-open={mobileOpen}
    >
      <aside
        className="ops-sidebar"
        id="admin-sidebar"
        ref={sidebarRef}
        aria-label="Admin workspace navigation"
        onClick={(event) => {
          if ((event.target as HTMLElement).closest("a[href]") && mobileOpen)
            closeMobile();
        }}
      >
        <div className="sidebar-topline">
          <Link
            className="brand"
            href="/"
            aria-label={`${PLATFORM_BRAND.name} operations home`}
          >
            <PlatformMark className="brand-mark" />
            <span className="brand-copy">
              <strong>{PLATFORM_BRAND.name}</strong>
              <small>admin workspace</small>
            </span>
          </Link>
          <button
            className={`${styles.iconButton} ${styles.desktopToggle}`}
            type="button"
            onClick={toggleCollapsed}
            aria-label={
              collapsed
                ? "Expand Admin navigation"
                : "Collapse Admin navigation"
            }
            aria-expanded={!collapsed}
            aria-controls="admin-sidebar"
          >
            {collapsed ? (
              <PanelLeftOpen size={19} />
            ) : (
              <PanelLeftClose size={19} />
            )}
          </button>
          <button
            className={`${styles.iconButton} ${styles.mobileClose}`}
            type="button"
            onClick={closeMobile}
            aria-label="Close Admin navigation"
          >
            <X size={20} />
          </button>
        </div>

        <AdminTenantContext />

        <AdminNavigation active={active} activeSupport={activeSupport} />

        <div className={styles.account}>
          {state.status === "ready" ? (
            <>
              <span className={styles.avatar} aria-hidden="true">
                {(state.session.displayName || state.session.email)
                  .slice(0, 1)
                  .toUpperCase()}
              </span>
              <div className={styles.accountCopy}>
                <strong>{state.session.displayName || "Your account"}</strong>
                <small title={state.session.email}>{state.session.email}</small>
              </div>
              <button
                className={styles.iconButton}
                type="button"
                onClick={requestSignOut}
                disabled={signingOut}
                aria-label={signingOut ? "Signing out" : "Sign out"}
                title="Sign out"
              >
                <LogOut size={18} />
              </button>
              {signOutError && (
                <p className={styles.signOutError} role="alert">
                  {signOutError}
                </p>
              )}
            </>
          ) : (
            <Link href="/login">Sign in</Link>
          )}
        </div>
      </aside>

      {mobileOpen && (
        <button
          className={styles.scrim}
          type="button"
          onClick={closeMobile}
          aria-label="Dismiss Admin navigation"
          tabIndex={-1}
        />
      )}
      <main
        inert={mobileOpen}
        className="admin-content"
        id="admin-content"
        aria-labelledby="page-title"
        tabIndex={-1}
      >
        <div className={styles.topbar}>
          <button
            className={`${styles.iconButton} ${styles.mobileToggle}`}
            ref={triggerRef}
            type="button"
            onClick={openMobile}
            aria-label="Open Admin navigation"
            aria-expanded={mobileOpen}
            aria-controls="admin-sidebar"
          >
            <Menu size={20} />
          </button>
          <span>Academy administration</span>
          {canManageSalesXray(state) ? (
            <Link href="/sales-xray/review" className={styles.reviewShortcut}>
              Review workspace
            </Link>
          ) : null}
        </div>
        <header className="page-header">
          <div className="page-heading">
            <div className="breadcrumb-row shell-breadcrumbs">
              <span>Admin workspace</span>
              <span aria-hidden="true">›</span>
              <span>
                {surface === "studio"
                  ? "Academy Studio"
                  : surface === "people"
                    ? "People"
                    : surface === "operations"
                      ? "Operations"
                      : "Overview"}
              </span>
            </div>
            <span className="kicker">{eyebrow}</span>
            <h1 id="page-title">{title}</h1>
            <p>{description}</p>
          </div>
          <div className="page-header-actions">
            <AdminSessionStatus />
          </div>
        </header>

        {sessionBoundary ?? (
          <AdminRouteContent active={active}>{children}</AdminRouteContent>
        )}

        <footer className="admin-footer">
          <span>{PLATFORM_BRAND.name} / Academy operations</span>
          <span>
            {footerText ??
              (surface === "studio"
                ? "TENANT-SCOPED · SERVER-AUTHORIZED · NO STORE"
                : active === "people"
                  ? "ACADEMY LEARNER RECORDS · AUDITED ACCESS"
                  : "PREVIEW DATA · NO RECORDS ASSERTED")}
          </span>
        </footer>
      </main>
    </div>
  );
}

export function AdminShell(props: Parameters<typeof AdminWorkspace>[0]) {
  return (
    <AdminSessionProvider
      renderBoundary={(boundary) => (
        <AdminWorkspace {...props} sessionBoundary={boundary}>
          {null}
        </AdminWorkspace>
      )}
    >
      <AdminWorkspace {...props} />
    </AdminSessionProvider>
  );
}
