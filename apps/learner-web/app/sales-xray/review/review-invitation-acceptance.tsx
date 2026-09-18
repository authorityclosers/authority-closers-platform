"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ROUTES } from "../../lib/routes";
import {
  clearReviewInvitationFragment,
  readReviewInvitationToken,
  withReviewInvitationToken,
} from "../../lib/review-invitation-auth";
import {
  acceptReviewInvitation,
  reviewInvitationErrorMessage,
  ReviewInvitationApiProblem,
  type AcceptedReviewInvitation,
} from "./review-invitation-api";
import styles from "./review-invitation.module.css";

type State =
  | { status: "loading"; token: string | null }
  | { status: "sign_in"; token: string }
  | { status: "accepting"; token: string }
  | {
      status: "error";
      token: string | null;
      message: string;
      retryable: boolean;
    }
  | { status: "accepted"; token: string; assignment: AcceptedReviewInvitation };

export function ReviewInvitationAcceptance() {
  const router = useRouter();
  const [state, setState] = useState<State>({ status: "loading", token: null });
  const tokenRef = useRef<string | null>(null);
  const requestRef = useRef<Promise<AcceptedReviewInvitation> | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const token =
      tokenRef.current ?? readReviewInvitationToken(window.location.hash, true);
    tokenRef.current = token;
    // Remove the bearer token from the visible URL before any auth transition.
    clearReviewInvitationFragment();
    if (!token) {
      queueMicrotask(() => {
        if (active)
          setState({
            status: "error",
            token: null,
            retryable: false,
            message: "Open this page from the invitation email.",
          });
      });
      return () => {
        active = false;
      };
    }
    queueMicrotask(() => {
      if (active) setState({ status: "accepting", token });
    });
    // Reuse one acceptance request through React effect replay. The fragment
    // has already been removed, so replay must retain the in-memory token.
    requestRef.current ??= acceptReviewInvitation(token);
    void requestRef.current.then(
      (assignment) => {
        if (!active) return;
        setState({ status: "accepted", token, assignment });
        router.push(`/sales-xray/review/${encodeURIComponent(assignment.id)}`);
      },
      (reason: unknown) => {
        if (!active) return;
        const message = reviewInvitationErrorMessage(reason);
        if (
          reason instanceof Error &&
          "status" in reason &&
          ((reason as { status?: number }).status === 401 ||
            (reason as { status?: number }).status === 403)
        ) {
          setState({ status: "sign_in", token });
        } else {
          setState({
            status: "error",
            token,
            message,
            retryable:
              reason instanceof TypeError ||
              (reason instanceof ReviewInvitationApiProblem &&
                reason.retryable),
          });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [router, attempt]);

  const loginHref = state.token
    ? withReviewInvitationToken(ROUTES.login, state.token)
    : ROUTES.login;
  const registerHref = state.token
    ? withReviewInvitationToken(ROUTES.register, state.token)
    : ROUTES.register;

  return (
    <main id="main-content" className="learner-main" tabIndex={-1}>
      <div className="page-container">
        <section
          className={styles.card}
          aria-labelledby="review-invitation-title"
        >
          <span className={styles.eyebrow}>Sales Xray / reviewer handoff</span>
          <h1 id="review-invitation-title">Review invitation</h1>
          {state.status === "loading" || state.status === "accepting" ? (
            <p role="status">
              Checking your verified session before opening the invitation…
            </p>
          ) : null}
          {state.status === "sign_in" ? (
            <>
              <p role="alert">
                Sign in with the email address that received this invitation.
              </p>
              <div className={styles.actions}>
                <Link className="button button--ink" href={loginHref}>
                  Sign in
                </Link>
                <Link className="button button--outline" href={registerHref}>
                  Create an account
                </Link>
                <a
                  className="button button--outline"
                  href={ROUTES.login}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Use Google sign-in in another tab
                </a>
                <button
                  className="button button--outline"
                  type="button"
                  onClick={() => {
                    requestRef.current = null;
                    setAttempt((value) => value + 1);
                  }}
                >
                  I&apos;ve signed in — open review
                </button>
              </div>
              <p>
                For Google sign-in, keep this invitation tab open. Finish
                signing in in the new tab, then return here and open the review.
              </p>
            </>
          ) : null}
          {state.status === "error" ? (
            <>
              <p role="alert">{state.message}</p>
              {state.retryable && state.token ? (
                <button
                  className="button button--ink"
                  type="button"
                  onClick={() => {
                    requestRef.current = null;
                    setAttempt((value) => value + 1);
                  }}
                >
                  Retry invitation
                </button>
              ) : null}
              {state.token ? (
                <Link className="button button--outline" href={loginHref}>
                  Return to sign in
                </Link>
              ) : null}
            </>
          ) : null}
          {state.status === "accepted" ? (
            <p role="status">
              Invitation accepted. Opening the assigned Academy review…
            </p>
          ) : null}
          <p className={styles.note}>
            Use the email address that received this invitation. If you need
            access to a different call, ask the administrator for a new link.
          </p>
        </section>
      </div>
    </main>
  );
}
