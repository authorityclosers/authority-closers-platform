"use client";

import { useRef, useState } from "react";

import styles from "./assigned-review-form.module.css";

export const REVIEW_LENSES = ["sales", "technical", "ux"] as const;
export type ReviewLens = (typeof REVIEW_LENSES)[number];

export type ReviewClip = Readonly<{
  segment_id: string;
  start_ms: number;
  end_ms: number;
  playback_url: string;
  quote?: string | null;
}>;

export type ReviewAssignment = Readonly<{
  assignment_id: string;
  recording_id: string;
  run_revision: string;
  cursor: string;
  reviewer: Readonly<{ person_id: string; display_name: string }>;
  report: Readonly<{ title: string; summary: string }>;
  clips: readonly ReviewClip[];
  allowed_lenses: readonly ReviewLens[];
}>;

export type ReviewProposalDraft = Readonly<{
  assignment_id: string;
  recording_id: string;
  run_revision: string;
  reviewer_id: string;
  lens: ReviewLens;
  clip: Readonly<Pick<ReviewClip, "segment_id" | "start_ms" | "end_ms">> | null;
  feedback: string;
  confidence: string;
}>;

export type ReviewSubmissionReceipt = Readonly<{
  submission_id: string;
  cursor: string;
}>;

export type SubmitReviewProposal = (
  draft: ReviewProposalDraft,
  idempotencyKey: string,
) => Promise<ReviewSubmissionReceipt>;

function formatTimestamp(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function idempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  throw new Error("Secure review submission identity is unavailable.");
}

const lensCopy: Record<ReviewLens, Readonly<{ label: string; detail: string }>> = {
  sales: { label: "Sales", detail: "Context and adjudication" },
  technical: { label: "Technical", detail: "Transcript and measurement" },
  ux: { label: "UX", detail: "Attribution and alignment" },
};

export function AssignedReviewForm({
  assignment,
  onSubmit,
}: {
  assignment: ReviewAssignment;
  onSubmit: SubmitReviewProposal;
}) {
  const player = useRef<HTMLAudioElement>(null);
  const firstLens = assignment.allowed_lenses.find((lens) =>
    REVIEW_LENSES.includes(lens),
  );
  const [lens, setLens] = useState<ReviewLens>(firstLens ?? "sales");
  const [clip, setClip] = useState<ReviewClip | null>(assignment.clips[0] ?? null);
  const [feedback, setFeedback] = useState("");
  const [confidence, setConfidence] = useState("");
  const [submitState, setSubmitState] = useState<
    | { status: "idle" }
    | { status: "submitting"; key: string }
    | { status: "error"; key: string; message: string }
    | { status: "saved"; receipt: ReviewSubmissionReceipt }
  >({ status: "idle" });

  const canSubmit = Boolean(
    assignment.allowed_lenses.includes(lens) && feedback.trim() && confidence.trim(),
  );

  async function submit() {
    if (!canSubmit || submitState.status === "submitting") return;
    const key = submitState.status === "error" ? submitState.key : idempotencyKey();
    const draft: ReviewProposalDraft = {
      assignment_id: assignment.assignment_id,
      recording_id: assignment.recording_id,
      run_revision: assignment.run_revision,
      reviewer_id: assignment.reviewer.person_id,
      lens,
      clip: clip
        ? { segment_id: clip.segment_id, start_ms: clip.start_ms, end_ms: clip.end_ms }
        : null,
      feedback: feedback.trim(),
      confidence: confidence.trim(),
    };
    setSubmitState({ status: "submitting", key });
    try {
      const receipt = await onSubmit(draft, key);
      setSubmitState({ status: "saved", receipt });
    } catch (error) {
      setSubmitState({
        status: "error",
        key,
        message:
          error instanceof Error
            ? error.message
            : "The proposal could not be saved. Your draft is still here.",
      });
    }
  }

  return (
    <section className={styles.form} aria-labelledby="assigned-review-title">
      <div className={styles.header}>
        <div>
          <span className={styles.eyebrow}>Assigned review</span>
          <h2 id="assigned-review-title">{assignment.report.title}</h2>
          <p>{assignment.report.summary}</p>
        </div>
        <span className={styles.boundPill}>ASSIGNMENT BOUND</span>
      </div>

      <dl className={styles.facts}>
        <div>
          <dt>Reviewer</dt>
          <dd>{assignment.reviewer.display_name}</dd>
        </div>
        <div>
          <dt>Run revision</dt>
          <dd><code>{assignment.run_revision}</code></dd>
        </div>
        <div>
          <dt>Assignment</dt>
          <dd><code>{assignment.assignment_id}</code></dd>
        </div>
      </dl>

      <div className={styles.evidence}>
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Evidence</span>
            <h3>Listen to the exact moments</h3>
          </div>
          <span className={styles.smallPill}>{assignment.clips.length} clips</span>
        </div>
        {clip ? (
          <>
            <audio
              ref={player}
              className={styles.player}
              controls
              preload="metadata"
              src={clip.playback_url}
              aria-label="Assigned conversation clip"
            />
            <p className={styles.quote}>{clip.quote ?? "No transcript quote supplied."}</p>
          </>
        ) : (
          <p className={styles.empty}>The server returned no playable clip for this assignment.</p>
        )}
        <div className={styles.clipList} role="list" aria-label="Timestamped clips">
          {assignment.clips.map((candidate) => (
            <button
              type="button"
              role="listitem"
              className={`${styles.clipButton}${clip?.segment_id === candidate.segment_id ? ` ${styles.clipButtonActive}` : ""}`}
              key={`${candidate.segment_id}:${candidate.start_ms}`}
              onClick={() => {
                setClip(candidate);
                if (player.current) {
                  player.current.currentTime = candidate.start_ms / 1000;
                  void player.current.play().catch(() => undefined);
                }
              }}
            >
              <span>{candidate.segment_id}</span>
              <span>{formatTimestamp(candidate.start_ms)}–{formatTimestamp(candidate.end_ms)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Review lens</span>
          <h3>Choose the perspective for this proposal</h3>
        </div>
        <span className={styles.muted}>Lens changes the form only</span>
      </div>
      <div className={styles.lensGrid} role="group" aria-label="Review lens">
        {REVIEW_LENSES.map((candidate) => {
          const available = assignment.allowed_lenses.includes(candidate);
          return (
            <button
              type="button"
              className={`${styles.lensButton}${lens === candidate ? ` ${styles.lensButtonActive}` : ""}`}
              aria-pressed={lens === candidate}
              disabled={!available}
              key={candidate}
              onClick={() => setLens(candidate)}
            >
              <strong>{lensCopy[candidate].label}</strong>
              <small>{lensCopy[candidate].detail}</small>
            </button>
          );
        })}
      </div>

      <div className={styles.fieldGrid}>
        <label>
          Factual correction or feedback
          <textarea
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            placeholder="Capture the observable correction or feedback."
          />
          <small>Draft stays in this assignment until the server accepts it.</small>
        </label>
        <label>
          Confidence
          <input
            value={confidence}
            onChange={(event) => setConfidence(event.target.value)}
            placeholder="e.g. high — grounded in clip 00:42–01:08"
          />
        </label>
      </div>

      {submitState.status === "error" ? (
        <div className={styles.error} role="alert">
          <strong>{submitState.message}</strong>
          <span>Retry keeps the same draft and idempotency key.</span>
        </div>
      ) : null}
      {submitState.status === "saved" ? (
        <div className={styles.success} role="status">
          <strong>Proposal appended.</strong>
          <span>Server cursor: <code>{submitState.receipt.cursor}</code></span>
        </div>
      ) : null}
      <button
        className={styles.submit}
        type="button"
        disabled={!canSubmit || submitState.status === "submitting" || submitState.status === "saved"}
        onClick={() => void submit()}
      >
        {submitState.status === "submitting"
          ? "Saving proposal…"
          : submitState.status === "saved"
            ? "Proposal saved"
            : submitState.status === "error"
              ? "Retry append-only proposal"
              : "Save append-only proposal"}
      </button>
      <p className={styles.disclaimer}>
        Permission comes from the signed-in assignment. Lens is a review perspective,
        never a role grant; original evidence remains immutable.
      </p>
    </section>
  );
}
