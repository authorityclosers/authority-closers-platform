"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  loadReviewerSession,
  logoutReviewer,
  type ReviewerIdentity,
} from "./reviewer-auth";
import { requestReviewerNavigation } from "./review/reviewer-navigation";
import styles from "./reviewer-shell.module.css";

type ReviewerSessionState =
  | { status: "loading"; session: ReviewerIdentity | null }
  | { status: "ready"; session: ReviewerIdentity }
  | { status: "signed_out"; session: null }
  | { status: "error"; session: ReviewerIdentity | null; message: string };

type ReviewerSessionContextValue = ReviewerSessionState & {
  refresh: () => Promise<ReviewerIdentity | null>;
  signOut: () => Promise<boolean>;
};

const ReviewerSessionContext = createContext<ReviewerSessionContextValue | null>(null);

export function ReviewerSessionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ReviewerSessionState>({ status: "loading", session: null });

  const refresh = useCallback(async () => {
    setState((previous) => ({ status: "loading", session: previous.session }));
    try {
      const session = await loadReviewerSession();
      if (!session) {
        setState({ status: "signed_out", session: null });
        return null;
      }
      setState({ status: "ready", session });
      return session;
    } catch (error) {
      const status = error && typeof error === "object" && "status" in error ? Number((error as { status?: number }).status) : 0;
      if (status === 401 || status === 403 || status === 404) {
        setState({ status: "signed_out", session: null });
        return null;
      }
      setState({ status: "error", session: null, message: error instanceof Error ? error.message : "Reviewer session could not be checked." });
      return null;
    }
  }, []);

  useEffect(() => {
    let active = true;
    void loadReviewerSession().then(
      (session) => { if (active) setState(session ? { status: "ready", session } : { status: "signed_out", session: null }); },
      (error: unknown) => {
        if (!active) return;
        const status = error && typeof error === "object" && "status" in error ? Number((error as { status?: number }).status) : 0;
        setState(status === 401 || status === 403 || status === 404 ? { status: "signed_out", session: null } : { status: "error", session: null, message: error instanceof Error ? error.message : "Reviewer session could not be checked." });
      },
    );
    return () => { active = false; };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await logoutReviewer();
      setState({ status: "signed_out", session: null });
      return true;
    } catch (error) {
      setState((previous) => ({
        status: "error",
        session: previous.session,
        message: error instanceof Error ? error.message : "Reviewer sign-out could not be confirmed.",
      }));
      return false;
    }
  }, []);

  const value = useMemo(() => ({ ...state, refresh, signOut }), [state, refresh, signOut]);
  return <ReviewerSessionContext.Provider value={value}>{children}</ReviewerSessionContext.Provider>;
}

export function useReviewerSession() {
  const value = useContext(ReviewerSessionContext);
  if (!value) throw new Error("useReviewerSession must be used below ReviewerSessionProvider.");
  return value;
}

export function ReviewerShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const reviewerSession = useReviewerSession();
  const { status, session, signOut, refresh } = reviewerSession;
  const [signingOut, setSigningOut] = useState(false);
  const assignmentRoute = pathname === "/reviewer/review" || pathname.startsWith("/reviewer/review/");
  const assignmentBlocked = assignmentRoute && status !== "ready";
  const sessionError = status === "error" ? reviewerSession.message : null;
  const onSignOut = () => {
    if (signingOut) return;
    requestReviewerNavigation(() => {
      setSigningOut(true);
      void signOut()
        .then((succeeded) => {
          if (succeeded) router.replace("/reviewer/login");
        })
        .finally(() => setSigningOut(false));
    });
  };
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link className={styles.brand} href="/reviewer" aria-label="Reviewer workspace home">
          <span className={styles.brandMark} aria-hidden="true">AC</span>
          <span><strong>Authority Closers</strong><small>Reviewer workspace</small></span>
        </Link>
        <div className={styles.headerActions}>
          <span className={styles.sessionPill} data-status={status}>
            {status === "loading" ? "Checking access" : session ? session.email : "Signed out"}
          </span>
          {session ? <button className={styles.signOut} type="button" onClick={onSignOut} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button> : null}
          {sessionError && session ? <span className={styles.signOutError} role="alert">{sessionError}</span> : null}
        </div>
      </header>
      {assignmentBlocked ? (
        <main id="admin-content" className={styles.boundary} tabIndex={-1}>
          <section className={styles.boundaryCard} role={status === "error" ? "alert" : "status"}>
            <span className={styles.boundaryEyebrow}>Reviewer access</span>
            <h1>{status === "loading" ? "Checking your reviewer session" : status === "error" ? "Reviewer session unavailable" : "Sign in to continue"}</h1>
            <p>{status === "loading" ? "Your assigned source will open after access is verified." : status === "error" ? sessionError ?? "The dedicated reviewer session could not be checked." : "This assigned review is private to the signed-in reviewer."}</p>
            {status === "error" ? <button className={styles.boundaryButton} type="button" onClick={() => void refresh()}>Reconnect</button> : null}
            {status === "signed_out" || status === "error" ? <Link className={styles.boundaryButton} href="/reviewer/login">Open reviewer sign-in</Link> : null}
          </section>
        </main>
      ) : children}
    </div>
  );
}
