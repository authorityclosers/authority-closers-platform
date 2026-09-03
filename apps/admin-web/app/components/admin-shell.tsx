"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  BarChart3,
  BookOpenCheck,
  ChevronDown,
  ClipboardList,
  CircleAlert,
  CircleHelp,
  LayoutDashboard,
  Settings,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import { BrandMark } from "@ac/ui";

import {
  AdminSessionProvider,
  AdminSessionStatus,
  useAdminSession,
} from "../lib/admin-session";

export type AdminArea = "overview" | "people" | "catalog" | "operations";
export type AdminSupportArea = "correction" | "grant";
export type AdminSurface = "organization" | "people" | "studio" | "operations";

type NavigationItem = {
  area: AdminArea;
  href: string;
  label: string;
  icon: LucideIcon;
};

const navigation: NavigationItem[] = [
  { area: "overview", href: "/", label: "Overview", icon: LayoutDashboard },
  { area: "people", href: "/people", label: "People", icon: CircleAlert },
  { area: "catalog", href: "/catalog", label: "Catalog", icon: BookOpenCheck },
  {
    area: "operations",
    href: "/learning-operations",
    label: "Learning operations",
    icon: Activity,
  },
];

const supportNavigation: Array<{
  area: AdminSupportArea;
  href: string;
  label: string;
}> = [
  {
    area: "correction",
    href: "/people/corrections",
    label: "Append correction",
  },
  { area: "grant", href: "/people/grants", label: "Manual grant" },
];

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
  children,
}: {
  active: AdminArea;
  activeSupport?: AdminSupportArea;
  eyebrow: string;
  title: string;
  description: string;
  surface?: AdminSurface;
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
              aria-label="Authority Closers operations home"
            >
              <BrandMark className="brand-mark" />
              <span className="brand-copy">
                <strong>Authority LMS</strong>
                <small>admin workspace</small>
              </span>
            </Link>
            <span className="sidebar-index">v2</span>
          </div>

          <AdminTenantContext />

          <p className="sidebar-label">Workspace</p>
          <nav className="sidebar-nav" aria-label="Operations">
            {navigation.map(({ area, href, label, icon: Icon }) => {
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

          <div className="sidebar-subnav">
            <p className="sidebar-label">Support seams</p>
            <nav aria-label="Support actions">
              {supportNavigation.map(({ area, href, label }) => (
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
                    ? "Course studio"
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

          {children}

          <footer className="admin-footer">
            <span>AUTHORITY LMS / ADMIN FOUNDATION</span>
            <span>PREVIEW DATA · NO RECORDS ASSERTED</span>
          </footer>
        </main>
      </div>
    </AdminSessionProvider>
  );
}
