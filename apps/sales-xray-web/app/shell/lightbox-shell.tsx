"use client";

import {
  CircleUserRound,
  FolderOpen,
  LogIn,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import type { Allowance } from "../acquisition-client";
import { Glyph } from "../lightbox/glyph";
import { LocalSettingsButton } from "../live-data-banner";
import { newCallHref } from "../new-call-navigation";
import { ProfileMenu } from "../profile-menu";
import { useWorkspaceAccess } from "../workspace-access";
import { BrandLockup } from "./brand-lockup";
import { HelpMenu } from "./help-menu";
import { MinutesMeter } from "./minutes-meter";
import styles from "./lightbox-shell.module.css";

export type LightboxShellProps = {
  children: ReactNode;
  authenticated: boolean;
  homeHref?: string;
  active?: "analyse" | "calls";
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
      description:
        "Your call is saved. Review the next step to start analysis.",
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
  if (stage === "welcome") return { title: "New analysis" };
  return null;
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
}: LightboxShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const access = useWorkspaceAccess();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const hasToggled = useRef(false);
  const accountHref = authenticated ? "/calls" : "/login";
  const accountLabel = authenticated
    ? "Account & saved calls"
    : "Profile & account";
  const visibleHero = heroStage ?? (welcome ? "welcome" : undefined);
  const heading = compactBusy ? null : pageHeading(visibleHero, previewHero);

  useEffect(() => {
    if (!hasToggled.current) return;
    toggleRef.current?.focus();
  }, [collapsed]);

  // Guests keep their staged file mounted: sign-in opens in place when possible.
  function openAccount(event: MouseEvent<HTMLAnchorElement>) {
    if (!authenticated && access?.requestAccountSignIn) {
      event.preventDefault();
      access.requestAccountSignIn();
    }
  }

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
        className={styles.rail}
        aria-label="Sales Xray navigation"
      >
        <div className={styles.railTop}>
          <BrandLockup href={homeHref} />
          <button
            ref={toggleRef}
            type="button"
            className={styles.toggle}
            aria-label={
              collapsed
                ? "Expand Sales Xray navigation"
                : "Collapse Sales Xray navigation"
            }
            aria-controls="sales-xray-sidebar"
            aria-expanded={!collapsed}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
            onClick={() => {
              hasToggled.current = true;
              setCollapsed((value) => !value);
            }}
          >
            {collapsed ? (
              <PanelLeftOpen size={18} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={18} aria-hidden="true" />
            )}
          </button>
        </div>
        <nav className={styles.nav} aria-label="Workspace">
          {/* Full navigation resets a restored call even on the same route. */}
          <Link
            className={styles.newAnalysis}
            href={newAnalysisHref}
            aria-current={active === "analyse" ? "page" : undefined}
          >
            <Plus size={18} aria-hidden="true" />
            <span>New analysis</span>
          </Link>
          <Link
            className={styles.navLink}
            href="/calls"
            aria-current={active === "calls" ? "page" : undefined}
          >
            <FolderOpen size={19} strokeWidth={1.75} aria-hidden="true" />
            <span>Calls</span>
          </Link>
          <Link
            className={styles.navLink}
            href={accountHref}
            onClick={openAccount}
          >
            <CircleUserRound size={19} strokeWidth={1.75} aria-hidden="true" />
            <span>{accountLabel}</span>
          </Link>
          <LocalSettingsButton className={styles.navLink} />
        </nav>
        <div className={styles.railSpacer} />
        <div className={styles.railMeter}>
          <MinutesMeter allowance={allowance} />
        </div>
        <div className={styles.railAccount}>
          <ProfileMenu
            authenticated={authenticated}
            accountHref={accountHref}
            placement="above"
            compact={collapsed}
          />
          {!authenticated && (
            <Link
              className={styles.signIn}
              href="/login"
              onClick={(event) => {
                if (access?.requestAccountSignIn) {
                  event.preventDefault();
                  access.requestAccountSignIn();
                }
              }}
            >
              <LogIn size={16} aria-hidden="true" />
              <span>Sign in to analyse calls</span>
            </Link>
          )}
        </div>
      </aside>
      <div className={styles.content}>
        <header className={styles.mobileBar}>
          <BrandLockup href={homeHref} />
          <div className={styles.barActions}>
            <MinutesMeter allowance={allowance} variant="pill" />
            <HelpMenu />
            <ProfileMenu
              authenticated={authenticated}
              accountHref={accountHref}
            />
          </div>
        </header>
        <header className={styles.topBar}>
          <span className={styles.crumb}>
            {active === "calls" ? "Calls" : null}
          </span>
          <div className={styles.barActions}>
            {authenticated ? (
              <span className={styles.trust}>
                <Glyph name="shield" size={15} />
                Private to your account
              </span>
            ) : null}
            <HelpMenu />
          </div>
        </header>
        {heading ? (
          <div className={styles.pageHeading}>
            <h1>{heading.title}</h1>
            {heading.description ? <p>{heading.description}</p> : null}
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
        >
          <CircleUserRound size={20} aria-hidden="true" />
          <span>{authenticated ? "Account" : "Profile"}</span>
        </Link>
        <LocalSettingsButton className={styles.bottomLink} />
      </nav>
    </div>
  );
}
