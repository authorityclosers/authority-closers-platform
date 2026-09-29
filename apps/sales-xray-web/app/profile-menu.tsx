"use client";

import {
  ChevronDown,
  FolderOpen,
  LogOut,
  Mail,
  MoreHorizontal,
  User,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import {
  requestSalesXrayLogout,
  UploadNeedsSignOutConfirmationError,
} from "./account-navigation";
import { invalidateShellProfile, useShellProfile } from "./shell/profile-store";
import { useUploadSession } from "./hooks/upload-session";
import { ThemeControl } from "./lightbox/theme-provider";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./profile-menu.module.css";

const SIGN_OUT_UPLOAD_WARNING =
  "The upload is still in progress or unconfirmed. Signing out will stop it and clear this tab’s recovery state. If the server already received it, you can find it in Calls. Continue?";

export { PROFILE_UPDATED_EVENT } from "./shell/profile-store";

function initials(name: string | null): string {
  if (!name) return "AC";
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => Array.from(part)[0])
    .join("")
    .toLocaleUpperCase();
}

function getFirstName(name: string | null, email: string | null): string {
  if (name && name.trim().length > 0) {
    const first = name.trim().split(/\s+/)[0];
    if (first) return first;
  }
  if (email && email.includes("@")) {
    const prefix = email.split("@")[0]?.trim();
    if (prefix) return prefix;
  }
  return "Account";
}

export function ProfileMenu({
  authenticated,
  accountHref,
  placement = "below",
  compact = false,
  variant = "header",
}: {
  authenticated: boolean;
  accountHref: string;
  /** "above" opens from the account row at the foot of the rail. */
  placement?: "below" | "above";
  /** Avatar only, for the collapsed rail. */
  compact?: boolean;
  variant?: "rail" | "header";
}) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState("");
  const profile = useShellProfile(authenticated);
  const profileName = profile?.name?.trim() || null;
  const profileEmail = profile?.email?.trim() || null;
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const signingOutRef = useRef(false);
  const access = useWorkspaceAccess();
  const upload = useUploadSession();

  const accountName = authenticated ? profileName : null;
  const accountLabel = authenticated
    ? accountName || "AC account"
    : "Guest workspace";

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePress = (event: PointerEvent) => {
      if (event.target instanceof Node && !menu.current?.contains(event.target))
        setOpen(false);
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      trigger.current?.focus();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const popoverEl = menu.current?.querySelector(`.${styles.popover}`);
      if (!popoverEl) return;
      const focusable = Array.from(
        popoverEl.querySelectorAll<HTMLElement>("a, button:not([disabled])"),
      );
      if (focusable.length === 0) return;
      const currentIndex = focusable.indexOf(
        document.activeElement as HTMLElement,
      );
      if (event.key === "ArrowDown") {
        const nextIndex =
          currentIndex >= 0 && currentIndex < focusable.length - 1
            ? currentIndex + 1
            : 0;
        focusable[nextIndex]?.focus();
      } else {
        const prevIndex =
          currentIndex > 0 ? currentIndex - 1 : focusable.length - 1;
        focusable[prevIndex]?.focus();
      }
    }
  }

  async function signOut() {
    if (signingOutRef.current) return;
    const unresolved = upload?.requiresSignOutConfirmation() ?? false;
    if (unresolved && !window.confirm(SIGN_OUT_UPLOAD_WARNING)) return;
    signingOutRef.current = true;
    setSigningOut(true);
    setError("");
    try {
      await requestSalesXrayLogout(upload, unresolved);
      invalidateShellProfile();
      // Discard the mounted report, audio and client route cache after logout.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- Confirmed sign out must discard private document state.
      window.location.assign("/");
    } catch (error) {
      setError(
        error instanceof UploadNeedsSignOutConfirmationError
          ? "Check the upload and confirm sign out again."
          : "We couldn’t confirm sign out. Try again.",
      );
      setSigningOut(false);
      signingOutRef.current = false;
    }
  }

  const userInitials = initials(accountName);
  const displayName = accountLabel;
  const firstName = getFirstName(accountName, profileEmail);
  const displayEmail =
    profileEmail ||
    (authenticated ? "Private workspace" : "Sign in to analyse calls");

  return (
    <div
      ref={menu}
      className={styles.menu}
      data-placement={placement}
      data-variant={variant}
      data-compact={compact || undefined}
    >
      {variant === "header" ? (
        <button
          ref={trigger}
          type="button"
          className={styles.headerTrigger}
          aria-expanded={open}
          aria-label={
            authenticated ? `Open ${displayName} menu` : "Open profile menu"
          }
          onClick={() => setOpen((value) => !value)}
        >
          <span className={styles.avatarInitials} aria-hidden="true">
            {userInitials}
          </span>
          <span className={styles.headerName}>{firstName}</span>
          <ChevronDown
            className={styles.chevron}
            size={14}
            aria-hidden="true"
          />
        </button>
      ) : (
        <button
          ref={trigger}
          type="button"
          className={styles.trigger}
          aria-expanded={open}
          aria-label={
            authenticated ? `Open ${displayName} menu` : "Open profile menu"
          }
          onClick={() => setOpen((value) => !value)}
        >
          <span className={styles.avatarInitials} aria-hidden="true">
            {userInitials}
          </span>
          <span className={styles.triggerCopy}>
            <strong title={displayName}>{displayName}</strong>
            <small>{displayEmail}</small>
          </span>
          <MoreHorizontal
            className={styles.moreIcon}
            size={18}
            aria-hidden="true"
          />
        </button>
      )}
      {open ? (
        <div
          className={styles.popover}
          role="region"
          aria-label="Profile actions"
          onKeyDown={handleMenuKeyDown}
        >
          <div className={styles.menuHeader}>
            <span className={styles.summaryAvatar} aria-hidden="true">
              {userInitials}
            </span>
            <div className={styles.menuHeaderCopy}>
              <strong className={styles.headerFullName}>
                {authenticated
                  ? accountName || "Authority Closers account"
                  : "Guest workspace"}
              </strong>
              <small className={styles.headerEmail}>{displayEmail}</small>
            </div>
          </div>
          <div className={styles.separator} role="separator" />
          <div className={styles.actions}>
            {authenticated ? (
              <Link
                href={accountHref}
                className={styles.item}
                onClick={() => setOpen(false)}
              >
                <User size={16} aria-hidden="true" />
                <span>Account</span>
              </Link>
            ) : access?.requestAccountSignIn ? (
              <button
                type="button"
                className={styles.item}
                onClick={() => {
                  setOpen(false);
                  access.requestAccountSignIn?.();
                }}
              >
                <User size={16} aria-hidden="true" />
                <span>Sign in</span>
              </button>
            ) : (
              <Link
                href="/login"
                className={styles.item}
                onClick={() => setOpen(false)}
              >
                <User size={16} aria-hidden="true" />
                <span>Sign in</span>
              </Link>
            )}
            <Link
              href="/analysis/calls"
              className={styles.item}
              onClick={() => setOpen(false)}
            >
              <FolderOpen size={16} aria-hidden="true" />
              <span>Calls</span>
            </Link>
          </div>
          <ThemeControl />
          <div className={styles.separator} role="separator" />
          <div className={styles.actions}>
            <a
              href="https://app.authorityclosers.com/privacy"
              target="_blank"
              rel="noreferrer"
              className={styles.item}
              onClick={() => setOpen(false)}
            >
              <span>Privacy</span>
            </a>
            <a
              href="https://app.authorityclosers.com/terms"
              target="_blank"
              rel="noreferrer"
              className={styles.item}
              onClick={() => setOpen(false)}
            >
              <span>Terms</span>
            </a>
            <a
              href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20help"
              className={styles.item}
              onClick={() => setOpen(false)}
            >
              <Mail size={16} aria-hidden="true" />
              <span>Email the AC team</span>
            </a>
          </div>
          {authenticated ? (
            <>
              <div className={styles.separator} role="separator" />
              <div className={styles.actions}>
                <button
                  type="button"
                  className={styles.item}
                  disabled={signingOut}
                  onClick={() => void signOut()}
                >
                  <LogOut size={16} aria-hidden="true" />
                  <span>{signingOut ? "Signing out…" : "Sign out"}</span>
                </button>
              </div>
            </>
          ) : null}
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
