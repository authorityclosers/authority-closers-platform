"use client";

import { useState } from "react";
import {
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileSearch,
  LockKeyhole,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  UsersRound,
} from "lucide-react";

import { AdminShell } from "../../components/admin-shell";
import { AuditPanel, SectionHeading } from "../../components/ops-primitives";
import {
  AssignedReviewForm,
  type ReviewAssignment,
  type SubmitReviewProposal,
} from "@ac/sales-xray-review-ui";
import { type ReviewMode, type ReviewQueueState } from "./review-api";
import styles from "./review-workspace.module.css";

const modes: Array<{ id: ReviewMode; label: string; detail: string }> = [
  { id: "sales", label: "Sales", detail: "Context and adjudication" },
  { id: "technical", label: "Technical", detail: "Transcript and measurement" },
  { id: "ux", label: "UX", detail: "Attribution and alignment" },
];

type Reviewer = { id: string; name: string; detail: string };

const reviewers: Reviewer[] = [
  { id: "dipak", name: "Dipak", detail: "Server assignment required" },
  { id: "suyash", name: "Suyash", detail: "Server assignment required" },
];

function StatePanel({
  state,
  onRetry,
}: {
  state: ReviewQueueState;
  onRetry: () => void;
}) {
  if (state.status === "loading") {
    return (
      <div className={styles.queueState} role="status" aria-live="polite">
        <RefreshCw size={26} className="spin" aria-hidden="true" />
        <strong>Checking the review queue</strong>
        <p>
          Reading server-owned assignments and the current append-only cursor.
        </p>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className={styles.queueState} role="alert">
        <CircleAlert size={28} aria-hidden="true" />
        <strong>{state.message}</strong>
        <p>
          No report, reviewer, clip, or saved review is shown until the server
          returns an authorized response.
        </p>
        {state.retryable ? (
          <button
            className="button button-secondary"
            type="button"
            onClick={onRetry}
          >
            <RefreshCw size={15} aria-hidden="true" /> Retry queue
          </button>
        ) : null}
      </div>
    );
  }
  return null;
}

export function ReviewWorkspace({
  assignmentId,
  assignment,
  onSubmit,
}: {
  assignmentId: string;
  assignment?: ReviewAssignment;
  onSubmit?: SubmitReviewProposal;
}) {
  const [state] = useState<ReviewQueueState>({
    status: "error",
    message: "The review bridge contract is pending its server-owned DTO.",
    retryable: false,
  });
  const [selectedMode, setSelectedMode] = useState<ReviewMode>("sales");
  const [selectedReviewer, setSelectedReviewer] = useState("dipak");
  const [feedback, setFeedback] = useState("");
  const [confidence, setConfidence] = useState("");

  if (assignment && onSubmit) {
    return (
      <AdminShell
        active="overview"
        surface="organization"
        eyebrow="Review / assigned conversation evidence"
        title="Conversation review"
        description="Review a server-assigned conversation report with timestamped evidence, one lens at a time. Reviewer mode changes the form view; it never grants access."
      >
        <AssignedReviewForm assignment={assignment} onSubmit={onSubmit} />
      </AdminShell>
    );
  }

  return (
    <AdminShell
      active="overview"
      surface="organization"
      eyebrow="Review / assigned conversation evidence"
      title="Conversation review"
      description="Review a server-assigned conversation report with timestamped evidence, one lens at a time. Reviewer mode changes the form view; it never grants access."
    >
      <div className={styles.workspace} data-assignment-id={assignmentId}>
        <div className={styles.notice} role="note">
          <div className={styles.noticeIcon} aria-hidden="true">
            <ShieldCheck size={20} />
          </div>
          <div>
            <h2>Evidence stays private and append-only.</h2>
            <p>
              Reports, clips, identities, and review history must come from the
              authenticated tenant boundary. A correction supersedes a prior
              proposal; it never rewrites the original evidence.
            </p>
          </div>
          <span className={styles.noticeCode}>SERVER OWNED</span>
        </div>

        <div className={styles.layout}>
          <section className={styles.panel} aria-labelledby="queue-title">
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.eyebrow}>Assigned queue</span>
                <h2 id="queue-title">Reports awaiting review</h2>
              </div>
              <span className={`${styles.pill} ${styles.pillPending}`}>
                <Clock3 size={12} aria-hidden="true" /> Cursor bound
              </span>
            </div>
            <p className={styles.panelIntro}>
              The queue is paged by the server cursor. A stale cursor or changed
              tenant context must fail closed.
            </p>
            {state.status === "ready" ? (
              <div className={styles.queueState} role="status">
                <FileSearch size={28} aria-hidden="true" />
                <strong>Queue response received.</strong>
                <p>
                  The review contract is ready to render once its report and
                  assignment fields are bound to this surface.
                </p>
              </div>
            ) : (
              <StatePanel state={state} onRetry={() => undefined} />
            )}
          </section>

          <div className={styles.detailStack}>
            <section className={styles.panel} aria-labelledby="evidence-title">
              <SectionHeading
                eyebrow="Selected report / evidence player"
                id="evidence-title"
                title="Choose a report to inspect its clips."
                body="Playback will use the server-issued private clip URL and exact timestamps. The browser never constructs a storage key or accepts a caller supplied recording URL."
              />
              <div className={styles.playerPlaceholder}>
                <LockKeyhole size={20} aria-hidden="true" />
                <span>
                  Awaiting an authorized report selection for {assignmentId}
                </span>
              </div>
              <div className={styles.clipRow}>
                <span>No clip loaded</span>
                <span className={styles.pill}>0 clips</span>
              </div>
            </section>

            <section className={styles.panel} aria-labelledby="review-title">
              <div className={styles.panelHeader}>
                <div>
                  <span className={styles.eyebrow}>Review draft</span>
                  <h2 id="review-title">Record a lens-specific proposal</h2>
                </div>
                <MessageSquareText size={19} aria-hidden="true" />
              </div>
              <p className={styles.panelIntro}>
                You can prepare a draft while reviewing. Save stays disabled
                until an assigned report and the append-only write contract are
                present.
              </p>
              <div className={styles.disabledForm}>
                <div>
                  <span className={styles.eyebrow}>Reviewer</span>
                  <div
                    className={styles.reviewerGrid}
                    role="group"
                    aria-label="Reviewer identity"
                  >
                    {reviewers.map((reviewer) => (
                      <button
                        className={styles.reviewerButton}
                        type="button"
                        key={reviewer.id}
                        aria-pressed={selectedReviewer === reviewer.id}
                        onClick={() => setSelectedReviewer(reviewer.id)}
                      >
                        <strong>{reviewer.name}</strong>
                        <small>{reviewer.detail}</small>
                      </button>
                    ))}
                    <button
                      className={styles.reviewerButton}
                      type="button"
                      disabled
                    >
                      <strong>
                        <UsersRound size={14} aria-hidden="true" /> Invite
                        reviewer
                      </strong>
                      <small>Server assignment required</small>
                    </button>
                  </div>
                </div>
                <div>
                  <span className={styles.eyebrow}>Review mode</span>
                  <div
                    className={styles.modeGrid}
                    role="group"
                    aria-label="Review mode"
                  >
                    {modes.map((mode) => (
                      <button
                        className={styles.modeButton}
                        type="button"
                        key={mode.id}
                        aria-pressed={selectedMode === mode.id}
                        onClick={() => setSelectedMode(mode.id)}
                      >
                        <strong>{mode.label}</strong>
                        <small>{mode.detail}</small>
                      </button>
                    ))}
                  </div>
                </div>
                <div className={styles.fieldStack}>
                  <label htmlFor="review-feedback">
                    Factual correction or feedback
                    <textarea
                      id="review-feedback"
                      value={feedback}
                      onChange={(event) => setFeedback(event.target.value)}
                      placeholder="Capture the observable correction or feedback."
                    />
                    <span className={styles.fieldHint}>
                      Draft remains local until the server accepts an
                      append-only review proposal.
                    </span>
                  </label>
                  <label htmlFor="review-confidence">
                    Confidence
                    <input
                      id="review-confidence"
                      value={confidence}
                      onChange={(event) => setConfidence(event.target.value)}
                      placeholder="e.g. high — grounded in clip 00:42–01:08"
                    />
                  </label>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled
                  >
                    <CheckCircle2 size={15} aria-hidden="true" /> Save
                    append-only proposal (locked)
                  </button>
                </div>
              </div>
              <p className={styles.footnote}>
                Current selection: {selectedReviewer} · {selectedMode}. The role
                mode controls the lens only; permission remains
                server-authoritative.
              </p>
            </section>
          </div>
        </div>

        <AuditPanel
          id="review-audit"
          title="Review history is never overwritten."
          body="Every accepted proposal will bind the server assignment, report revision, clip evidence, reviewer identity, selected lens, confidence, and request idempotency key. No event is written by this disconnected UI."
          fields={[
            "Server-assigned report and immutable revision",
            "Authenticated reviewer and tenant context",
            "Timestamped clip evidence and factual rationale",
            "Append-only chain, cursor, and idempotency key",
          ]}
        />
      </div>
    </AdminShell>
  );
}
