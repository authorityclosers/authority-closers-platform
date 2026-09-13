"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Clock3, RefreshCw, ShieldCheck } from "lucide-react";

import {
  adminReviewDetailsError,
  loadAdminReviewDetails,
  type AdminReviewDetails,
  type AdminReviewFeedbackItem,
} from "./admin-review-details-api";
import { ReviewApiProblem } from "./review-api";
import styles from "./admin-review-details.module.css";

type DetailState =
  | { status: "loading"; details: AdminReviewDetails | null }
  | { status: "ready"; details: AdminReviewDetails }
  | {
      status: "error";
      details: AdminReviewDetails | null;
      message: string;
      retryable: boolean;
    };

function formatEpoch(epoch: number | null): string {
  if (epoch === null) return "Unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(epoch * 1000));
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function DetailStatePanel({
  state,
  onRetry,
}: {
  state: DetailState;
  onRetry: () => void;
}) {
  if (state.status === "loading" && state.details === null) {
    return (
      <div className={styles.state} role="status" aria-live="polite">
        <RefreshCw size={19} className="spin" aria-hidden="true" />
        <strong>Loading saved review feedback</strong>
      </div>
    );
  }
  if (state.status === "error" && state.details === null) {
    return (
      <div className={styles.state} role="alert">
        <AlertCircle size={19} aria-hidden="true" />
        <strong>{state.message}</strong>
        {state.retryable ? (
          <button
            className="button button-secondary"
            type="button"
            onClick={onRetry}
          >
            <RefreshCw size={15} aria-hidden="true" /> Retry details
          </button>
        ) : null}
      </div>
    );
  }
  return null;
}

function FeedbackItem({ item }: { item: AdminReviewFeedbackItem }) {
  const payload = item.payload;
  return (
    <article className={styles.feedbackItem} data-feedback-state={item.state}>
      <div className={styles.feedbackHeader}>
        <div>
          <span className={styles.kicker}>Saved feedback</span>
          <h3>{shortId(item.id)}</h3>
        </div>
        <span
          className={
            item.state === "available" ? styles.available : styles.erased
          }
        >
          {item.state === "available"
            ? "Available"
            : item.state === "erased"
              ? "Erased"
              : "Unavailable"}
        </span>
      </div>
      <dl className={styles.metadata}>
        <div>
          <dt>Created</dt>
          <dd>{formatEpoch(item.created_at_epoch)}</dd>
        </div>
        {item.erased_at_epoch !== null ? (
          <div>
            <dt>Erased</dt>
            <dd>{formatEpoch(item.erased_at_epoch)}</dd>
          </div>
        ) : null}
      </dl>
      {payload ? (
        <>
          <div className={styles.feedbackFacts}>
            <span>Lens: {payload.lens}</span>
            <span>Confidence: {payload.confidence}</span>
            <span>Reviewer: {shortId(payload.reviewer_person_id)}</span>
          </div>
          <p className={styles.feedbackCopy}>{payload.feedback}</p>
          {payload.proposed_correction ? (
            <div className={styles.correction}>
              <strong>
                Proposed correction · {payload.proposed_correction.target_layer}
              </strong>
              <p>
                <strong>Actual:</strong> {payload.proposed_correction.actual}
              </p>
              <p>
                <strong>Expected:</strong>{" "}
                {payload.proposed_correction.expected}
              </p>
              <p>{payload.proposed_correction.rationale}</p>
            </div>
          ) : null}
        </>
      ) : (
        <p className={styles.erasedCopy}>
          {item.state === "erased"
            ? "The feedback payload was erased with the source. Immutable envelope metadata remains available for audit and history checks."
            : "The feedback payload is unavailable while the source permission or retention fence is closed."}
        </p>
      )}
      <details className={styles.integrity}>
        <summary>Integrity metadata</summary>
        <dl className={styles.metadata}>
          <div>
            <dt>Payload hash</dt>
            <dd title={item.payload_sha256}>{shortId(item.payload_sha256)}</dd>
          </div>
          <div>
            <dt>Request hash</dt>
            <dd title={item.request_sha256}>{shortId(item.request_sha256)}</dd>
          </div>
        </dl>
      </details>
    </article>
  );
}

export function AdminReviewDetails({ assignmentId }: { assignmentId: string }) {
  return (
    <AdminReviewDetailsSession key={assignmentId} assignmentId={assignmentId} />
  );
}

function AdminReviewDetailsSession({ assignmentId }: { assignmentId: string }) {
  const [state, setState] = useState<DetailState>({
    status: "loading",
    details: null,
  });
  const [reloadToken, setReloadToken] = useState(0);
  const requestGeneration = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    void loadAdminReviewDetails(assignmentId, fetch, controller.signal).then(
      (details) => {
        if (generation !== requestGeneration.current) return;
        setState({ status: "ready", details });
      },
      (error: unknown) => {
        if (
          generation !== requestGeneration.current ||
          (error instanceof DOMException && error.name === "AbortError")
        ) {
          return;
        }
        const parsed = adminReviewDetailsError(error);
        const terminal =
          error instanceof ReviewApiProblem &&
          (error.status === 403 || error.status === 404);
        setState((current) => ({
          status: "error",
          details: terminal ? null : current.details,
          ...parsed,
        }));
      },
    );
    return () => {
      requestGeneration.current += 1;
      controller.abort();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [assignmentId, reloadToken]);

  const retry = useCallback(() => {
    setState({ status: "loading", details: null });
    setReloadToken((current) => current + 1);
  }, []);
  const details = state.details;
  return (
    <section
      className={styles.panel}
      aria-labelledby="saved-review-details-title"
    >
      <div className={styles.panelHeader}>
        <div>
          <span className={styles.kicker}>
            Saved feedback and access history
          </span>
          <h2 id="saved-review-details-title">Saved review feedback</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          aria-label="Refresh saved review feedback"
          onClick={retry}
          disabled={state.status === "loading"}
        >
          <RefreshCw
            size={17}
            className={state.status === "loading" ? "spin" : undefined}
            aria-hidden="true"
          />
        </button>
      </div>
      <p className={styles.intro}>
        Read-only feedback saved by the assigned reviewer. Source audio and
        report payloads remain private.
      </p>
      <DetailStatePanel state={state} onRetry={retry} />
      {state.status === "error" && details ? (
        <div className={styles.inlineError} role="alert">
          <AlertCircle size={16} aria-hidden="true" /> {state.message}
          {state.retryable ? (
            <button type="button" onClick={retry}>
              Retry
            </button>
          ) : null}
        </div>
      ) : null}
      {details ? (
        <>
          <div className={styles.lifecycle}>
            <div className={styles.lifecycleTitle}>
              <ShieldCheck size={17} aria-hidden="true" />
              <strong>Access and source binding</strong>
            </div>
            <dl className={styles.metadata}>
              <div>
                <dt>Assignment</dt>
                <dd>{shortId(details.assignment.id)}</dd>
              </div>
              <div>
                <dt>State</dt>
                <dd>{details.lifecycle.state}</dd>
              </div>
              <div>
                <dt>Expires</dt>
                <dd>{formatEpoch(details.lifecycle.expires_at_epoch)}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{details.source.content_state}</dd>
              </div>
              <div>
                <dt>Retention until</dt>
                <dd>{formatEpoch(details.source.retention_until_epoch)}</dd>
              </div>
              <div>
                <dt>Run</dt>
                <dd>{details.review.run_state}</dd>
              </div>
            </dl>
            {details.lifecycle.revocation ? (
              <p className={styles.revocation}>
                <Clock3 size={14} aria-hidden="true" /> Revoked{" "}
                {formatEpoch(details.lifecycle.revocation.created_at_epoch)}
              </p>
            ) : null}
          </div>
          <div className={styles.feedbackList}>
            {details.feedback.length === 0 ? (
              <p className={styles.empty} role="status">
                No saved feedback is available for this assignment.
              </p>
            ) : (
              details.feedback.map((item) => (
                <FeedbackItem item={item} key={item.id} />
              ))
            )}
          </div>
          {details.feedback_truncated ? (
            <p className={styles.truncated} role="note">
              Showing the first 100 feedback entries; the server reports{" "}
              {details.feedback_count} total.
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
