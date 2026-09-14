"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  clearReviewerFragment,
  readReviewerToken,
  requestReviewerSignIn,
  reviewerAuthErrorMessage,
  verifyReviewerSignIn,
} from "../reviewer-auth";
import { acceptReviewerInvitation, reviewerErrorMessage } from "../reviewer-api";
import { useReviewerSession } from "../reviewer-session";
import styles from "../reviewer-auth.module.css";

function AuthCard({ children, eyebrow, title, description }: { children: React.ReactNode; eyebrow: string; title: string; description: string }) {
  return (
    <main id="admin-content" className={styles.main} tabIndex={-1}>
      <section className={styles.card} aria-labelledby="reviewer-auth-title">
        <span className={styles.eyebrow}>{eyebrow}</span>
        <h1 id="reviewer-auth-title">{title}</h1>
        <p className={styles.description}>{description}</p>
        {children}
      </section>
    </main>
  );
}

export function ReviewerLoginForm() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus("sending");
    setMessage("");
    try {
      await requestReviewerSignIn(email);
      setStatus("sent");
      setMessage("Check your inbox for a reviewer sign-in link.");
    } catch (error) {
      setStatus("error");
      setMessage(reviewerAuthErrorMessage(error));
    }
  };
  return (
    <AuthCard eyebrow="Dedicated access" title="Sign in to review" description="Use the email address that received reviewer access. Reviewer sign-in is separate from your Academy learner session.">
      <form className={styles.form} onSubmit={submit}>
        <label htmlFor="reviewer-email">Email address</label>
        <input id="reviewer-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={320} />
        <button className={styles.primaryButton} type="submit" disabled={status === "sending"}>{status === "sending" ? "Sending link…" : "Email me a sign-in link"}</button>
        {message ? <p className={status === "error" ? styles.error : styles.success} role={status === "error" ? "alert" : "status"}>{message}</p> : null}
      </form>
      <p className={styles.note}>Reviewer links are one-time and expire. Open the link in this same browser after checking your inbox.</p>
    </AuthCard>
  );
}

export function ReviewerVerification() {
  const router = useRouter();
  const { refresh } = useReviewerSession();
  const tokenRef = useRef<string | null>(null);
  const requestRef = useRef<Promise<Awaited<ReturnType<typeof verifyReviewerSignIn>>> | null>(null);
  const [status, setStatus] = useState<"loading" | "missing" | "verifying" | "error">("loading");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    const token = tokenRef.current ?? readReviewerToken(window.location.hash);
    tokenRef.current = token;
    clearReviewerFragment();
    if (!token) {
      setStatus("missing");
      setMessage("Open this page from your reviewer sign-in email.");
      return () => { active = false; };
    }
    setStatus("verifying");
    requestRef.current ??= verifyReviewerSignIn(token);
    void requestRef.current.then(async (verified) => {
      if (!active) return;
      const session = await refresh();
      if (!session) {
        setStatus("error");
        setMessage("The reviewer session cookie was not established. Request a fresh sign-in link.");
        return;
      }
      const destination = verified.assignment_id ? `/reviewer/review/${encodeURIComponent(verified.assignment_id)}` : "/reviewer";
      router.push(destination);
    }, (error: unknown) => {
      if (!active) return;
      setStatus("error");
      setMessage(reviewerAuthErrorMessage(error));
    });
    return () => { active = false; };
  }, [refresh, router]);
  return (
    <AuthCard eyebrow="One-time sign-in" title="Verifying your reviewer link" description="Open this link in the same browser where you requested reviewer access.">
      {status === "verifying" || status === "loading" ? <p className={styles.status} role="status">Checking the link…</p> : null}
      {status === "missing" || status === "error" ? <><p className={styles.error} role="alert">{message}</p><Link className={styles.secondaryButton} href="/reviewer/login">Request another link</Link></> : null}
    </AuthCard>
  );
}

export function ReviewerInvitationAcceptance() {
  const router = useRouter();
  const { status: sessionStatus, session } = useReviewerSession();
  const tokenRef = useRef<string | null>(null);
  const requestRef = useRef<Promise<Awaited<ReturnType<typeof acceptReviewerInvitation>>> | null>(null);
  const [email, setEmail] = useState("");
  const [authStatus, setAuthStatus] = useState<"idle" | "sending" | "sent">("idle");
  const [status, setStatus] = useState<"loading" | "email" | "accepting" | "accepted" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    const token = tokenRef.current ?? readReviewerToken(window.location.hash);
    tokenRef.current = token;
    clearReviewerFragment();
    if (!token) {
      setStatus("error");
      setMessage("Open this page from the reviewer invitation email.");
      return () => { active = false; };
    }
    if (sessionStatus === "loading") return () => { active = false; };
    if (!session) return () => { active = false; };
    requestRef.current ??= acceptReviewerInvitation(token);
    void requestRef.current.then((loaded) => {
      if (!active) return;
      setStatus("accepted");
      router.push(`/reviewer/review/${encodeURIComponent(loaded.id)}`);
    }, (error: unknown) => {
      if (!active) return;
      setStatus("error");
      setMessage(reviewerErrorMessage(error));
    });
    return () => { active = false; };
  }, [router, session, sessionStatus]);

  const requestAccess = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = tokenRef.current;
    if (!token) return;
    setAuthStatus("sending");
    setMessage("");
    try {
      await requestReviewerSignIn(email, token);
      setAuthStatus("sent");
      setMessage("If the invitation matches that address, check your inbox for a reviewer sign-in link.");
    } catch (error) {
      setAuthStatus("idle");
      setMessage(reviewerAuthErrorMessage(error));
    }
  };

  const displayStatus = sessionStatus === "loading"
    ? "loading"
    : !session && status === "loading"
      ? "email"
      : session && status === "loading"
        ? "accepting"
        : status;
  return (
    <AuthCard eyebrow="Reviewer invitation" title="Claim your assigned review" description="Verify the email address that received this invitation. A new reviewer account is admitted to this workspace without changing Academy learner access.">
      {displayStatus === "loading" || displayStatus === "accepting" ? <p className={styles.status} role="status">{displayStatus === "loading" ? "Checking your reviewer session…" : "Opening the assigned review…"}</p> : null}
      {displayStatus === "email" ? <form className={styles.form} onSubmit={requestAccess}><label htmlFor="invited-reviewer-email">Invitation email</label><input id="invited-reviewer-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={320} /><button className={styles.primaryButton} type="submit" disabled={authStatus === "sending"}>{authStatus === "sending" ? "Sending link…" : "Continue with email"}</button>{message ? <p className={styles.success} role="status">{message}</p> : null}</form> : null}
      {displayStatus === "error" ? <><p className={styles.error} role="alert">{message}</p><Link className={styles.secondaryButton} href="/reviewer/login">Go to reviewer sign-in</Link></> : null}
      {displayStatus === "accepted" ? <p className={styles.success} role="status">Invitation accepted. Opening the review…</p> : null}
      <p className={styles.note}>Open the sign-in link in this same browser after checking your inbox.</p>
    </AuthCard>
  );
}
