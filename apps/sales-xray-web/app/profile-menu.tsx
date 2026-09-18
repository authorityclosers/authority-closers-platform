"use client";

import { ChevronDown, CircleUserRound, FolderOpen, LogOut } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { requestSalesXrayLogout } from "./account-navigation";
import { LocalSettingsButton } from "./live-data-banner";
import styles from "./profile-menu.module.css";

export function ProfileMenu({
  authenticated,
  accountHref,
}: {
  authenticated: boolean;
  accountHref: string;
}) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState("");
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const signingOutRef = useRef(false);

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
    signingOutRef.current = true;
    setSigningOut(true);
    setError("");
    try {
      await requestSalesXrayLogout();
      // Discard the mounted report, audio and client route cache after logout.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- Confirmed sign out must discard private document state.
      window.location.assign("/");
    } catch {
      setError("We couldn’t confirm sign out. Try again.");
      setSigningOut(false);
      signingOutRef.current = false;
    }
  }

  return (
    <div ref={menu} className={styles.menu}>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-label={
          authenticated ? "Open AC account menu" : "Open profile menu"
        }
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.avatar} aria-hidden="true">
          <CircleUserRound />
        </span>
        <span className={styles.triggerCopy}>
          <strong>{authenticated ? "AC account" : "Guest workspace"}</strong>
          <small>
            {authenticated ? "Private workspace" : "Sign in to save calls"}
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
              {authenticated ? "AC" : "G"}
            </span>
            <span className={styles.summaryCopy}>
              <strong>
                {authenticated
                  ? "Authority Closers account"
                  : "Guest workspace"}
              </strong>
              <small>
                {authenticated
                  ? "Calls and reports stay scoped to your workspace."
                  : "Sign in when you’re ready to save your calls."}
              </small>
            </span>
          </div>
          <div className={styles.actions}>
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
