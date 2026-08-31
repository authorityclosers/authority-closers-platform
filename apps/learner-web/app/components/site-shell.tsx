import {
  ArrowLeft,
  ArrowUpRight,
  Bell,
  BookOpen,
  ChevronDown,
  CircleHelp,
  Home,
  Library,
  Menu,
  Medal,
  Search,
} from "lucide-react";
import Link from "next/link";

import { BrandMark } from "@ac/ui";

import { ROUTES } from "../lib/routes";

type PublicCurrent = "home" | "program";
type LearnerCurrent = "home" | "course" | "certificate" | "none";

function BrandLink({ href = ROUTES.home }: { href?: string }) {
  return (
    <Link className="brand" href={href} aria-label="Authority Closers home">
      <BrandMark className="brand-mark" />
      <span>Authority Closers</span>
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
          <p>v0.1 alpha · browser-first learning foundation.</p>
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
}: {
  href: string;
  label: string;
  current: boolean;
  icon: React.ReactNode;
}) {
  return (
    <Link
      className={`learner-nav__link${current ? " is-current" : ""}`}
      href={href}
      aria-current={current ? "page" : undefined}
    >
      {icon}
      <span>{label}</span>
    </Link>
  );
}

function LearnerSideItem({
  label,
  icon,
  current = false,
}: {
  label: string;
  icon: React.ReactNode;
  current?: boolean;
}) {
  return (
    <span
      className={`learner-sidebar__item${current ? " is-current" : ""}`}
      aria-disabled="true"
      aria-current={current ? "page" : undefined}
    >
      {icon}
      <span>{label}</span>
    </span>
  );
}

export function LearnerShell({
  children,
  current = "home",
}: {
  children?: React.ReactNode;
  current?: LearnerCurrent;
}) {
  return (
    <div className="site-frame site-frame--learner">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside
        className="learner-sidebar"
        aria-label="Learner workspace navigation"
      >
        <div className="learner-sidebar__brand">
          <BrandLink href={ROUTES.learnerHome} />
          <span className="learner-sidebar__version">v0.1</span>
        </div>
        <nav className="learner-sidebar__nav" aria-label="Learner sections">
          <LearnerNavLink
            href={ROUTES.learnerHome}
            label="Home"
            current={current === "home"}
            icon={<Home size={18} aria-hidden="true" />}
          />
          <LearnerSideItem
            label="My learning"
            icon={<BookOpen size={18} aria-hidden="true" />}
            current={current === "course"}
          />
          <LearnerSideItem
            label="Library"
            icon={<Library size={18} aria-hidden="true" />}
          />
          <LearnerSideItem
            label="Progress"
            icon={<Medal size={18} aria-hidden="true" />}
          />
        </nav>
        <div className="learner-sidebar__footer">
          <LearnerSideItem
            label="More"
            icon={<CircleHelp size={18} aria-hidden="true" />}
          />
          <span className="learner-sidebar__collapse">Collapse</span>
        </div>
      </aside>
      <header className="learner-header">
        <div className="learner-header__inner">
          <div className="learner-header__mobile-brand">
            <BrandLink href={ROUTES.learnerHome} />
            <span className="learner-sidebar__version">v0.1</span>
          </div>
          <button
            className="learner-header__menu"
            type="button"
            aria-label="Learner navigation menu is unavailable in this alpha"
            disabled
          >
            <Menu size={20} aria-hidden="true" />
          </button>
          <label className="learner-search" htmlFor="learner-search">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">Search courses and lessons</span>
            <input
              id="learner-search"
              type="search"
              placeholder="Search courses, lessons, topics"
              aria-label="Search is unavailable in this alpha"
              disabled
            />
          </label>
          <div className="learner-header__actions">
            <button
              type="button"
              className="icon-button"
              aria-label="Help is unavailable in this alpha"
              disabled
            >
              <CircleHelp size={19} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="icon-button learner-notifications"
              aria-label="Notifications are unavailable in this alpha"
              disabled
            >
              <Bell size={19} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="learner-profile"
              aria-label="Profile menu is unavailable in this alpha"
              disabled
            >
              <span className="learner-profile__avatar" aria-hidden="true">
                AC
              </span>
              <span className="learner-profile__label">Profile</span>
              <ChevronDown size={15} aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>
      <nav
        className="learner-bottom-nav"
        aria-label="Learner mobile navigation"
      >
        <LearnerNavLink
          href={ROUTES.learnerHome}
          label="Home"
          current={current === "home"}
          icon={<Home size={21} aria-hidden="true" />}
        />
        <LearnerSideItem
          label="Library"
          icon={<Library size={21} aria-hidden="true" />}
        />
        <LearnerSideItem
          label="Practice"
          icon={<BookOpen size={21} aria-hidden="true" />}
          current={current === "course"}
        />
        <LearnerSideItem
          label="Progress"
          icon={<Medal size={21} aria-hidden="true" />}
        />
        <LearnerSideItem
          label="More"
          icon={<Menu size={21} aria-hidden="true" />}
        />
      </nav>
      {children}
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
