"use client";

/* Avatar delivery URLs are signed and provider-owned at runtime. */
/* eslint-disable @next/next/no-img-element */

import {
  ArrowLeft,
  ArrowUpRight,
  BarChart2,
  Bell,
  BookOpen,
  CalendarDays,
  ChevronDown,
  Compass,
  HelpCircle,
  Info,
  LayoutDashboard,
  MoreHorizontal,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  User,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BrandMark } from "@ac/ui";

import { createLearnerApi } from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import { SignOutControl } from "./sign-out-control";

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

function LearnerSidebarBrand() {
  return (
    <Link
      className="learner-sidebar-wordmark"
      href={ROUTES.dashboard}
      aria-label="Authority Closers home"
    >
      <span className="brand-title-full">
        <span>Authority</span>
        <span>Closers</span>
      </span>
    </Link>
  );
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
      aria-current={current ? "page" : undefined}
      onClick={onClick}
      title={title ?? label}
    >
      <span className="learner-nav__icon" aria-hidden="true">
        {icon}
      </span>
      <span>{label}</span>
    </Link>
  );
}

const SUPPORT_MAILTO =
  "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20Learner%20Support";

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
  className?: string;
};

export type AppShellProps = LearnerShellProps;

export function initialsForDisplayName(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "AC";
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "";
  return `${first}${last}`.toUpperCase() || "AC";
}

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

  return (
    <span className={className} aria-hidden="true">
      {avatarUrl && avatarUrl !== failedAvatarUrl ? (
        <img
          className="learner-identity-avatar__image"
          src={avatarUrl}
          alt={avatarAlt}
          onError={() => setFailedAvatarUrl(avatarUrl)}
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
  className = "",
}: LearnerShellProps) {
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [notificationPopoverOpen, setNotificationPopoverOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [identity, setIdentity] = useState({
    displayName: userDisplayName,
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
  const drawerRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const toastTimerRef = useRef<number | undefined>(undefined);
  const avatarUpdateGenerationRef = useRef(0);

  function showToast(message: string): void {
    setToast(message);
    if (toastTimerRef.current !== undefined) {
      window.clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = window.setTimeout(() => {
      setToast(null);
      toastTimerRef.current = undefined;
    }, 3400);
  }

  function toggleSidebar(): void {
    setSidebarCollapsed((collapsed) => !collapsed);
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
  }, [userDisplayName]);

  useEffect(() => {
    const handleToastEvent = (e: Event) => {
      if (e instanceof CustomEvent && typeof e.detail === "string") {
        showToast(e.detail);
      }
    };
    window.addEventListener("ac-toast", handleToastEvent);
    return () => {
      window.removeEventListener("ac-toast", handleToastEvent);
      if (toastTimerRef.current !== undefined) {
        window.clearTimeout(toastTimerRef.current);
      }
    };
  }, []);

  // Close mobile drawer on route change or ESC; activate search on Cmd+K
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (mobileDrawerOpen) {
          setMobileDrawerOpen(false);
        }
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
      } else if (
        (e.metaKey || e.ctrlKey) &&
        e.key.toLowerCase() === "k" &&
        !e.defaultPrevented
      ) {
        const searchEl = document.querySelector<HTMLAnchorElement>(
          ".learner-header__search-trigger",
        );
        if (searchEl) {
          e.preventDefault();
          searchEl.click();
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mobileDrawerOpen, accountMenuOpen, notificationPopoverOpen, helpOpen]);

  useEffect(() => {
    if (!mobileDrawerOpen) {
      restoreFocusRef.current?.focus();
      restoreFocusRef.current = null;
      return;
    }

    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : moreButtonRef.current;

    const background = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".site-frame--learner > *:not(.mobile-drawer-overlay)",
      ),
    );
    const previouslyInert = new Map<HTMLElement, string | null>();
    background.forEach((element) => {
      previouslyInert.set(element, element.getAttribute("inert"));
      element.setAttribute("inert", "");
    });

    const focusableSelector =
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusFirst = () => {
      const first =
        drawerRef.current?.querySelector<HTMLElement>(focusableSelector);
      first?.focus();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = drawerRef.current
        ? Array.from(
            drawerRef.current.querySelectorAll<HTMLElement>(focusableSelector),
          )
        : [];
      if (focusable.length === 0) {
        event.preventDefault();
        drawerRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    focusFirst();
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyInert.forEach((value, element) => {
        if (value === null) element.removeAttribute("inert");
        else element.setAttribute("inert", value);
      });
    };
  }, [mobileDrawerOpen]);

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
  const isCalendar = current === "calendar";
  const isNotifications = current === "notifications";
  const isProfile = current === "profile";
  const isSettings = current === "settings";
  const isMore = isNotifications || isProfile || isSettings;

  const currentTitle = isHome
    ? "Dashboard"
    : isLearning
      ? "My Learning"
      : isDiscover
        ? "Discover"
        : isProgress
          ? "Progress"
          : isCalendar
            ? "Calendar"
            : isNotifications
              ? "Notifications"
              : isProfile
                ? "Learner Profile"
                : isSettings
                  ? "Settings"
                  : current === "certificate"
                    ? "Certificate"
                    : "Workspace";

  const effectiveDisplayName = identity.displayName;

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
        <div className="learner-sidebar__brand">
          <LearnerSidebarBrand />
        </div>

        <div className="learner-sidebar__content">
          <p className="learner-sidebar__section-label">Workspace</p>
          <nav
            className="learner-sidebar__nav"
            aria-label="Learner workspace sections"
          >
            <LearnerNavLink
              href={ROUTES.dashboard}
              label="Dashboard"
              current={isHome}
              icon={<LayoutDashboard size={19} aria-hidden="true" />}
            />
            <LearnerNavLink
              href={learningHref}
              label="My Learning"
              current={isLearning}
              icon={<BookOpen size={19} aria-hidden="true" />}
            />
            <LearnerNavLink
              href={ROUTES.discover}
              label="Discover"
              current={isDiscover}
              icon={<Compass size={19} aria-hidden="true" />}
            />
            <LearnerNavLink
              href={ROUTES.progress}
              label="Progress"
              current={isProgress}
              icon={<BarChart2 size={19} aria-hidden="true" />}
            />
            <LearnerNavLink
              href={ROUTES.notifications}
              label="Notifications"
              current={isNotifications}
              icon={
                <span className="nav-icon-badge-wrapper">
                  <Bell size={19} aria-hidden="true" />
                </span>
              }
            />
          </nav>

          <div className="learner-sidebar__account-group">
            <p className="learner-sidebar__section-label">Account</p>
            <nav className="learner-sidebar__nav" aria-label="Account sections">
              <LearnerNavLink
                href={ROUTES.profile}
                label="Profile"
                current={isProfile}
                icon={<User size={19} aria-hidden="true" />}
              />
              <LearnerNavLink
                href={ROUTES.settings}
                label="Settings"
                current={isSettings}
                icon={<Settings size={19} aria-hidden="true" />}
              />
              <a
                className="learner-nav__link"
                href={SUPPORT_MAILTO}
                aria-label="Contact support"
                title="Help"
              >
                <span className="learner-nav__icon" aria-hidden="true">
                  <HelpCircle size={19} />
                </span>
                <span>Help</span>
              </a>
            </nav>
          </div>
        </div>

        <div className="learner-sidebar__footer">
          <Link
            href={ROUTES.profile}
            className="learner-sidebar__user-pill"
            aria-label={`Open profile for ${effectiveDisplayName}`}
            title={effectiveDisplayName}
          >
            <IdentityAvatar
              className="user-avatar-badge"
              displayName={effectiveDisplayName}
              avatarUrl={identity.avatarUrl}
              avatarAlt={identity.avatarAlt}
            />
            <div className="user-pill__copy">
              <span className="user-pill__name">{effectiveDisplayName}</span>
              <span className="user-pill__role">Learner</span>
            </div>
          </Link>
        </div>
      </aside>

      {/* Compact Utility Header */}
      <header className="learner-header">
        <div className="learner-header__inner">
          <button
            type="button"
            className="learner-sidebar-toggle"
            onClick={toggleSidebar}
            aria-label={
              sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"
            }
            aria-expanded={!sidebarCollapsed}
            aria-controls="learner-sidebar"
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen size={18} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={18} aria-hidden="true" />
            )}
          </button>
          <div className="learner-header__mobile-brand">
            <Link
              className="mobile-brand-link"
              href={ROUTES.dashboard}
              aria-label="Authority Closers home"
            >
              <div className="mobile-brand-icon" aria-hidden="true">
                <BrandMark className="mobile-brand-mark" />
              </div>
              <span className="mobile-brand-name">Authority Closers</span>
            </Link>
          </div>

          <div className="learner-header__context">
            <strong>{currentTitle}</strong>
          </div>

          <div className="learner-header__search-slot">
            <Link
              href={ROUTES.discover}
              className="learner-header__search-trigger"
              aria-label="Search courses, lessons, and more"
            >
              <Search size={16} aria-hidden="true" />
              <span>Search for courses, lessons, and more</span>
              <kbd className="search-shortcut-badge">⌘ K</kbd>
            </Link>
          </div>

          <div className="learner-header__actions">
            <Link
              href={ROUTES.discover}
              className="mobile-header-icon-button"
              aria-label="Search courses, lessons, and more"
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
                <div
                  id="learner-notifications-popover"
                  ref={notificationPopoverRef}
                  className="notification-popover"
                  role="dialog"
                  aria-modal="false"
                  aria-labelledby="learner-notifications-popover-title"
                >
                  <div className="notification-popover__header">
                    <div className="notification-popover__title-row">
                      <h2
                        id="learner-notifications-popover-title"
                        className="notification-popover__title"
                      >
                        Notifications
                      </h2>
                      <span
                        className="notification-popover__status-badge"
                        role="status"
                      >
                        Unavailable
                      </span>
                    </div>
                    <p className="notification-popover__subhead">
                      Notification history is not available in this first-slice
                      workspace.
                    </p>
                  </div>

                  <div className="notification-popover__body">
                    <div
                      className="notification-popover__empty-icon"
                      aria-hidden="true"
                    >
                      <Bell size={24} />
                    </div>
                    <p className="notification-popover__empty-title">
                      No notifications to show
                    </p>
                    <p className="notification-popover__empty-copy">
                      This surface does not yet have a server-backed
                      notification source, so no alerts or read-state changes
                      are being presented here.
                    </p>
                  </div>

                  <div className="notification-popover__footer">
                    <Link
                      href={ROUTES.notifications}
                      className="notification-popover__action-link"
                      onClick={() => setNotificationPopoverOpen(false)}
                    >
                      View full notifications page
                    </Link>
                  </div>
                </div>
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
                    <strong id="learner-account-menu-title">
                      {effectiveDisplayName}
                    </strong>
                    <span>Learner account</span>
                  </div>
                  <div className="account-menu-links">
                    <Link
                      href={ROUTES.profile}
                      role="menuitem"
                      tabIndex={-1}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <User size={15} aria-hidden="true" /> Profile & Identity
                    </Link>
                    <Link
                      href={ROUTES.settings}
                      role="menuitem"
                      tabIndex={-1}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <Settings size={15} aria-hidden="true" /> Settings &
                      Appearance
                    </Link>
                    <Link
                      href={ROUTES.notifications}
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
              <div className="learner-help-chatbox__message">
                <span
                  className="learner-help-chatbox__avatar"
                  aria-hidden="true"
                >
                  AC
                </span>
                <p>
                  Live chat is not connected in this workspace yet. Send the
                  learner support team a note and include the page you were on.
                </p>
              </div>
              <a
                className="learner-help-chatbox__email"
                href={SUPPORT_MAILTO}
                onClick={() => setHelpOpen(false)}
              >
                Email learner support{" "}
                <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            </div>
          </div>
        ) : null}
      </div>

      {toast ? (
        <div
          className="learner-toast-region"
          aria-live="polite"
          aria-atomic="true"
        >
          <div className="learner-toast" role="status">
            <Info size={16} aria-hidden="true" />
            <span>{toast}</span>
          </div>
        </div>
      ) : null}

      {/* Mobile Bottom Navigation (Direction A: 5-items) */}
      <nav
        className="learner-bottom-nav"
        aria-label="Learner mobile navigation"
      >
        <LearnerNavLink
          href={ROUTES.dashboard}
          label="Home"
          current={isHome}
          icon={<LayoutDashboard size={20} aria-hidden="true" />}
        />
        <LearnerNavLink
          href={learningHref}
          label="Learning"
          current={isLearning}
          icon={<BookOpen size={20} aria-hidden="true" />}
        />
        <LearnerNavLink
          href={ROUTES.discover}
          label="Discover"
          current={isDiscover}
          icon={<Compass size={20} aria-hidden="true" />}
        />
        <LearnerNavLink
          href={ROUTES.progress}
          label="Progress"
          current={isProgress}
          icon={<BarChart2 size={20} aria-hidden="true" />}
        />
        <button
          type="button"
          className={`learner-nav__link${isMore || mobileDrawerOpen ? " is-current" : ""}`}
          ref={moreButtonRef}
          onClick={() => {
            setNotificationPopoverOpen(false);
            setAccountMenuOpen(false);
            setHelpOpen(false);
            setMobileDrawerOpen((open) => !open);
          }}
          aria-expanded={mobileDrawerOpen}
          aria-controls="learner-more-drawer"
          aria-current={isMore ? "page" : undefined}
          aria-haspopup="dialog"
          aria-label="More navigation options"
        >
          <span className="learner-nav__icon" aria-hidden="true">
            <MoreHorizontal size={20} />
          </span>
          <span>More</span>
        </button>
      </nav>

      {/* Mobile "More" Drawer / Bottom Sheet */}
      {mobileDrawerOpen ? (
        <div
          className="mobile-drawer-overlay"
          onClick={() => setMobileDrawerOpen(false)}
          role="presentation"
        >
          <div
            id="learner-more-drawer"
            ref={drawerRef}
            className="mobile-drawer-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="learner-more-title"
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mobile-drawer-header">
              <div className="mobile-drawer-user">
                <IdentityAvatar
                  className="user-avatar-badge"
                  displayName={effectiveDisplayName}
                  avatarUrl={identity.avatarUrl}
                  avatarAlt={identity.avatarAlt}
                />
                <div>
                  <strong id="learner-more-title">
                    {effectiveDisplayName}
                  </strong>
                  <span>Learner workspace</span>
                </div>
              </div>
              <button
                type="button"
                className="mobile-drawer-close"
                onClick={() => setMobileDrawerOpen(false)}
                aria-label="Close menu"
              >
                <X size={20} aria-hidden="true" />
              </button>
            </div>

            <nav
              className="mobile-drawer-nav"
              aria-label="Account and support navigation"
            >
              <Link
                href={ROUTES.profile}
                className="mobile-drawer-link"
                onClick={() => setMobileDrawerOpen(false)}
              >
                <User size={18} aria-hidden="true" />
                <span>Profile & Identity</span>
              </Link>
              <Link
                href={ROUTES.notifications}
                className="mobile-drawer-link"
                onClick={() => setMobileDrawerOpen(false)}
              >
                <Bell size={18} aria-hidden="true" />
                <span>Notifications</span>
              </Link>
              <Link
                href={ROUTES.calendar}
                className="mobile-drawer-link"
                onClick={() => setMobileDrawerOpen(false)}
              >
                <CalendarDays size={18} aria-hidden="true" />
                <span>Calendar</span>
              </Link>
              <Link
                href={ROUTES.settings}
                className="mobile-drawer-link"
                onClick={() => setMobileDrawerOpen(false)}
              >
                <Settings size={18} aria-hidden="true" />
                <span>Settings & Appearance</span>
              </Link>
              <a
                href={SUPPORT_MAILTO}
                className="mobile-drawer-link"
                onClick={() => setMobileDrawerOpen(false)}
              >
                <HelpCircle size={18} aria-hidden="true" />
                <span>Help & Support</span>
              </a>
              <SignOutControl className="mobile-drawer-link mobile-drawer-link--danger" />
            </nav>
          </div>
        </div>
      ) : null}
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
