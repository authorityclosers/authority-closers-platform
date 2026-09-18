"use client";

import { ArrowRight, LogOut } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { rememberSubmission } from "./acquisition-client";
import { useWorkspaceAccess } from "./workspace-access";

const SIGN_OUT_ERROR = "We couldn’t confirm sign out. Try again.";

/**
 * Confirm the server's logout contract before discarding the current document.
 * The only browser state owned by this surface is the opaque submission id.
 */
export async function requestSalesXrayLogout() {
  const response = await fetch("/v1/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json" },
  });
  if (response.status !== 204) throw new Error("logout_unconfirmed");
  rememberSubmission(null);
}

export function AccountNavigation({ compact = false }: { compact?: boolean }) {
  const access = useWorkspaceAccess();
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);

  async function signOut() {
    if (inFlight.current) return;
    inFlight.current = true;
    setSigningOut(true);
    setError("");
    try {
      await requestSalesXrayLogout();
      // A confirmed sign out must replace the document so report and playback
      // state cannot remain reachable through the current React tree.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- Confirmed sign out must discard the privileged document and route cache.
      window.location.assign("/");
    } catch {
      setError(SIGN_OUT_ERROR);
      setSigningOut(false);
    } finally {
      inFlight.current = false;
    }
  }

  const className = compact
    ? "account-navigation account-navigation-compact"
    : "account-navigation";

  if (access?.authenticated === true)
    return (
      <nav className={className} aria-label="Sales Xray account navigation">
        <Link href="/calls" className="account-nav-link">
          Saved calls
        </Link>
        <button
          type="button"
          className="account-nav-signout"
          onClick={() => void signOut()}
          disabled={signingOut}
        >
          <LogOut size={15} aria-hidden="true" />
          {signingOut ? "Signing out…" : "Sign out"}
        </button>
        {error ? (
          <span className="account-nav-error" role="alert">
            {error}
          </span>
        ) : null}
      </nav>
    );

  if (access?.authenticated === false)
    return (
      <nav className={className} aria-label="Sales Xray account navigation">
        <Link href="/login" className="account-nav-link">
          My AC account <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </nav>
    );

  return null;
}
