"use client";

import { ChevronDown, CircleUserRound, FolderOpen, LogOut } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  requestSalesXrayLogout,
  UploadNeedsSignOutConfirmationError,
} from "./account-navigation";
import { readAccountProfile } from "./account-profile-client";
import { useUploadSession } from "./hooks/upload-session";
import { ThemeControl } from "./lightbox/theme-provider";
import { LocalSettingsButton } from "./live-data-banner";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./profile-menu.module.css";

const SIGN_OUT_UPLOAD_WARNING =
  "The upload is still in progress or unconfirmed. Signing out will stop it and clear this tab’s recovery state. If the server already received it, you can find it in Calls. Continue?";

export const PROFILE_UPDATED_EVENT = "sales-xray:profile-updated";

function initials(name: string | null): string {
  if (!name) return "AC";
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => Array.from(part)[0])
    .join("")
    .toLocaleUpperCase();
}

export function ProfileMenu({
  authenticated,
  accountHref,
  placement = "below",
  compact = false,
}: {
  authenticated: boolean;
  accountHref: string;
  /** "above" opens from the account row at the foot of the rail. */
  placement?: "below" | "above";
  /** Avatar only, for the collapsed rail. */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState("");
  const [profileName, setProfileName] = useState<string | null>(null);
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const signingOutRef = useRef(false);
  const access = useWorkspaceAccess();
  const upload = useUploadSession();

  useEffect(() => {
    if (!authenticated) return;
    let controller: AbortController | null = null;
    const refresh = () => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      void readAccountProfile(current.signal)
        .then((profile) => {
          if (!current.signal.aborted)
            setProfileName(profile.name?.trim() || null);
        })
        .catch(() => {
          // The menu remains usable when a profile read is unavailable.
        });
    };
    const refreshAfterUpdate = () => {
      setProfileName(null);
      refresh();
    };
    refresh();
    window.addEventListener(PROFILE_UPDATED_EVENT, refreshAfterUpdate);
    return () => {
      window.removeEventListener(PROFILE_UPDATED_EVENT, refreshAfterUpdate);
      controller?.abort();
    };
  }, [authenticated]);

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
    const closeOnEscape = (event: KeyboardEvent) => {
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

  async function signOut() {
    if (signingOutRef.current) return;
    const unresolved = upload?.requiresSignOutConfirmation() ?? false;
    if (unresolved && !window.confirm(SIGN_OUT_UPLOAD_WARNING)) return;
    signingOutRef.current = true;
    setSigningOut(true);
    setError("");
    try {
      await requestSalesXrayLogout(upload, unresolved);
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

  return (
    <div
      ref={menu}
      className={styles.menu}
      data-placement={placement}
      data-compact={compact || undefined}
    >
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-label={
          authenticated ? `Open ${accountLabel} menu` : "Open profile menu"
        }
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.avatar} aria-hidden="true">
          <CircleUserRound />
        </span>
        <span className={styles.triggerCopy}>
          <strong title={accountName || undefined}>{accountLabel}</strong>
          <small>
            {authenticated ? "Private workspace" : "Sign in to analyse calls"}
          </small>
        </span>
        <ChevronDown className={styles.chevron} size={15} aria-hidden="true" />
      </button>
      {open ? (
        <div
          className={styles.popover}
          role="region"
          aria-label="Profile actions"
        >
          <div className={styles.summary}>
            <span className={styles.summaryAvatar} aria-hidden="true">
              {authenticated ? initials(accountName) : "G"}
            </span>
            <span className={styles.summaryCopy}>
              <strong>
                {authenticated
                  ? accountName || "Authority Closers account"
                  : "Guest workspace"}
              </strong>
              <small>
                {authenticated
                  ? "Calls and reports stay scoped to your workspace."
                  : "Sign in to analyse calls and open your reports."}
              </small>
            </span>
          </div>
          <div className={styles.actions}>
            {!authenticated && access?.requestAccountSignIn ? (
              <button
                type="button"
                className={styles.item}
                onClick={() => {
                  setOpen(false);
                  access.requestAccountSignIn?.();
                }}
              >
                <FolderOpen size={16} aria-hidden="true" />
                Sign in to my AC account
              </button>
            ) : (
              <Link
                href={accountHref}
                className={styles.item}
                onClick={() => setOpen(false)}
              >
                <FolderOpen size={16} aria-hidden="true" />
                {authenticated
                  ? "Saved calls & account"
                  : "Sign in to my AC account"}
              </Link>
            )}
            <LocalSettingsButton className={styles.item} />
            {authenticated ? (
              <button
                type="button"
                className={styles.item}
                disabled={signingOut}
                onClick={() => void signOut()}
              >
                <LogOut size={16} aria-hidden="true" />
                {signingOut ? "Signing out…" : "Sign out"}
              </button>
            ) : null}
          </div>
          <ThemeControl className={styles.theme} />
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
