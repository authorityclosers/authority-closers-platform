"use client";

import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  BarChart3,
  BookOpenCheck,
  ChevronDown,
  ClipboardList,
  CircleAlert,
  CircleHelp,
  LayoutDashboard,
  MessagesSquare,
  Settings,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import { PLATFORM_BRAND, PlatformMark } from "@ac/ui";

import {
  AdminSessionProvider,
  AdminSessionStatus,
  canEnterStudio,
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
    icon: CircleAlert,
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
    label: "Append correction",
    permission: "learning_correct",
  },
  {
    area: "grant",
    href: "/people/grants",
    label: "Manual grant",
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
  const providerControlsVisible =
    state.status === "ready" &&
    state.session.email.trim().toLowerCase() === "admin@authorityclosers.com" &&
    Boolean(state.session.emailVerifiedAt) &&
    ["owner", "admin"].includes(state.session.membershipRole) &&
    permissions.has("admin_surface");
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
          <p className="sidebar-label">Support seams</p>
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
        <strong>{ready ? "Server-selected tenant" : "Tenant pending"}</strong>
        <small>
          {ready
            ? `${state.session.membershipRole} · context verified`
            : state.status === "loading"
              ? "Waiting for session verification"
              : "No verified tenant context"}
        </small>
      </span>
      <ChevronDown size={16} aria-hidden="true" />
    </div>
  );
}

export function AdminShell({
  active,
  activeSupport,
  eyebrow,
  title,
  description,
  surface = "organization",
  footerText,
  children,
}: {
  active: AdminArea;
  activeSupport?: AdminSupportArea;
  eyebrow: string;
  title: string;
  description: string;
  surface?: AdminSurface;
  footerText?: string;
  children: ReactNode;
}) {
  return (
    <AdminSessionProvider>
      <div className={`admin-shell clarity-shell surface-${surface}`}>
        <aside className="ops-sidebar">
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
            <span className="sidebar-index">Alpha</span>
          </div>

          <AdminTenantContext />

          <AdminNavigation active={active} activeSupport={activeSupport} />

          <p className="sidebar-label sidebar-label-secondary">Coming next</p>
          <div
            className="sidebar-disabled-nav"
            aria-label="Unavailable admin surfaces"
          >
            <span>
              <UsersRound size={16} aria-hidden="true" /> Groups
            </span>
            <span>
              <ClipboardList size={16} aria-hidden="true" /> Assignments
            </span>
            <span>
              <BarChart3 size={16} aria-hidden="true" /> Reports
            </span>
            <span>
              <Settings size={16} aria-hidden="true" /> Settings
            </span>
          </div>

          <div className="sidebar-footer" role="note">
            <span className="status-dot" aria-hidden="true" />
            <p>
              Restricted control plane
              <br />
              <span>Audit every intervention</span>
            </p>
          </div>
        </aside>

        <main
          className="admin-content"
          id="admin-content"
          aria-labelledby="page-title"
          tabIndex={-1}
        >
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
              <button
                className="icon-button"
                type="button"
                aria-label="Help (unavailable)"
                disabled
              >
                <CircleHelp size={18} aria-hidden="true" />
              </button>
              <AdminSessionStatus />
            </div>
          </header>

          <AdminRouteContent active={active}>{children}</AdminRouteContent>

          <footer className="admin-footer">
            <span>{PLATFORM_BRAND.name} / Academy operations</span>
            <span>
              {footerText ?? (surface === "studio"
                ? "TENANT-SCOPED · SERVER-AUTHORIZED · NO STORE"
                : active === "people"
                  ? "ACADEMY LEARNER RECORDS · AUDITED ACCESS"
                  : "PREVIEW DATA · NO RECORDS ASSERTED")}
            </span>
          </footer>
        </main>
      </div>
    </AdminSessionProvider>
  );
}
