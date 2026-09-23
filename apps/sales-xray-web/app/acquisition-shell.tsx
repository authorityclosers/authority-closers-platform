"use client";

import {
  ArrowUpRight,
  AudioLines,
  BookOpen,
  CircleUserRound,
  FolderOpen,
  LogIn,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { LocalSettingsButton } from "./live-data-banner";
import { ProfileMenu } from "./profile-menu";
import { newCallHref } from "./new-call-navigation";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./acquisition-shell.module.css";

export function AcquisitionShell({
  children,
  authenticated,
  homeHref = "/",
  active = "analyse",
  compactBusy = false,
  mobileFit = false,
  welcome = false,
  heroStage,
  displayName,
  previewHero = false,
}: {
  children: ReactNode;
  authenticated: boolean;
  homeHref?: string;
  active?: "analyse" | "calls";
  compactBusy?: boolean;
  mobileFit?: boolean;
  welcome?: boolean;
  heroStage?: "welcome" | "processing";
  /** A server-confirmed account name, when the caller has one. */
  displayName?: string | null;
  /** Label the explicit local review fixture without implying a real job. */
  previewHero?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const access = useWorkspaceAccess();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const hasToggled = useRef(false);
  const accountHref = authenticated ? "/calls" : "/login";
  const accountLabel = authenticated
    ? "Account & saved calls"
    : "Profile & account";
  const visibleHero = heroStage ?? (welcome ? "welcome" : undefined);

  useEffect(() => {
    if (!hasToggled.current) return;
    toggleRef.current?.focus();
  }, [collapsed]);

  return (
    <div
      className={`${styles.shell} ${collapsed ? styles.collapsed : ""}`}
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
        <div className={styles.sidebarTop}>
          <Link
            className={styles.brand}
            href={homeHref}
            aria-label="Sales Xray home"
          >
            <span className={styles.brandMark} aria-hidden="true">
              <Image
                src="/brand/ac-v0.1/symbol.svg"
                alt=""
                width={512}
                height={512}
                priority
              />
            </span>
            <span className={styles.brandWordmark} aria-hidden="true">
              <Image
                src="/brand/ac-v0.1/sales-xray-wordmark.svg"
                alt=""
                width={125}
                height={44}
                unoptimized
                priority
              />
            </span>
          </Link>
          <button
            ref={toggleRef}
            type="button"
            className={styles.sidebarToggle}
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
              <PanelLeftOpen size={17} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={17} aria-hidden="true" />
            )}
            <span className={styles.toggleText}>
              {collapsed ? "Expand" : "Collapse"}
            </span>
          </button>
        </div>
        <p className={styles.workspaceLabel}>CONVERSATION STUDIO</p>
        <nav className={styles.nav} aria-label="Workspace">
          {/* Full navigation resets a restored call even on the same route. */}
          <a
            className={`${styles.navLink} ${active === "analyse" ? styles.active : ""}`}
            href={newCallHref(homeHref)}
            aria-current={active === "analyse" ? "page" : undefined}
          >
            <AudioLines size={18} aria-hidden="true" />
            <span>Analyse a call</span>
          </a>
          <Link
            className={`${styles.navLink} ${active === "calls" ? styles.active : ""}`}
            href="/calls"
            aria-current={active === "calls" ? "page" : undefined}
          >
            <FolderOpen size={18} aria-hidden="true" />
            <span>Saved calls</span>
          </Link>
          <Link
            className={styles.navLink}
            href={accountHref}
            onClick={(event) => {
              if (!authenticated && access?.requestAccountSignIn) {
                event.preventDefault();
                access.requestAccountSignIn();
              }
            }}
          >
            <CircleUserRound size={18} aria-hidden="true" />
            <span>{accountLabel}</span>
          </Link>
          <LocalSettingsButton className={styles.navLink} />
        </nav>
        <details className={styles.sidebarHelp} id="sales-xray-help">
          <summary>
            <BookOpen size={32} strokeWidth={1.8} aria-hidden="true" />
            <h2>Need help?</h2>
            <p>Explore our guides, sample analysis, and best practices.</p>
            <span className={styles.helpAction}>
              View guides &amp; tips{" "}
              <ArrowUpRight size={17} aria-hidden="true" />
            </span>
          </summary>
          <ul>
            <li>Choose a supported audio file up to 32 MB.</li>
            <li>Review the language and privacy details before analysis.</li>
            <li>Open saved calls to revisit completed reports.</li>
          </ul>
        </details>
        <div className={styles.sidebarAccount}>
          <span className={styles.avatar} aria-hidden="true">
            {authenticated ? "AC" : "G"}
          </span>
          <span className={styles.accountCopy}>
            <strong>{authenticated ? "AC account" : "Guest workspace"}</strong>
            <small>
              {authenticated
                ? "Private workspace"
                : "Free analysis in this browser"}
            </small>
          </span>
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
              <LogIn size={15} aria-hidden="true" />
              Sign in to save calls
            </Link>
          )}
        </div>
      </aside>
      <div className={styles.content}>
        <header className={styles.mobileHeader}>
          <Link
            className={styles.mobileBrand}
            href={homeHref}
            aria-label="Sales Xray home"
          >
            <span className={styles.brandMark} aria-hidden="true">
              <Image
                src="/brand/ac-v0.1/symbol.svg"
                alt=""
                width={512}
                height={512}
                priority
              />
            </span>
            <span>
              <strong>Sales Xray</strong>
              <small>AUTHORITY CLOSERS</small>
            </span>
          </Link>
          <ProfileMenu
            authenticated={authenticated}
            accountHref={accountHref}
          />
        </header>
        <header className={styles.workspaceHeader}>
          {visibleHero && (
            <div className={styles.welcome}>
              <p className={styles.welcomeKicker}>TURN CALLS INTO CLARITY</p>
              {visibleHero === "processing" ? (
                <>
                  <h1>
                    {previewHero
                      ? "Example processing state"
                      : "Analysing your call"}{" "}
                    <AudioLines size={37} aria-hidden="true" />
                  </h1>
                  <p className={styles.welcomeDescription}>
                    {previewHero
                      ? "A read-only preview of how your call moves from upload to report."
                      : "We're processing your call and finding the key insights. This usually takes a few minutes."}
                  </p>
                </>
              ) : (
                <>
                  <h1>
                    {authenticated ? (
                      <>
                        Welcome back
                        {displayName?.trim() ? `, ${displayName.trim()}` : ""}
                        <span aria-hidden="true"> 👋</span>
                      </>
                    ) : (
                      "Welcome to Sales Xray"
                    )}
                  </h1>
                  <p className={styles.welcomeDescription}>
                    Upload a sales call and let Sales Xray find the insights, so
                    you can coach, improve, and close more.
                  </p>
                </>
              )}
            </div>
          )}
          {visibleHero && (
            <div className={styles.heroSlogan} aria-hidden="true">
              <span>
                Better
                <br />
                conversations.
                <br />
                Win more deals
              </span>
              <svg viewBox="0 0 70 46" focusable="false">
                <path d="M2 42C26 33 43 20 65 3M50 5l15-2-5 14" />
              </svg>
            </div>
          )}
          <div className={styles.profileSlot}>
            <ProfileMenu
              authenticated={authenticated}
              accountHref={accountHref}
            />
          </div>
        </header>
        <main id="main-content" className={styles.main}>
          {children}
        </main>
        {visibleHero && (
          <footer className={styles.workspaceFooter}>
            <span>
              <strong>Sales Xray</strong>{" "}
              <span>
                © {new Date().getFullYear()} Authority Closers. All rights
                reserved.
              </span>
            </span>
            <nav aria-label="Legal and support">
              <a href="https://app.authorityclosers.com/privacy">Privacy</a>
              <a href="https://app.authorityclosers.com/terms">Terms</a>
              <a href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20help">
                Help
              </a>
            </nav>
            <a className={styles.footerCta} href={newCallHref(homeHref)}>
              Turn conversations into closers{" "}
              <ArrowUpRight size={17} aria-hidden="true" />
            </a>
          </footer>
        )}
      </div>
      <nav
        className={styles.bottomNav}
        aria-label="Mobile Sales Xray navigation"
      >
        <a
          className={`${styles.bottomLink} ${active === "analyse" ? styles.bottomActive : ""}`}
          href={newCallHref(homeHref)}
          aria-current={active === "analyse" ? "page" : undefined}
        >
          <AudioLines size={20} aria-hidden="true" />
          <span>Analyse</span>
        </a>
        <Link
          className={`${styles.bottomLink} ${active === "calls" ? styles.bottomActive : ""}`}
          href="/calls"
          aria-current={active === "calls" ? "page" : undefined}
        >
          <FolderOpen size={20} aria-hidden="true" />
          <span>Saved calls</span>
        </Link>
        <Link
          className={styles.bottomLink}
          href={accountHref}
          onClick={(event) => {
            if (!authenticated && access?.requestAccountSignIn) {
              event.preventDefault();
              access.requestAccountSignIn();
            }
          }}
        >
          <CircleUserRound size={20} aria-hidden="true" />
          <span>{authenticated ? "Account" : "Profile"}</span>
        </Link>
        <LocalSettingsButton className={styles.bottomLink} />
      </nav>
    </div>
  );
}
