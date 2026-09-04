"use client";

/* Avatar delivery URLs are signed and provider-owned at runtime. */
/* eslint-disable @next/next/no-img-element */

import {
  ArrowLeft,
  ArrowUpRight,
  BarChart2,
  Bell,
  BookOpen,
  ChevronDown,
  Compass,
  HelpCircle,
  LayoutDashboard,
  MessageCircle,
  Search,
  Settings,
  User,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { BrandMark } from "@ac/ui";

import { createLearnerApi } from "../lib/learner-api";
import { NotificationPopover } from "./notifications-runtime";
import { initialsForDisplayName } from "../lib/profile-identity";
import { ROUTES } from "../lib/routes";
import { SignOutControl } from "./sign-out-control";
import {
  CommandPalette,
  MobileBottomNav,
  MobileMoreSheet,
  SidebarBadge,
  SidebarCollapseButton,
  SidebarNav,
  SidebarNavItem,
  SidebarTooltip,
  TenantIdentity,
  TenantSwitcher,
  type CommandPaletteItem,
  type SidebarNavItemConfig,
  type SidebarNavSection,
  type TenantIdentityConfig,
  type TenantSwitcherConfig,
  useCommandPaletteShortcuts,
} from "./learner-sidebar";

export { initialsForDisplayName } from "../lib/profile-identity";
export {
  CommandPalette,
  MobileBottomNav,
  MobileMoreSheet,
  SidebarBadge,
  SidebarCollapseButton,
  SidebarNav,
  SidebarNavItem,
  SidebarTooltip,
  TenantIdentity,
  TenantSwitcher,
  type CommandPaletteItem,
  type SidebarNavItemConfig,
  type SidebarNavSection,
  type TenantIdentityConfig,
  type TenantSwitcherConfig,
};

export const DEFAULT_TENANT_IDENTITY: TenantIdentityConfig = {
  tenantName: "Authority Closers",
  academyName: "Closers Academy",
  attribution: "by Authority Closers",
  homeHref: ROUTES.dashboard,
  mark: <BrandMark className="learner-sidebar-wordmark__mark-art" />,
};

export type PublicCurrent = "home" | "program";
export type LearnerCurrent =
  | "dashboard"
  | "home"
  | "learning"
  | "discover"
  | "progress"
  | "calendar"
  | "notifications"
  | "profile"
  | "settings"
  | "course"
  | "certificate"
  | "none";
export type AppShellCurrent = LearnerCurrent;

function BrandLink({ href = ROUTES.home }: { href?: string }) {
  return (
    <Link className="brand" href={href} aria-label="Authority Closers home">
      <BrandMark className="brand-mark" />
      <span>Authority Closers</span>
    </Link>
  );
}

export function LearnerSidebarBrand({
  identity = DEFAULT_TENANT_IDENTITY,
  collapsed = false,
}: {
  identity?: TenantIdentityConfig;
  collapsed?: boolean;
}) {
  return <TenantIdentity identity={identity} collapsed={collapsed} />;
}

export function PublicShell({
  children,
  current = "home",
}: {
  children?: React.ReactNode;
  current?: PublicCurrent;
}) {
  return (
    <div className="site-frame">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header__inner">
          <BrandLink />
          <nav className="public-nav" aria-label="Public navigation">
            <Link
              href="/#method"
              aria-current={current === "home" ? "page" : undefined}
            >
              The method
            </Link>
            <Link href={ROUTES.login}>Sign in</Link>
            <Link
              className="button button--small button--outline"
              href={ROUTES.home}
            >
              Explore published programs{" "}
              <ArrowUpRight size={15} aria-hidden="true" />
            </Link>
          </nav>
        </div>
      </header>
      {children}
      <footer className="site-footer">
        <div className="site-footer__inner">
          <BrandLink />
          <p>Learner workspace · browser-first learning.</p>
          <nav className="site-footer__links" aria-label="Legal and access">
            <Link href={ROUTES.privacy}>Privacy</Link>
            <Link href={ROUTES.terms}>Terms</Link>
            <Link href={ROUTES.login}>
              Sign in <ArrowUpRight size={14} aria-hidden="true" />
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function LearnerNavLink({
  href,
  label,
  current,
  icon,
  onClick,
  title,
}: {
  href: string;
  label: string;
  current: boolean;
  icon: React.ReactNode;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <Link
      className={`learner-nav__link${current ? " is-current" : ""}`}
      href={href}
      prefetch={false}
      aria-current={current ? "page" : undefined}
      onClick={onClick}
      title={title ?? label}
    >
      <span className="learner-nav__icon" aria-hidden="true">
        {icon}
      </span>
      <span className="learner-nav__label">{label}</span>
    </Link>
  );
}

const SUPPORT_MAILTO =
  "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20Learner%20Support";
const SIDEBAR_COLLAPSE_STORAGE_KEY = "ac.learner.sidebar.collapsed.v1";
const SIDEBAR_COLLAPSE_EVENT = "ac:learner-sidebar-preference";
let sidebarCollapsedFallback = false;

function getSidebarCollapsedSnapshot(): boolean {
  try {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSE_STORAGE_KEY);
    return stored === null ? sidebarCollapsedFallback : stored === "true";
  } catch {
    return sidebarCollapsedFallback;
  }
}

function subscribeSidebarCollapsed(onStoreChange: () => void): () => void {
  const handleChange = () => onStoreChange();
  window.addEventListener("storage", handleChange);
  window.addEventListener(SIDEBAR_COLLAPSE_EVENT, handleChange);
  return () => {
    window.removeEventListener("storage", handleChange);
    window.removeEventListener(SIDEBAR_COLLAPSE_EVENT, handleChange);
  };
}

function setSidebarCollapsedPreference(collapsed: boolean): void {
  sidebarCollapsedFallback = collapsed;
  try {
    window.localStorage.setItem(
      SIDEBAR_COLLAPSE_STORAGE_KEY,
      String(collapsed),
    );
  } catch {
    // The in-memory preference still updates in storage-restricted contexts.
  }
  window.dispatchEvent(new Event(SIDEBAR_COLLAPSE_EVENT));
}

export function closeAccountMenu(
  setOpen: (open: boolean) => void,
  trigger: Pick<HTMLButtonElement, "focus"> | null,
): void {
  setOpen(false);
  trigger?.focus();
}

export function closeNotificationPopover(
  setOpen: (open: boolean) => void,
  trigger: Pick<HTMLButtonElement, "focus"> | null,
): void {
  setOpen(false);
  trigger?.focus();
}

export function closeHelpPopover(
  setOpen: (open: boolean) => void,
  trigger: Pick<HTMLButtonElement, "focus"> | null,
): void {
  setOpen(false);
  trigger?.focus();
}

export type LearnerShellProps = {
  children?: React.ReactNode;
  current?: LearnerCurrent;
  learningHref?: string;
  userDisplayName?: string;
  userEmail?: string;
  className?: string;
  tenantIdentity?: TenantIdentityConfig;
  tenantConfig?: TenantSwitcherConfig;
  navSections?: SidebarNavSection[];
  learningChildren?: SidebarNavItemConfig[];
};

// Preserved for accessible static references and test stability
export const STATIC_HELP_LABEL = (
  <span className="learner-nav__label">Help</span>
);

export type AppShellProps = LearnerShellProps;

function IdentityAvatar({
  className,
  displayName,
  avatarUrl,
  avatarAlt,
}: {
  className: string;
  displayName: string;
  avatarUrl: string | null;
  avatarAlt: string;
}) {
  const [failedAvatarUrl, setFailedAvatarUrl] = useState<string | null>(null);
  const imageUrl =
    avatarUrl && avatarUrl !== failedAvatarUrl ? avatarUrl : null;

  return (
    <span
      className={className}
      data-avatar-state={imageUrl ? "image" : "initials"}
      aria-hidden="true"
    >
      {imageUrl ? (
        <img
          className="learner-identity-avatar__image"
          src={imageUrl}
          alt={avatarAlt}
          onError={() => setFailedAvatarUrl(imageUrl)}
        />
      ) : (
        initialsForDisplayName(displayName)
      )}
    </span>
  );
}

export function LearnerShell({
  children,
  current = "dashboard",
  learningHref = ROUTES.learning,
  userDisplayName = "Learner",
  userEmail = "",
  className = "",
  tenantIdentity,
  tenantConfig,
  navSections,
  learningChildren,
}: LearnerShellProps) {
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [notificationPopoverOpen, setNotificationPopoverOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [commandPaletteInvoker, setCommandPaletteInvoker] =
    useState<HTMLElement | null>(null);
  const searchTriggerRef = useRef<HTMLAnchorElement>(null);
  const sidebarSearchTriggerRef = useRef<HTMLButtonElement>(null);
  const mobileSearchTriggerRef = useRef<HTMLAnchorElement>(null);

  function openCommandPalette(invokingElement?: HTMLElement | null): void {
    setAccountMenuOpen(false);
    setNotificationPopoverOpen(false);
    setHelpOpen(false);
    setMobileDrawerOpen(false);
    const resolvedInvoker =
      invokingElement ??
      (typeof document !== "undefined" &&
      document.activeElement instanceof HTMLElement &&
      document.activeElement !== document.body
        ? document.activeElement
        : searchTriggerRef.current);
    setCommandPaletteInvoker(resolvedInvoker);
    setCommandPaletteOpen(true);
  }

  const sidebarCollapsed = useSyncExternalStore(
    subscribeSidebarCollapsed,
    getSidebarCollapsedSnapshot,
    () => false,
  );
  const [helpOpen, setHelpOpen] = useState(false);
  const [identity, setIdentity] = useState({
    displayName: userDisplayName,
    email: userEmail,
    avatarUrl: null as string | null,
    avatarAlt: `${userDisplayName}'s profile photo`,
  });
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const notificationButtonRef = useRef<HTMLButtonElement>(null);
  const notificationPopoverRef = useRef<HTMLDivElement>(null);
  const helpWrapperRef = useRef<HTMLDivElement>(null);
  const helpButtonRef = useRef<HTMLButtonElement>(null);
  const helpPanelRef = useRef<HTMLDivElement>(null);
  const avatarUpdateGenerationRef = useRef(0);

  let router: ReturnType<typeof useRouter> | null = null;
  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    router = useRouter();
  } catch {
    // Graceful fallback for non-Router execution
  }

  useCommandPaletteShortcuts({
    onOpenPalette: () => {
      openCommandPalette();
    },
    onNavigateHome: () => {
      if (router) router.push(ROUTES.dashboard);
      else window.location.href = ROUTES.dashboard;
    },
    onNavigateLearning: () => {
      if (router) router.push(learningHref);
      else window.location.href = learningHref;
    },
  });

  function toggleSidebar(): void {
    setSidebarCollapsedPreference(!sidebarCollapsed);
  }

  useEffect(() => {
    const controller = new AbortController();
    const api = createLearnerApi();

    async function loadIdentity() {
      const updateGeneration = avatarUpdateGenerationRef.current;
      const [meResult, avatarResult] = await Promise.allSettled([
        api.me({ signal: controller.signal }),
        api.profileAvatar({ signal: controller.signal }),
      ]);
      if (controller.signal.aborted || meResult.status !== "fulfilled") return;

      const displayName =
        meResult.value.display_name?.trim() || userDisplayName;
      const email = meResult.value.email?.trim() || userEmail.trim();
      const meAvatar = meResult.value.avatar;
      const profileAvatar =
        avatarResult.status === "fulfilled" &&
        avatarResult.value.avatar?.state === "ready" &&
        avatarResult.value.avatar.delivery_url
          ? avatarResult.value.avatar
          : null;
      const avatarReadIsCurrent =
        updateGeneration === avatarUpdateGenerationRef.current;

      setIdentity((current) => ({
        displayName,
        email,
        avatarUrl: avatarReadIsCurrent
          ? (profileAvatar?.delivery_url ?? meAvatar?.deliveryUrl ?? null)
          : current.avatarUrl,
        avatarAlt: avatarReadIsCurrent
          ? meAvatar?.alt?.trim() || `${displayName}'s profile photo`
          : current.avatarAlt,
      }));
    }

    void loadIdentity();
    const refreshTimer = window.setInterval(
      () => void loadIdentity(),
      4 * 60 * 1000,
    );

    function handleAvatarUpdated(event: Event) {
      if (!(event instanceof CustomEvent) || !event.detail) return;
      const detail = event.detail as {
        deliveryUrl?: unknown;
        alt?: unknown;
      };
      const deliveryUrl =
        typeof detail.deliveryUrl === "string" && detail.deliveryUrl
          ? detail.deliveryUrl
          : null;
      if (!deliveryUrl) return;
      avatarUpdateGenerationRef.current += 1;
      setIdentity((current) => ({
        ...current,
        avatarUrl: deliveryUrl,
        avatarAlt:
          typeof detail.alt === "string" && detail.alt.trim()
            ? detail.alt
            : current.avatarAlt,
      }));
    }

    window.addEventListener("ac-profile-avatar-updated", handleAvatarUpdated);
    return () => {
      controller.abort();
      window.clearInterval(refreshTimer);
      window.removeEventListener(
        "ac-profile-avatar-updated",
        handleAvatarUpdated,
      );
    };
  }, [userDisplayName, userEmail]);

  // Non-modal popovers close on Escape. Each modal owns its own Escape,
  // focus-trap, inert-background, cleanup, and focus-restoration behavior.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (accountMenuOpen) {
        closeAccountMenu(setAccountMenuOpen, accountButtonRef.current);
      }
      if (notificationPopoverOpen) {
        closeNotificationPopover(
          setNotificationPopoverOpen,
          notificationButtonRef.current,
        );
      }
      if (helpOpen) {
        closeHelpPopover(setHelpOpen, helpButtonRef.current);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [accountMenuOpen, notificationPopoverOpen, helpOpen]);

  useEffect(() => {
    if (!accountMenuOpen) return;

    const firstMenuItem =
      accountMenuRef.current?.querySelector<HTMLElement>('[role="menuitem"]');
    firstMenuItem?.focus();

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Node &&
        !accountMenuRef.current?.contains(target) &&
        !accountButtonRef.current?.contains(target)
      ) {
        closeAccountMenu(setAccountMenuOpen, accountButtonRef.current);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [accountMenuOpen]);

  function handleAccountMenuKeyDown(
    event: React.KeyboardEvent<HTMLDivElement>,
  ) {
    const menuItems = accountMenuRef.current
      ? Array.from(
          accountMenuRef.current.querySelectorAll<HTMLElement>(
            '[role="menuitem"]',
          ),
        )
      : [];
    if (event.key === "Escape") {
      event.preventDefault();
      closeAccountMenu(setAccountMenuOpen, accountButtonRef.current);
      return;
    }
    if (event.key === "Tab") {
      // Let the browser continue through the document's tab order. Closing
      // without restoring the trigger prevents the menu from trapping focus.
      setAccountMenuOpen(false);
      return;
    }
    if (
      !menuItems.length ||
      !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)
    ) {
      return;
    }
    event.preventDefault();
    const currentIndex = Math.max(
      0,
      menuItems.indexOf(document.activeElement as HTMLElement),
    );
    const nextIndex =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? menuItems.length - 1
          : (currentIndex +
              (event.key === "ArrowDown" ? 1 : -1) +
              menuItems.length) %
            menuItems.length;
    menuItems[nextIndex]?.focus();
  }

  useEffect(() => {
    if (!notificationPopoverOpen) return;

    const firstControl =
      notificationPopoverRef.current?.querySelector<HTMLElement>(
        'button, a[href], [tabindex]:not([tabindex="-1"])',
      );
    firstControl?.focus();

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Node &&
        !notificationPopoverRef.current?.contains(target) &&
        !notificationButtonRef.current?.contains(target)
      ) {
        closeNotificationPopover(
          setNotificationPopoverOpen,
          notificationButtonRef.current,
        );
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [notificationPopoverOpen]);

  useEffect(() => {
    if (!helpOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && !helpWrapperRef.current?.contains(target)) {
        closeHelpPopover(setHelpOpen, helpButtonRef.current);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [helpOpen]);

  useEffect(() => {
    if (!helpOpen) return;
    const first = helpPanelRef.current?.querySelector<HTMLElement>(
      'button, a[href], [tabindex]:not([tabindex="-1"])',
    );
    first?.focus();
  }, [helpOpen]);

  const isHome = current === "dashboard" || current === "home";
  const isLearning = current === "learning" || current === "course";
  const isDiscover = current === "discover";
  const isProgress = current === "progress";
  const isNotifications = current === "notifications";
  const isProfile = current === "profile";
  const isSettings = current === "settings";

  const effectiveDisplayName = identity.displayName;
  const effectiveTenantIdentity = tenantIdentity ?? DEFAULT_TENANT_IDENTITY;

  const workspaceSections: SidebarNavSection[] = [
    {
      id: "workspace",
      items: [
        {
          id: "dashboard",
          label: "Dashboard",
          href: ROUTES.dashboard,
          current: isHome,
          icon: (
            <LayoutDashboard size={20} strokeWidth={1.85} aria-hidden="true" />
          ),
          title: "Dashboard",
        },
        {
          id: "learning",
          label: "My Learning",
          href: learningHref,
          current: isLearning,
          icon: <BookOpen size={20} strokeWidth={1.85} aria-hidden="true" />,
          title: "My Learning",
          children: learningChildren,
        },
        {
          id: "discover",
          label: "Discover",
          href: ROUTES.discover,
          current: isDiscover,
          icon: <Compass size={20} strokeWidth={1.85} aria-hidden="true" />,
          title: "Discover",
        },
        {
          id: "progress",
          label: "Progress",
          href: ROUTES.progress,
          current: isProgress,
          icon: <BarChart2 size={20} strokeWidth={1.85} aria-hidden="true" />,
          title: "Progress",
        },
        {
          id: "notifications",
          label: "Notifications",
          href: ROUTES.notifications,
          current: isNotifications,
          icon: <Bell size={20} strokeWidth={1.85} aria-hidden="true" />,
          title: "Notifications",
        },
      ],
    },
    {
      id: "account",
      label: "Account",
      items: [
        {
          id: "profile",
          label: "Profile",
          href: ROUTES.profile,
          current: isProfile,
          icon: <User size={20} strokeWidth={1.85} aria-hidden="true" />,
          title: "Profile",
        },
        {
          id: "settings",
          label: "Settings",
          href: ROUTES.settings,
          current: isSettings,
          icon: <Settings size={20} strokeWidth={1.85} aria-hidden="true" />,
          title: "Settings",
        },
        {
          id: "help",
          label: "Help",
          href: SUPPORT_MAILTO,
          icon: <HelpCircle size={20} strokeWidth={1.85} aria-hidden="true" />,
          title: "Help",
          external: true,
        },
      ],
    },
  ];

  const computedSections = navSections ?? workspaceSections;

  return (
    <div
      className={`site-frame site-frame--learner${
        sidebarCollapsed ? " site-frame--collapsed" : ""
      }${className ? ` ${className}` : ""}`}
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      {/* Desktop Persistent Sidebar */}
      <aside
        id="learner-sidebar"
        className="learner-sidebar"
        aria-label="Learner workspace navigation"
      >
        <div className="learner-sidebar__header">
          <div className="learner-sidebar__brand">
            <TenantIdentity
              identity={effectiveTenantIdentity}
              collapsed={sidebarCollapsed}
            />
          </div>
          <SidebarCollapseButton
            collapsed={sidebarCollapsed}
            onToggle={toggleSidebar}
            aria-expanded={!sidebarCollapsed}
            aria-controls="learner-sidebar"
            className="learner-sidebar-toggle"
          />
        </div>

        <TenantSwitcher
          currentTenantId={tenantConfig?.currentTenantId ?? "tenant-1"}
          tenants={
            tenantConfig?.tenants ?? [
              { id: "tenant-1", name: effectiveTenantIdentity.tenantName },
            ]
          }
          onSelectTenant={tenantConfig?.onSelectTenant}
          collapsed={sidebarCollapsed}
        />

        <div className="learner-sidebar__search-row">
          <button
            ref={sidebarSearchTriggerRef}
            type="button"
            className="learner-sidebar__search-trigger"
            onClick={(e) => openCommandPalette(e.currentTarget)}
            aria-label="Search courses, lessons, and more (Cmd+K)"
            title={sidebarCollapsed ? "Search (⌘K)" : undefined}
          >
            <Search
              size={17}
              strokeWidth={1.85}
              aria-hidden="true"
              className="learner-sidebar__search-icon"
            />
            {!sidebarCollapsed ? (
              <>
                <span className="learner-sidebar__search-text">Search</span>
                <kbd className="learner-sidebar__search-kbd">⌘K</kbd>
              </>
            ) : null}
          </button>
        </div>

        <div className="learner-sidebar__content">
          <SidebarNav
            sections={computedSections}
            collapsed={sidebarCollapsed}
          />
        </div>

        <div className="learner-sidebar__footer">
          <div className="learner-sidebar__account">
            <SidebarTooltip
              active={sidebarCollapsed}
              content={`Profile: ${effectiveDisplayName}`}
            >
              <Link
                href={ROUTES.profile}
                className="learner-sidebar__account-link"
                title="Profile"
                aria-label={`Learner profile: ${effectiveDisplayName}`}
              >
                <IdentityAvatar
                  className="learner-sidebar__account-avatar"
                  displayName={effectiveDisplayName}
                  avatarUrl={identity.avatarUrl}
                  avatarAlt={identity.avatarAlt}
                />
                {!sidebarCollapsed ? (
                  <div className="learner-sidebar__account-info">
                    <span className="learner-sidebar__account-name">
                      {effectiveDisplayName}
                    </span>
                    <span
                      className="learner-sidebar__account-sub"
                      title={identity.email || "Learner"}
                    >
                      Learner
                    </span>
                  </div>
                ) : null}
              </Link>
            </SidebarTooltip>
            {!sidebarCollapsed ? (
              <Link
                href={ROUTES.settings}
                className="learner-sidebar__account-settings-btn"
                aria-label="Settings"
                title="Settings"
              >
                <Settings size={18} strokeWidth={1.85} aria-hidden="true" />
              </Link>
            ) : null}
          </div>
        </div>
      </aside>

      {/* Compact Utility Header */}
      <header className="learner-header">
        <div className="learner-header__inner">
          <div className="learner-header__mobile-brand">
            <Link
              className="mobile-brand-link"
              href={ROUTES.dashboard}
              prefetch={false}
              aria-label="Closers Academy — by Authority Closers"
            >
              <div className="mobile-brand-icon" aria-hidden="true">
                <BrandMark className="mobile-brand-mark" />
              </div>
              <div className="mobile-brand-text">
                <span className="mobile-brand-name">Closers Academy</span>
                <span className="mobile-brand-tenant">
                  by Authority Closers
                </span>
              </div>
            </Link>
          </div>

          <div className="learner-header__search-slot">
            <Link
              ref={searchTriggerRef}
              href={ROUTES.discover}
              prefetch={false}
              className="learner-header__search-trigger"
              aria-label="Search courses, lessons, and more (Cmd+K)"
              onClick={(e) => {
                e.preventDefault();
                openCommandPalette(e.currentTarget);
              }}
            >
              <Search size={16} aria-hidden="true" />
              <span>Search for courses, lessons, and more</span>
              <kbd className="search-shortcut-badge">⌘ K</kbd>
            </Link>
          </div>

          <div className="learner-header__actions">
            <Link
              ref={mobileSearchTriggerRef}
              href={ROUTES.discover}
              prefetch={false}
              className="mobile-header-icon-button"
              aria-label="Search courses, lessons, and more"
              onClick={(e) => {
                e.preventDefault();
                openCommandPalette(e.currentTarget);
              }}
            >
              <Search size={18} aria-hidden="true" />
            </Link>
            <div className="notification-dropdown-wrapper">
              <button
                type="button"
                className="header-icon-button notification-bell-button"
                ref={notificationButtonRef}
                onClick={() => {
                  setAccountMenuOpen(false);
                  setHelpOpen(false);
                  const nextOpen = !notificationPopoverOpen;
                  setNotificationPopoverOpen(nextOpen);
                }}
                aria-expanded={notificationPopoverOpen}
                aria-controls="learner-notifications-popover"
                aria-haspopup="dialog"
                aria-label="Notifications"
              >
                <Bell size={18} aria-hidden="true" />
              </button>

              {notificationPopoverOpen ? (
                <NotificationPopover
                  panelRef={notificationPopoverRef}
                  onClose={() =>
                    closeNotificationPopover(
                      setNotificationPopoverOpen,
                      notificationButtonRef.current,
                    )
                  }
                />
              ) : null}
            </div>

            <div className="account-dropdown-wrapper">
              <button
                type="button"
                className="learner-profile-button"
                ref={accountButtonRef}
                onClick={() => {
                  setNotificationPopoverOpen(false);
                  setHelpOpen(false);
                  setAccountMenuOpen((open) => !open);
                }}
                aria-expanded={accountMenuOpen}
                aria-controls="learner-account-menu"
                aria-haspopup="menu"
                aria-label={`Account menu for ${effectiveDisplayName}`}
              >
                <IdentityAvatar
                  className="learner-profile__avatar"
                  displayName={effectiveDisplayName}
                  avatarUrl={identity.avatarUrl}
                  avatarAlt={identity.avatarAlt}
                />
                <span className="learner-profile__name">
                  {effectiveDisplayName}
                </span>
                <ChevronDown
                  size={14}
                  aria-hidden="true"
                  className="learner-profile__chevron"
                />
              </button>

              {accountMenuOpen ? (
                <div
                  id="learner-account-menu"
                  ref={accountMenuRef}
                  className="account-menu-popover"
                  role="menu"
                  tabIndex={-1}
                  aria-labelledby="learner-account-menu-title"
                  aria-label="Account options"
                  onKeyDown={handleAccountMenuKeyDown}
                >
                  <div className="account-menu-header">
                    <div className="account-menu-identity">
                      <IdentityAvatar
                        className="account-menu-avatar"
                        displayName={effectiveDisplayName}
                        avatarUrl={identity.avatarUrl}
                        avatarAlt={identity.avatarAlt}
                      />
                      <div className="account-menu-header__copy">
                        <strong id="learner-account-menu-title">
                          {effectiveDisplayName}
                        </strong>
                        {identity.email ? (
                          <span className="account-menu-email">
                            {identity.email}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <span className="account-menu-scope">Learner account</span>
                  </div>
                  <div className="account-menu-links">
                    <Link
                      href={ROUTES.profile}
                      prefetch={false}
                      role="menuitem"
                      tabIndex={-1}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <User size={15} aria-hidden="true" /> Profile & Identity
                    </Link>
                    <Link
                      href={ROUTES.settings}
                      prefetch={false}
                      role="menuitem"
                      tabIndex={-1}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <Settings size={15} aria-hidden="true" /> Settings &
                      Appearance
                    </Link>
                    <Link
                      href={ROUTES.notifications}
                      prefetch={false}
                      role="menuitem"
                      tabIndex={-1}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <Bell size={15} aria-hidden="true" /> Notifications
                    </Link>
                    <a
                      href={SUPPORT_MAILTO}
                      role="menuitem"
                      tabIndex={-1}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <HelpCircle size={15} aria-hidden="true" /> Help & Support
                    </a>
                  </div>
                  <div className="account-menu-footer">
                    <SignOutControl
                      className="menu-sign-out-link"
                      role="menuitem"
                      tabIndex={-1}
                    />
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Surface */}
      {children}

      {/* Help chatbox shell. Conversation state is intentionally not
          fabricated until a support provider is connected. */}
      <div className="learner-help-widget" ref={helpWrapperRef}>
        <button
          type="button"
          className="learner-help-chatbox__trigger"
          ref={helpButtonRef}
          onClick={() => {
            const nextOpen = !helpOpen;
            setHelpOpen(nextOpen);
            setNotificationPopoverOpen(false);
            setAccountMenuOpen(false);
          }}
          aria-expanded={helpOpen}
          aria-controls="learner-help-chatbox"
          aria-haspopup="dialog"
          aria-label="Open help chatbox"
          title="Help"
        >
          <MessageCircle size={19} aria-hidden="true" />
          <span>Help</span>
        </button>

        {helpOpen ? (
          <div
            id="learner-help-chatbox"
            ref={helpPanelRef}
            className="learner-help-chatbox"
            role="dialog"
            aria-modal="false"
            aria-labelledby="learner-help-chatbox-title"
            tabIndex={-1}
          >
            <div className="learner-help-chatbox__header">
              <div>
                <p className="kicker">Learner support</p>
                <h2 id="learner-help-chatbox-title">How can we help?</h2>
              </div>
              <button
                type="button"
                className="learner-help-chatbox__close"
                onClick={() => {
                  closeHelpPopover(setHelpOpen, helpButtonRef.current);
                }}
                aria-label="Close help chatbox"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>
            <div className="learner-help-chatbox__body">
              <div className="learner-help-chatbox__availability" role="status">
                <span
                  className="learner-help-chatbox__availability-dot"
                  aria-hidden="true"
                />
                <span>Email support is available</span>
              </div>
              <div className="learner-help-chatbox__message">
                <span
                  className="learner-help-chatbox__avatar"
                  aria-hidden="true"
                >
                  <BrandMark className="learner-help-chatbox__brand-mark" />
                </span>
                <p>
                  In-app chat is not connected in this workspace yet. Email the
                  learner support team when you need a human response, and
                  include the page you were on.
                </p>
              </div>
              <a
                className="learner-help-chatbox__email"
                href={SUPPORT_MAILTO}
                onClick={() =>
                  closeHelpPopover(setHelpOpen, helpButtonRef.current)
                }
              >
                Email learner support{" "}
                <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            </div>
          </div>
        ) : null}
      </div>

      {/* Mobile Bottom Navigation (Direction A: 5-items) */}
      <MobileBottomNav
        current={current}
        learningHref={learningHref}
        moreOpen={mobileDrawerOpen}
        onToggleMore={() => {
          setNotificationPopoverOpen(false);
          setAccountMenuOpen(false);
          setHelpOpen(false);
          setMobileDrawerOpen((open) => !open);
        }}
        moreButtonRef={moreButtonRef}
      />

      {/* Mobile "More" Drawer / Bottom Sheet */}
      <MobileMoreSheet
        open={mobileDrawerOpen}
        onClose={() => setMobileDrawerOpen(false)}
        userDisplayName={effectiveDisplayName}
        moreButtonRef={moreButtonRef}
        avatarSlot={
          <IdentityAvatar
            className="user-avatar-badge"
            displayName={effectiveDisplayName}
            avatarUrl={identity.avatarUrl}
            avatarAlt={identity.avatarAlt}
          />
        }
      />

      {/* Real Searchable Command Palette with Ctrl/Cmd+K, Escape, Focus Restore, and G Shortcuts */}
      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => {
          setCommandPaletteOpen(false);
          setCommandPaletteInvoker(null);
        }}
        learningHref={learningHref}
        triggerRef={searchTriggerRef}
        invokingElement={commandPaletteInvoker}
      />
    </div>
  );
}

export const AppShell = LearnerShell;

export function Breadcrumbs({
  items,
}: {
  items: Array<{ label: string; href?: string }>;
}) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <ol>
        <li>
          <Link href={ROUTES.learnerHome} aria-label="Back to learner home">
            <ArrowLeft size={14} aria-hidden="true" />
            <span>Home</span>
          </Link>
        </li>
        {items.map((item, index) => (
          <li key={item.label}>
            <span className="breadcrumbs__separator" aria-hidden="true">
              /
            </span>
            {item.href ? (
              <Link href={item.href}>{item.label}</Link>
            ) : (
              <span
                aria-current={index === items.length - 1 ? "page" : undefined}
              >
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
