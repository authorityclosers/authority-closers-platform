"use client";

/**
 * The console frame, after Pulse's shell: a rail of grouped sections on the
 * left (icons only on tablets or when collapsed), a slim top bar, and on
 * phones a bottom bar with the main sections plus "More", which opens the
 * full rail as a sheet. Sections a person can't use are not shown; the API
 * still checks every read and command.
 */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Activity,
  BadgeIndianRupee,
  BarChart3,
  ChartNoAxesCombined,
  BookOpenCheck,
  ClipboardCheck,
  Building2,
  CircleGauge,
  Clapperboard,
  Coins,
  FlaskConical,
  GraduationCap,
  Handshake,
  Home,
  LogOut,
  Megaphone,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Rocket,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  Timer,
  UserCheck,
  UsersRound,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { ConsoleSessionContext } from "../components/admin-shell";
import { useAdminWorkspaceControls } from "../components/admin-workspace-controls";
import { AdminSessionProvider } from "../lib/admin-session";
import {
  activeHref,
  visibleNavigation,
  type ConsoleAccess,
  type NavIcon,
} from "../lib/nav";
import type { Workspace } from "../lib/workspaces";
import { AccountMenu } from "./account-menu";
import { CommandMenu } from "./command-menu";
import { EnvironmentSwitch, isEnvironment } from "./environment-switch";
import { ThemeToggle } from "./theme";
import styles from "./shell.module.css";

const ICONS: Record<NavIcon, LucideIcon> = {
  home: Home,
  calls: Clapperboard,
  gold: Star,
  reviewers: UserCheck,
  review: ClipboardCheck,
  health: Activity,
  usage: BarChart3,
  company: ChartNoAxesCombined,
  outcomes: Handshake,
  providers: Coins,
  settings: Settings,
  analysis: SlidersHorizontal,
  execution: CircleGauge,
  minutes: Timer,
  synthetic: FlaskConical,
  people: UsersRound,
  organisations: Building2,
  billing: BadgeIndianRupee,
  academies: GraduationCap,
  learning: Workflow,
  studio: BookOpenCheck,
  releases: Rocket,
  updates: Megaphone,
  safety: ShieldCheck,
};

export function AcMark({ size = 20 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 512 512"
      aria-hidden="true"
      fill="currentColor"
    >
      <polygon points="32,432 192,48 280,48 120,432" />
      <polygon points="308,112 440,432 144,432 184,328 296,328 260,224" />
    </svg>
  );
}

export function ConsoleShell({
  access,
  environment,
  workspaces = null,
  children,
}: {
  access: ConsoleAccess;
  environment: string | null;
  /** Every workspace, for people with platform read; else null. */
  workspaces?: readonly Workspace[] | null;
  children: ReactNode;
}) {
  const pathname = usePathname() ?? "/";
  const search = useSearchParams()?.toString() ?? "";
  const groups = visibleNavigation(access);
  const current = activeHref(pathname, groups, search);
  const phoneItems = groups
    .flatMap((group) => group.items)
    .filter((item) => item.phone)
    .slice(0, 4);
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
  const currentLabel =
    groups.flatMap((group) => group.items).find((item) => item.href === current)
      ?.label ?? "Admin";

  return (
    <AdminSessionProvider>
      <ConsoleSessionContext.Provider value={true}>
        <div
          className={styles.shell}
          data-collapsed={collapsed ? "" : undefined}
          data-sheet={mobileOpen ? "" : undefined}
        >
          <aside
            className={styles.rail}
            id="admin-sidebar"
            ref={sidebarRef}
            aria-label="Admin navigation"
            onClick={(event) => {
              if (
                (event.target as HTMLElement).closest("a[href]") &&
                mobileOpen
              )
                closeMobile();
            }}
          >
            <div className={styles.brandRow}>
              <AccountMenu access={access} workspaces={workspaces} />
              <button
                type="button"
                className={`${styles.iconButton} ${styles.collapseToggle}`}
                onClick={toggleCollapsed}
                aria-label={
                  collapsed ? "Expand navigation" : "Collapse navigation"
                }
                aria-expanded={!collapsed}
                aria-controls="admin-sidebar"
                title={collapsed ? "Expand navigation" : "Collapse navigation"}
              >
                {collapsed ? (
                  <PanelLeftOpen size={16} aria-hidden="true" />
                ) : (
                  <PanelLeftClose size={16} aria-hidden="true" />
                )}
              </button>
              <button
                type="button"
                className={`${styles.iconButton} ${styles.sheetClose}`}
                onClick={closeMobile}
                aria-label="Close navigation"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <nav className={styles.nav} aria-label="Sections">
              {groups.map((group, index) => (
                <div className={styles.group} key={group.label || index}>
                  {group.label ? (
                    <p className={styles.groupLabel}>{group.label}</p>
                  ) : null}
                  {group.items.map((item) => {
                    const Icon = ICONS[item.icon];
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={styles.navLink}
                        aria-current={
                          item.href === current ? "page" : undefined
                        }
                        title={item.label}
                        prefetch={false}
                      >
                        <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
                        <span>{item.label}</span>
                      </Link>
                    );
                  })}
                </div>
              ))}
            </nav>

            <div className={styles.account}>
              <Link href="/" className={styles.brand} aria-label="Admin home">
                <span className={styles.brandMark}>
                  <AcMark size={16} />
                </span>
                <span className={styles.brandText}>
                  <strong>AC Admin</strong>
                  <small>{environment ?? "Back office"}</small>
                </span>
              </Link>
              <button
                type="button"
                className={styles.iconButton}
                onClick={requestSignOut}
                disabled={signingOut}
                aria-label={signingOut ? "Signing out" : "Sign out"}
                title="Sign out"
              >
                <LogOut size={16} aria-hidden="true" />
              </button>
              {signOutError ? (
                <p className={styles.accountError} role="alert">
                  {signOutError}
                </p>
              ) : null}
            </div>
          </aside>

          {mobileOpen ? (
            <button
              type="button"
              className={styles.scrim}
              onClick={closeMobile}
              aria-label="Dismiss navigation"
              tabIndex={-1}
            />
          ) : null}

          <div className={styles.body} inert={mobileOpen}>
            <header className={styles.topbar}>
              <button
                type="button"
                ref={triggerRef}
                className={`${styles.iconButton} ${styles.menuButton}`}
                onClick={openMobile}
                aria-label="Open navigation"
                aria-expanded={mobileOpen}
                aria-controls="admin-sidebar"
              >
                <Menu size={18} aria-hidden="true" />
              </button>
              <span className={styles.where}>{currentLabel}</span>
              <span className={styles.topTools}>
                {isEnvironment(environment) ? (
                  <EnvironmentSwitch environment={environment} />
                ) : environment ? (
                  <span className={styles.env} data-env={environment}>
                    {environment}
                  </span>
                ) : null}
                <CommandMenu groups={groups} />
                <ThemeToggle />
              </span>
            </header>
            <main id="admin-content" className={styles.main} tabIndex={-1}>
              {children}
            </main>
          </div>

          {phoneItems.length ? (
            <nav className={styles.bottomBar} aria-label="Main sections">
              {phoneItems.map((item) => {
                const Icon = ICONS[item.icon];
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={styles.bottomLink}
                    aria-current={item.href === current ? "page" : undefined}
                    prefetch={false}
                  >
                    <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
              <button
                type="button"
                className={styles.bottomLink}
                onClick={openMobile}
                aria-label="More sections"
              >
                <Menu size={18} strokeWidth={1.8} aria-hidden="true" />
                <span>More</span>
              </button>
            </nav>
          ) : null}
        </div>
      </ConsoleSessionContext.Provider>
    </AdminSessionProvider>
  );
}
