"use client";

import Link from "next/link";

import { AccountSettings } from "./account-settings";
import { AcquisitionShell } from "./acquisition-shell";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./account-view.module.css";

/** The signed-in Sales Xray account: verified identity, details, allowance. */
export function AccountView() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const identityKey = access?.context
    ? JSON.stringify([
        access.context.personId,
        access.context.sessionId,
        access.context.tenantId,
      ])
    : String(access?.authenticated ?? "unknown");
  return (
    <AcquisitionShell
      authenticated={authenticated}
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <div className={styles.page} data-account-view>
        {access?.authenticated === false ? (
          <>
            <header className={styles.header}>
              <h1>Account</h1>
              <p>Your Authority Closers identity for Sales Xray.</p>
            </header>
            <section className={styles.panel} aria-labelledby="account-signin">
              <h2 id="account-signin">Sign in to see your account</h2>
              <p className={styles.muted}>
                Your profile and analysis allowance appear after you sign in.
              </p>
              <div className={styles.actions}>
                <Link
                  className={styles.primary}
                  href="/login"
                  onClick={(event) => {
                    if (access.requestAccountSignIn) {
                      event.preventDefault();
                      access.requestAccountSignIn();
                    }
                  }}
                >
                  Sign in
                </Link>
              </div>
            </section>
          </>
        ) : authenticated ? (
          <AccountSettings key={identityKey} />
        ) : (
          <>
            <header className={styles.header}>
              <h1>Account</h1>
            </header>
            <p className={styles.muted} role="status" aria-busy="true">
              Checking your account…
            </p>
          </>
        )}
      </div>
    </AcquisitionShell>
  );
}

