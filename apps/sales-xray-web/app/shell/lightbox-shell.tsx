"use client";

import {
  AlertCircle,
  AudioLines,
  CheckCircle2,
  ChevronDown,
  ChevronsUpDown,
  CircleUserRound,
  FolderOpen,
  HelpCircle,
  LayoutGrid,
  Loader,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import { readAccountProfile } from "../account-profile-client";
import type { Allowance } from "../acquisition-client";
import { LocalSettingsButton } from "../live-data-banner";
import { newCallHref } from "../new-call-navigation";
import { ProfileMenu } from "../profile-menu";
import { useWorkspaceAccess } from "../workspace-access";
import { BrandLockup } from "./brand-lockup";
import { MinutesMeter } from "./minutes-meter";
import {
  readCallSummary,
  readRecentCalls,
  type CallSummary,
} from "../dashboard/dashboard-data";
import {
  getShellState,
  updateShellState,
} from "./shell-store";
import styles from "./lightbox-shell.module.css";

export type LightboxShellProps = {
  children: ReactNode;
  authenticated: boolean;
  homeHref?: string;
  active?: "dashboard" | "analyse" | "calls" | "account";
  compactBusy?: boolean;
  mobileFit?: boolean;
  welcome?: boolean;
  heroStage?: "welcome" | "ready" | "processing";
  /** Kept for API compatibility; the shell shows no greeting banner. */
  displayName?: string | null;
  /** Label the explicit local review fixture without implying a real job. */
  previewHero?: boolean;
  /** A verified session allowance; the meter stays hidden without one. */
  allowance?: Allowance | null;
};

type PageHeading = { title: string; description?: string };

// Compact, truthful page headings. No greeting, slogan or estimated duration.
function pageHeading(
  stage: LightboxShellProps["heroStage"],
  previewHero: boolean,
): PageHeading | null {
  if (stage === "ready")
    return {
      title: "Ready to analyse",
      description: "Your call is saved. Start analysis to get your report.",
    };
  if (stage === "processing")
    return previewHero
      ? {
          title: "Example processing state",
          description:
            "A read-only preview of how your call moves from upload to report.",
        }
      : {
          title: "Analysing your call",
          description: "Find this call and its progress in Calls.",
        };
  if (stage === "welcome")
    return {
      title: "New analysis",
      description: "Upload a sales call to generate insights and a report.",
    };
  return null;
}

function resolvePageTitle(
  active: LightboxShellProps["active"],
  heading: PageHeading | null,
): string | null {
  if (active === "dashboard") return "Dashboard";
  if (heading) return heading.title;
  if (active === "calls") return "Calls";
  if (active === "account") return "Account";
  return null;
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return (name.slice(0, 2) || "CA").toUpperCase();
}

export function LightboxShell({
  children,
  authenticated,
  homeHref = "/",
  active = "analyse",
  compactBusy = false,
  mobileFit = false,
  welcome = false,
  heroStage,
  previewHero = false,
  allowance = null,
  displayName = null,
}: LightboxShellProps) {
  const cached = getShellState();
  const [collapsed, setCollapsed] = useState(cached.collapsed);
  const [counts, setCounts] = useState<CallSummary | null>(cached.counts);
  const [workspaces, setWorkspaces] = useState(cached.workspaces);
  const [selectedTenantId, setSelectedTenantId] = useState(cached.selectedTenantId);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [statusQuery] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("status");
  });
  const [profileName, setProfileName] = useState(cached.profileName);
  const [recentCalls, setRecentCalls] = useState(cached.recentCalls);
  const [recentsOpen, setRecentsOpen] = useState(cached.recentsOpen);

  const switcherRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const access = useWorkspaceAccess();

  const accountHref = authenticated ? "/account" : "/login";
  const accountLabel = authenticated ? "Account" : "Profile & account";
  const visibleHero = heroStage ?? (welcome ? "welcome" : undefined);
  const heading = compactBusy ? null : pageHeading(visibleHero, previewHero);
  const pageTitle = resolvePageTitle(active, heading);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      updateShellState({ collapsed: next });
      try {
        localStorage.setItem("sx.sidebar.collapsed", String(next));
      } catch {}
      return next;
    });
  };

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!authenticated || process.env.NODE_ENV === "test") {
      setRecentCalls([]);
      updateShellState({ recentCalls: [] });
      return;
    }
    const cached = getShellState();
    if (cached.fetchedAt !== null && Date.now() - cached.fetchedAt < 60_000) {
      return;
    }
    const controller = new AbortController();
    readRecentCalls(controller.signal)
      .then((submissions) => {
        const mapped = submissions.map((call) => ({
          id: call.id,
          name: call.label?.displayName ?? "Untitled call",
          date: new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
            new Date(call.createdAt),
          ),
        }));
        setRecentCalls(mapped);
        updateShellState({ recentCalls: mapped, fetchedAt: Date.now() });
      })
      .catch(() => {
        setRecentCalls([]);
        updateShellState({ recentCalls: [] });
      });
    return () => controller.abort();
  }, [authenticated]);

  useEffect(() => {
    if (!authenticated || process.env.NODE_ENV === "test") {
      return;
    }
    const controller = new AbortController();
    readCallSummary(controller.signal)
      .then((data) => {
        setCounts(data);
        updateShellState({ counts: data });
      })
      .catch(() => {
        setCounts(null);
        updateShellState({ counts: null });
      });
    return () => controller.abort();
  }, [authenticated]);

  useEffect(() => {
    if (!authenticated || process.env.NODE_ENV === "test") {
      return;
    }
    const controller = new AbortController();
    try {
      const promise = fetch("/v1/me/workspaces", {
        signal: controller.signal,
        credentials: "same-origin",
      });
      if (promise && typeof promise.then === "function") {
        promise
          .then((res) => (res.ok ? res.json() : null))
          .then((data) => {
            if (data && Array.isArray(data.workspaces)) {
              setWorkspaces(data.workspaces);
              const chosen =
                data.selected_tenant_id || data.workspaces[0]?.tenant_id || null;
              setSelectedTenantId(chosen);
              updateShellState({
                workspaces: data.workspaces,
                selectedTenantId: chosen,
                fetchedAt: Date.now(),
              });
            }
          })
          .catch(() => {});
      }
    } catch {}
    return () => controller.abort();
  }, [authenticated]);

  useEffect(() => {
    if (!authenticated || process.env.NODE_ENV === "test") {
      return;
    }
    const controller = new AbortController();
    readAccountProfile(controller.signal)
      .then((profile) => {
        if (!controller.signal.aborted && profile.name?.trim()) {
          const name = profile.name.trim();
          setProfileName(name);
          updateShellState({ profileName: name });
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [authenticated]);

  useEffect(() => {
    if (!switcherOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !switcherRef.current?.contains(event.target)
      ) {
        setSwitcherOpen(false);
      }
    };
    const closeEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setSwitcherOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [switcherOpen]);

  async function handleSelectWorkspace(tenantId: string) {
    if (tenantId === selectedTenantId) {
      setSwitcherOpen(false);
      return;
    }
    try {
      const res = await fetch("/v1/context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenantId }),
        credentials: "same-origin",
      });
      if (res.ok) {
        setSelectedTenantId(tenantId);
        setSwitcherOpen(false);
        const data = await readCallSummary();
        setCounts(data);
        updateShellState({ counts: data });
      }
    } catch {}
  }

  function openAccount(event: MouseEvent<HTMLAnchorElement>) {
    if (!authenticated && access?.requestAccountSignIn) {
      event.preventDefault();
      access.requestAccountSignIn();
    }
  }

  const currentWorkspace =
    workspaces.find((w) => w.tenant_id === selectedTenantId) ||
    workspaces[0] ||
    null;
  const currentWorkspaceName =
    profileName ||
    (currentWorkspace?.name && !currentWorkspace.name.toLowerCase().includes("closers academy")
      ? currentWorkspace.name
      : null) ||
    displayName ||
    "Workspace";
  const newAnalysisHref = newCallHref(homeHref);

  return (
    <div
      className={`${styles.shell} ${collapsed ? styles.collapsed : ""}`}
      data-lightbox-shell
      data-authenticated={authenticated}
      data-sidebar-collapsed={collapsed}
      data-compact-busy={compactBusy}
      data-mobile-fit={mobileFit}
      data-welcome={Boolean(visibleHero)}
      data-hero-stage={visibleHero}
    >
      <a className={styles.skip} href="#main-content">
        Skip to workspace
      </a>
      <aside
        id="sales-xray-sidebar"
        className={styles.sidebar}
        aria-label="Sales Xray navigation"
      >
        {/* 64px Icon Strip */}
        <div className={styles.iconStrip}>
          <div className={styles.stripTop}>
            <div className={styles.logoSlot}>
              <BrandLockup href={homeHref} markOnly={true} />
              {collapsed && (
                <button
                  type="button"
                  className={styles.logoExpandBtn}
                  onClick={toggleCollapsed}
                  aria-label="Expand sidebar navigation"
                  title="Expand navigation"
                >
                  <PanelLeftOpen size={18} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
          <div className={styles.stripNav}>
            <Link
              className={`${styles.stripBtn}${active === "dashboard" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/dashboard"
              aria-label="Dashboard"
              aria-current={active === "dashboard" ? "page" : undefined}
            >
              <LayoutGrid size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.tooltip}>Dashboard</span>
            </Link>
            <Link
              className={`${styles.stripBtn}${active === "analyse" ? ` ${styles.stripBtnActive}` : ""}`}
              href={newAnalysisHref}
              aria-label="New analysis"
              aria-current={active === "analyse" ? "page" : undefined}
            >
              <Plus size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.tooltip}>New analysis</span>
            </Link>
            <Link
              className={`${styles.stripBtn}${active === "calls" ? ` ${styles.stripBtnActive}` : ""}`}
              href="/calls"
              aria-label="Calls"
              aria-current={active === "calls" ? "page" : undefined}
            >
              <FolderOpen size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.tooltip}>Calls</span>
            </Link>
          </div>
          <div className={styles.stripBottom}>
            <Link
              className={`${styles.stripBtn}${active === "account" ? ` ${styles.stripBtnActive}` : ""}`}
              href={accountHref}
              onClick={openAccount}
              aria-label={accountLabel}
              aria-current={active === "account" ? "page" : undefined}
            >
              <Settings size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.tooltip}>{accountLabel}</span>
            </Link>
            <a
              className={styles.stripBtn}
              href="mailto:support@authorityclosers.com"
              aria-label="Help"
            >
              <HelpCircle size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.tooltip}>Help</span>
            </a>
          </div>
        </div>

        {/* 248px Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div className={styles.workspaceSwitcherContainer} ref={switcherRef}>
              <button
                type="button"
                className={styles.workspaceTrigger}
                onClick={() => {
                  if (workspaces.length > 1) {
                    setSwitcherOpen((v) => !v);
                  }
                }}
                aria-expanded={workspaces.length > 1 ? switcherOpen : undefined}
                aria-disabled={workspaces.length <= 1 ? true : undefined}
                aria-label={`Current workspace: ${currentWorkspaceName}`}
                title={currentWorkspaceName}
              >
                <div className={styles.workspaceTile} aria-hidden="true">
                  {getInitials(currentWorkspaceName)}
                </div>
                <div className={styles.workspaceCopy}>
                  <div className={styles.workspaceName} title={currentWorkspaceName}>
                    {currentWorkspaceName}
                  </div>
                  <div className={styles.workspaceSub}>Private workspace</div>
                </div>
                <ChevronsUpDown
                  size={14}
                  className={styles.workspaceChevron}
                  aria-hidden="true"
                />
              </button>

              {switcherOpen && workspaces.length > 1 && (
                <div className={styles.workspacePopover} role="menu">
                  {workspaces.map((w) => {
                    const isSelected = w.tenant_id === selectedTenantId;
                    return (
                      <button
                        key={w.tenant_id}
                        type="button"
                        className={styles.workspaceItem}
                        role="menuitem"
                        onClick={() => void handleSelectWorkspace(w.tenant_id)}
                      >
                        <span
                          className={`${styles.radioDot}${isSelected ? ` ${styles.radioDotActive}` : ""}`}
                        >
                          {isSelected ? "●" : "○"}
                        </span>
                        <span className={styles.workspaceItemName}>{w.name}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <button
              type="button"
              className={styles.collapseBtn}
              onClick={toggleCollapsed}
              aria-label="Collapse sidebar navigation"
              title="Collapse navigation"
            >
              <PanelLeftClose size={16} aria-hidden="true" />
            </button>
          </div>

          {/* Recents Section */}
          <div className={styles.recentsSection}>
            <div className={styles.recentsHeader}>
              <button
                type="button"
                className={styles.recentsToggleBtn}
                onClick={() => {
                  setRecentsOpen((prev) => {
                    const next = !prev;
                    updateShellState({ recentsOpen: next });
                    return next;
                  });
                }}
                aria-expanded={recentsOpen}
                title={recentsOpen ? "Collapse recents" : "Expand recents"}
              >
                <ChevronDown
                  size={14}
                  className={`${styles.recentsChevron}${recentsOpen ? "" : ` ${styles.recentsChevronCollapsed}`}`}
                  aria-hidden="true"
                />
                <span className={styles.recentsTitle}>Recents</span>
              </button>
              <Link href="/calls" className={styles.recentsViewAll} title="View all calls">
                View all
              </Link>
            </div>
            {recentsOpen && (
              <div className={styles.recentsList}>
                {recentCalls.map((call) => (
                  <Link
                    key={call.id}
                    href={`/calls?id=${call.id}`}
                    className={styles.recentItem}
                    title={call.name}
                  >
                    <AudioLines size={14} className={styles.recentIcon} aria-hidden="true" />
                    <span className={styles.recentName}>{call.name}</span>
                    <span className={styles.recentDate}>{call.date}</span>
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className={styles.panelSpacer} />

          <div className={styles.panelMeter}>
            <MinutesMeter allowance={allowance} />
          </div>
        </div>
      </aside>
      <div className={styles.content}>
        <header className={styles.mobileBar}>
          <BrandLockup href={homeHref} />
          <div className={styles.barActions}>
            <MinutesMeter allowance={allowance} variant="pill" />
            <ProfileMenu
              authenticated={authenticated}
              accountHref={accountHref}
            />
          </div>
        </header>
        <header className={styles.topBar}>
          <div className={styles.topBarLeft}>
            {pageTitle && (
              <div className={styles.titleWrap}>
                <div className={styles.topBarTitle}>
                  <span className={styles.titleContext}>Sales Xray</span>
                  <span className={styles.titleSlash} aria-hidden="true">/</span>
                  <span className={styles.titleText}>{pageTitle}</span>
                  {active === "dashboard" && (
                    <span className={styles.titleBadge}>
                      <span className={styles.titleDot} aria-hidden="true" />
                      Live Overview
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
          <div className={styles.topBarRight}>
            <div className={styles.searchBox}>
              <Search size={15} className={styles.searchIcon} aria-hidden="true" />
              <input
                ref={searchInputRef}
                type="search"
                className={styles.searchInput}
                placeholder="Search calls…"
                aria-label="Search calls"
              />
              <kbd className={styles.searchKbd}>⌘K</kbd>
            </div>
            <a
              href="mailto:support@authorityclosers.com"
              className={styles.helpButton}
              aria-label="Help & support"
              title="Help & support"
            >
              <HelpCircle size={18} aria-hidden="true" />
            </a>
            <ProfileMenu
              authenticated={authenticated}
              accountHref={accountHref}
              variant="header"
            />
          </div>
        </header>
        {heading?.description ? (
          <div className={styles.pageDescription}>
            <p>{heading.description}</p>
          </div>
        ) : null}
        <main id="main-content" className={styles.main}>
          {children}
        </main>
      </div>
      <nav
        className={styles.bottomNav}
        aria-label="Mobile Sales Xray navigation"
      >
        <Link
          className={styles.bottomLink}
          href={newAnalysisHref}
          aria-current={active === "analyse" ? "page" : undefined}
        >
          <Plus size={20} aria-hidden="true" />
          <span>New</span>
        </Link>
        <Link
          className={styles.bottomLink}
          href="/calls"
          aria-current={active === "calls" ? "page" : undefined}
        >
          <FolderOpen size={20} aria-hidden="true" />
          <span>Calls</span>
        </Link>
        <Link
          className={styles.bottomLink}
          href={accountHref}
          onClick={openAccount}
          aria-current={active === "account" ? "page" : undefined}
        >
          <CircleUserRound size={20} aria-hidden="true" />
          <span>{authenticated ? "Account" : "Profile"}</span>
        </Link>
        <LocalSettingsButton className={styles.bottomLink} />
      </nav>
    </div>
  );
}
