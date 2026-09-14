"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { createReviewerAssignmentApi, reviewerErrorMessage, ReviewerApiProblem, type ReviewerAssignmentSummary } from "./reviewer-api";
import { useReviewerSession } from "./reviewer-session";
import styles from "./reviewer-home.module.css";

function stateLabel(value: ReviewerAssignmentSummary["state"]) {
  return value === "in_progress" ? "In progress" : value.replaceAll("_", " ");
}

export function ReviewerHome() {
  const { status, session, refresh } = useReviewerSession();
  const [items, setItems] = useState<ReviewerAssignmentSummary[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [queueState, setQueueState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    if (status !== "ready") return;
    const controller = new AbortController();
    void createReviewerAssignmentApi().queue(controller.signal).then((payload) => {
      if (controller.signal.aborted) return;
      setItems(payload.items);
      setTruncated(payload.truncated);
      setQueueState("ready");
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      if (reason instanceof ReviewerApiProblem && (reason.status === 401 || reason.status === 403)) void refresh();
      setError(reviewerErrorMessage(reason));
      setQueueState("error");
    });
    return () => controller.abort();
  }, [refresh, status]);

  return (
    <main id="admin-content" className={styles.main} tabIndex={-1}>
      <div className={styles.container}>
        <span className={styles.eyebrow}>Dedicated reviewer access</span>
        <div className={styles.hero}>
          <div><h1>Review the calls assigned to you.</h1><p>Every assignment carries its own source, transcript and allowed feedback lenses. Your reviewer session is independent from Academy learner access.</p></div>
          {session ? <div className={styles.identity}><span>Signed in as</span><strong>{session.display_name || session.email}</strong><small>{session.email}</small></div> : null}
        </div>
        {status === "loading" ? <section className={styles.stateCard}><p role="status">Checking your reviewer session…</p></section> : null}
        {status === "signed_out" ? <section className={styles.stateCard}><h2>Sign in to see assignments</h2><p>Use the one-time link sent to your reviewer email.</p><Link className={styles.primaryButton} href="/reviewer/login">Sign in to review</Link></section> : null}
        {status === "error" ? <section className={styles.stateCard}><h2>Reviewer session unavailable</h2><p role="alert">The workspace could not verify your dedicated session. Refresh to try again.</p><button className={styles.secondaryButton} type="button" onClick={() => window.location.reload()}>Refresh workspace</button></section> : null}
        {status === "ready" && queueState === "loading" ? <p className={styles.status} role="status">Loading your assignments…</p> : null}
        {status === "ready" && queueState === "error" ? <section className={styles.stateCard}><h2>Assignments unavailable</h2><p className={styles.error} role="alert">{error}</p><button className={styles.secondaryButton} type="button" onClick={() => window.location.reload()}>Retry assignments</button></section> : null}
        {status === "ready" && queueState === "ready" ? <section className={styles.queue} aria-labelledby="assignments-title"><div className={styles.queueHeading}><div><span className={styles.eyebrow}>Your queue</span><h2 id="assignments-title">Assigned conversations</h2></div><span className={styles.countPill}>{items.length}{truncated ? "+" : ""}</span></div>{items.length === 0 ? <p className={styles.empty}>There are no active reviewer assignments for this session.</p> : <div className={styles.cards}>{items.map((item) => <Link className={styles.assignmentCard} href={`/reviewer/review/${encodeURIComponent(item.id)}`} key={item.id}><div className={styles.cardTop}><span className={styles.statePill} data-state={item.state}>{stateLabel(item.state)}</span><span>{new Date(item.expires_at_epoch * 1000).toLocaleDateString()}</span></div><h3>Conversation review</h3><p>Run {item.run_id.slice(0, 8)}… · generation {item.run_generation}</p><div className={styles.cardBottom}><span>{item.allowed_lenses.join(" · ")}</span><span>Open review →</span></div></Link>)}</div>}{truncated ? <p className={styles.note}>Showing the first 50 assignments.</p> : null}</section> : null}
      </div>
    </main>
  );
}
