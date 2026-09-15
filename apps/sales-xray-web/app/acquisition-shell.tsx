"use client";

import {
  AudioLines,
  BookOpen,
  ChevronRight,
  CircleUserRound,
  FolderOpen,
  LogIn,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { AccountNavigation } from "./account-navigation";
import { LocalSettingsButton } from "./live-data-banner";
import styles from "./acquisition-shell.module.css";

export function AcquisitionShell({
  children,
  authenticated,
  homeHref = "/",
  active = "analyse",
  compactBusy = false,
}: {
  children: ReactNode;
  authenticated: boolean;
  homeHref?: string;
  active?: "analyse" | "calls";
  compactBusy?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const hasToggled = useRef(false);
  const accountHref = authenticated ? "/calls" : "/login";
  const accountLabel = authenticated
    ? "Account & saved calls"
    : "Profile & account";
  const breadcrumbLabel = active === "calls" ? "Saved calls" : "Analyse a call";

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
            <span>
              <strong>Sales Xray</strong>
              <small>BY AUTHORITY CLOSERS</small>
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
          <Link
            className={`${styles.navLink} ${active === "analyse" ? styles.active : ""}`}
            href={homeHref}
            aria-current={active === "analyse" ? "page" : undefined}
          >
            <AudioLines size={18} aria-hidden="true" />
            <span>Analyse a call</span>
          </Link>
          <Link
            className={`${styles.navLink} ${active === "calls" ? styles.active : ""}`}
            href="/calls"
            aria-current={active === "calls" ? "page" : undefined}
          >
            <FolderOpen size={18} aria-hidden="true" />
            <span>Saved calls</span>
          </Link>
          <Link className={styles.navLink} href={accountHref}>
            <CircleUserRound size={18} aria-hidden="true" />
            <span>{accountLabel}</span>
          </Link>
          <LocalSettingsButton className={styles.navLink} />
        </nav>
        <div className={styles.sidebarNote}>
          <Image
            className={styles.dipakArt}
            src="/media/dipak-learning-hero-v1.webp"
            alt=""
            width={640}
            height={360}
            sizes="208px"
            loading="lazy"
          />
          <span className={styles.noteIcon} aria-hidden="true">
            <BookOpen size={18} />
          </span>
          <strong>Better calls start with a closer look.</strong>
          <p>Evidence first. A thoughtful second opinion.</p>
        </div>
        <div className={styles.sidebarAccount}>
          <span className={styles.avatar} aria-hidden="true">
            {authenticated ? "AC" : "G"}
          </span>
          <span className={styles.accountCopy}>
            <strong>{authenticated ? "AC account" : "Guest workspace"}</strong>
            <small>
              {authenticated
                ? "Account and saved calls"
                : "Private browser session"}
            </small>
          </span>
          {authenticated ? (
            <AccountNavigation compact />
          ) : (
            <Link className={styles.signIn} href="/login">
              <LogIn size={15} aria-hidden="true" />
              Sign in
            </Link>
          )}
        </div>
        <div className={styles.sidebarFooter}>
          <ShieldCheck size={15} aria-hidden="true" />
          Private by default
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
          <AccountNavigation compact />
        </header>
        <div className={styles.breadcrumb} aria-label="Current location">
          Sales Xray <ChevronRight size={13} aria-hidden="true" />{" "}
          <span>{breadcrumbLabel}</span>
        </div>
        <main id="main-content" className={styles.main}>
          {children}
        </main>
      </div>
      <nav
        className={styles.bottomNav}
        aria-label="Mobile Sales Xray navigation"
      >
        <Link
          className={`${styles.bottomLink} ${active === "analyse" ? styles.bottomActive : ""}`}
          href={homeHref}
          aria-current={active === "analyse" ? "page" : undefined}
        >
          <AudioLines size={20} aria-hidden="true" />
          <span>Analyse</span>
        </Link>
        <Link
          className={`${styles.bottomLink} ${active === "calls" ? styles.bottomActive : ""}`}
          href="/calls"
          aria-current={active === "calls" ? "page" : undefined}
        >
          <FolderOpen size={20} aria-hidden="true" />
          <span>Saved calls</span>
        </Link>
        <Link className={styles.bottomLink} href={accountHref}>
          <CircleUserRound size={20} aria-hidden="true" />
          <span>{authenticated ? "Account" : "Profile"}</span>
        </Link>
        <LocalSettingsButton className={styles.bottomLink} />
      </nav>
    </div>
  );
}
