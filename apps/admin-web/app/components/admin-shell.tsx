"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  BookOpenCheck,
  CircleAlert,
  LayoutDashboard,
  type LucideIcon,
} from "lucide-react";

import { BrandMark } from "@ac/ui";

import { AdminSessionProvider, AdminSessionStatus } from "../lib/admin-session";

export type AdminArea = "overview" | "people" | "catalog" | "operations";
export type AdminSupportArea = "correction" | "grant";

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

export function AdminShell({
  active,
  activeSupport,
  eyebrow,
  title,
  description,
  children,
}: {
  active: AdminArea;
  activeSupport?: AdminSupportArea;
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <AdminSessionProvider>
      <div className="admin-shell">
        <aside className="ops-sidebar">
          <div className="sidebar-topline">
            <Link
              className="brand"
              href="/"
              aria-label="Authority Closers operations home"
            >
              <BrandMark className="brand-mark" />
              <span>AC / OPS</span>
            </Link>
            <span className="sidebar-index" aria-hidden="true">
              G1
            </span>
          </div>

          <p className="sidebar-label">Primary surfaces</p>
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
              <span className="kicker">{eyebrow}</span>
              <h1 id="page-title">{title}</h1>
              <p>{description}</p>
            </div>
            <AdminSessionStatus />
          </header>

          {children}

          <footer className="admin-footer">
            <span>G1 / FREE COURSE ADMIN</span>
            <span>READ-ONLY PREVIEW · NO DATA ASSERTED</span>
          </footer>
        </main>
      </div>
    </AdminSessionProvider>
  );
}
