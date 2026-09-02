"use client";

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
  MoreHorizontal,
  Search,
  Settings,
  User,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BrandMark } from "@ac/ui";

import { ROUTES } from "../lib/routes";
import { SignOutControl } from "./sign-out-control";

export type PublicCurrent = "home" | "program";
export type LearnerCurrent =
  | "dashboard"
  | "home"
  | "learning"
  | "discover"
  | "progress"
  | "notifications"
  | "profile"
  | "settings"
  | "course"
  | "certificate"
  | "none";

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

export function LearnerShell({
  children,
  current = "dashboard",
  learningHref = ROUTES.learning,
  userDisplayName = "Learner",
}: {
  children?: React.ReactNode;
  current?: LearnerCurrent;
  learningHref?: string;
  userDisplayName?: string;
}) {
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

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
  }, [mobileDrawerOpen, accountMenuOpen]);

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

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Node &&
        !accountMenuRef.current?.contains(target) &&
        !accountButtonRef.current?.contains(target)
      ) {
        setAccountMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [accountMenuOpen]);

  const isHome = current === "dashboard" || current === "home";
  const isLearning = current === "learning" || current === "course";
  const isDiscover = current === "discover";
  const isProgress = current === "progress";
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
          : isNotifications
            ? "Notifications"
            : isProfile
              ? "Learner Profile"
              : isSettings
                ? "Settings"
                : current === "certificate"
                  ? "Certificate"
                  : "Workspace";

  const initials = userDisplayName
    ? userDisplayName
        .split(" ")
        .map((part) => part[0])
        .filter(Boolean)
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "SR";

  return (
    <div
      className={`site-frame site-frame--learner${
        sidebarCollapsed ? " site-frame--collapsed" : ""
      }`}
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      {/* Desktop Persistent Sidebar */}
      <aside
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
            aria-label={`Open profile for ${userDisplayName}`}
            title={userDisplayName}
          >
            <span className="user-avatar-badge" aria-hidden="true">
              {initials}
            </span>
            <div className="user-pill__copy">
              <span className="user-pill__name">{userDisplayName}</span>
              <span className="user-pill__role">Learner</span>
            </div>
          </Link>

          <button
            type="button"
            className="sidebar-collapse-btn"
            onClick={() => setSidebarCollapsed((c) => !c)}
            aria-label={
              sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"
            }
            aria-expanded={!sidebarCollapsed}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <ChevronDown
              size={16}
              aria-hidden="true"
              className="sidebar-collapse-icon"
            />
            <span>Collapse</span>
          </button>
        </div>
      </aside>

      {/* Compact Utility Header */}
      <header className="learner-header">
        <div className="learner-header__inner">
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
            <Link
              href={ROUTES.notifications}
              className="header-icon-button"
              aria-label="Notifications"
            >
              <Bell size={18} aria-hidden="true" />
            </Link>

            <div className="account-dropdown-wrapper">
              <button
                type="button"
                className="learner-profile-button"
                ref={accountButtonRef}
                onClick={() => setAccountMenuOpen((open) => !open)}
                aria-expanded={accountMenuOpen}
                aria-controls="learner-account-menu"
                aria-haspopup="menu"
                aria-label={`Account menu for ${userDisplayName}`}
              >
                <span className="learner-profile__avatar" aria-hidden="true">
                  {initials}
                </span>
                <span className="learner-profile__name">{userDisplayName}</span>
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
                  aria-labelledby="learner-account-menu-title"
                  aria-label="Account options"
                >
                  <div className="account-menu-header">
                    <strong id="learner-account-menu-title">
                      {userDisplayName}
                    </strong>
                    <span>Learner account</span>
                  </div>
                  <div className="account-menu-links">
                    <Link
                      href={ROUTES.profile}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <User size={15} aria-hidden="true" /> Profile & Identity
                    </Link>
                    <Link
                      href={ROUTES.settings}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <Settings size={15} aria-hidden="true" /> Settings &
                      Appearance
                    </Link>
                    <Link
                      href={ROUTES.notifications}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <Bell size={15} aria-hidden="true" /> Notifications
                    </Link>
                    <a
                      href={SUPPORT_MAILTO}
                      onClick={() => setAccountMenuOpen(false)}
                    >
                      <HelpCircle size={15} aria-hidden="true" /> Help & Support
                    </a>
                  </div>
                  <div className="account-menu-footer">
                    <SignOutControl className="menu-sign-out-link" />
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Surface */}
      {children}

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
          onClick={() => setMobileDrawerOpen((open) => !open)}
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
                <span className="user-avatar-badge" aria-hidden="true">
                  {initials}
                </span>
                <div>
                  <strong id="learner-more-title">{userDisplayName}</strong>
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
