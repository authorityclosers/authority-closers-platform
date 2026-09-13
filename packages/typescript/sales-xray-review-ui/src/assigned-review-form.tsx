"use client";

import { useEffect, useRef, useState } from "react";

import styles from "./assigned-review-form.module.css";

export const REVIEW_LENSES = ["sales", "technical", "ux"] as const;
export type ReviewLens = (typeof REVIEW_LENSES)[number];
export const CORRECTION_TARGETS = {
  sales: ["context", "profile", "judge"],
  technical: ["transcript", "measurement", "attribution", "alignment"],
  ux: ["ux_metadata"],
} as const;
export type ReviewCorrection = Readonly<{
  target_layer: (typeof CORRECTION_TARGETS)[ReviewLens][number];
  actual: string;
  expected: string;
  rationale: string;
}>;

export type ReviewClip = Readonly<{
  segment_id: string;
  start_ms: number;
  end_ms: number;
  playback_url: string;
  checkpoint_id?: string;
  quote?: string | null;
}>;

export type ReviewAssignment = Readonly<{
  assignment_id: string;
  recording_id: string;
  run_revision: string;
  cursor?: string;
  checkpoint_id?: string;
  reviewer: Readonly<{ person_id: string; display_name: string }>;
  report: Readonly<{
    title: string;
    summary: string;
    verdict?: string;
    groups?: readonly Readonly<{
      title: string;
      findings: readonly Readonly<{
        title: string;
        explanation: string;
        evidence: readonly string[];
      }>[];
    }>[];
  }>;
  clips: readonly ReviewClip[];
  allowed_lenses: readonly ReviewLens[];
}>;

export type ReviewProposalDraft = Readonly<{
  assignment_id: string;
  recording_id: string;
  run_revision: string;
  reviewer_id: string;
  lens: ReviewLens;
  clip: Readonly<
    Pick<ReviewClip, "segment_id" | "start_ms" | "end_ms" | "checkpoint_id">
  > | null;
  feedback: string;
  confidence: string;
  proposed_correction?: ReviewCorrection;
}>;

export type ReviewSubmissionReceipt = Readonly<{
  submission_id: string;
  cursor?: string;
}>;

export type SubmitReviewProposal = (
  draft: ReviewProposalDraft,
  idempotencyKey: string,
) => Promise<ReviewSubmissionReceipt>;

function formatTimestamp(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  const fraction = milliseconds % 1000;
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}${fraction ? `.${String(fraction).padStart(3, "0")}` : ""}`;
}

function idempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  throw new Error("Secure review submission identity is unavailable.");
}

const lensCopy: Record<
  ReviewLens,
  Readonly<{ label: string; detail: string }>
> = {
  sales: { label: "Sales", detail: "Context and adjudication" },
  technical: { label: "Technical", detail: "Transcript and measurement" },
  ux: { label: "UX", detail: "Review experience and usability" },
};

export function AssignedReviewForm({
  assignment,
  onSubmit,
  registerNavigationGuard,
  verifyAudioAccess,
}: {
  assignment: ReviewAssignment;
  onSubmit: SubmitReviewProposal;
  registerNavigationGuard?: (dirty: boolean) => () => void;
  verifyAudioAccess?: () => Promise<void>;
}) {
  const player = useRef<HTMLAudioElement>(null);
  const statusMessage = useRef<HTMLDivElement>(null);
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const saving = useRef(false);
  const firstLens = assignment.allowed_lenses.find((lens) =>
    REVIEW_LENSES.includes(lens),
  );
  const [lens, setLens] = useState<ReviewLens>(firstLens ?? "sales");
  const [clip, setClip] = useState<ReviewClip | null>(
    assignment.clips[0] ?? null,
  );
  const [feedback, setFeedback] = useState("");
  const [confidence, setConfidence] = useState("");
  const [correction, setCorrection] = useState(false);
  const [target, setTarget] = useState<ReviewCorrection["target_layer"]>(
    CORRECTION_TARGETS[lens][0],
  );
  const [actual, setActual] = useState("");
  const [expected, setExpected] = useState("");
  const [rationale, setRationale] = useState("");
  const [audioError, setAudioError] = useState<string | null>(null);
  const [submitState, setSubmitState] = useState<
    | { status: "idle" }
    | { status: "submitting"; key: string }
    | { status: "error"; message: string }
    | { status: "saved"; receipt: ReviewSubmissionReceipt }
  >({ status: "idle" });

  const locked =
    submitState.status === "submitting" || submitState.status === "saved";
  const dirty =
    Boolean(feedback || actual || expected || rationale) &&
    submitState.status !== "saved";
  useEffect(
    () => registerNavigationGuard?.(dirty),
    [dirty, registerNavigationGuard],
  );
  useEffect(() => {
    if (submitState.status === "saved" || submitState.status === "error")
      statusMessage.current?.focus();
  }, [submitState.status]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const canSubmit = Boolean(
    assignment.allowed_lenses.includes(lens) &&
      clip &&
      feedback.trim() &&
      feedback.length <= 4000 &&
      ["low", "medium", "high"].includes(confidence) &&
      (!correction || (actual.trim() && expected.trim() && rationale.trim())),
  );

  async function submit() {
    if (!canSubmit || locked || saving.current) return;
    const draft: ReviewProposalDraft = {
      assignment_id: assignment.assignment_id,
      recording_id: assignment.recording_id,
      run_revision: assignment.run_revision,
      reviewer_id: assignment.reviewer.person_id,
      lens,
      clip: clip
        ? {
            segment_id: clip.segment_id,
            start_ms: clip.start_ms,
            end_ms: clip.end_ms,
            checkpoint_id: clip.checkpoint_id,
          }
        : null,
      feedback: feedback.trim(),
      confidence: confidence.trim(),
      ...(correction
        ? {
            proposed_correction: {
              target_layer: target,
              actual: actual.trim(),
              expected: expected.trim(),
              rationale: rationale.trim(),
            },
          }
        : {}),
    };
    saving.current = true;
    try {
      const fingerprint = JSON.stringify(draft);
      if (attempt.current?.fingerprint !== fingerprint)
        attempt.current = { fingerprint, key: idempotencyKey() };
      setSubmitState({ status: "submitting", key: attempt.current.key });
      const receipt = await onSubmit(draft, attempt.current.key);
      setSubmitState({ status: "saved", receipt });
    } catch (error) {
      setSubmitState({
        status: "error",
        message:
          error instanceof Error
            ? error.message
            : "The proposal could not be saved. Your draft is still here.",
      });
    } finally {
      saving.current = false;
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
        <span className={styles.boundPill}>DRAFT REPORT</span>
      </div>
      <p className={styles.disclaimer}>
        Qualitative draft awaiting adjudication. No numeric score is published.
      </p>
      <details className={styles.report}>
        <summary>Read the full report</summary>
        {assignment.report.groups?.map((group) => (
          <section key={group.title}>
            <h3>{group.title}</h3>
            {group.findings.length ? (
              group.findings.map((finding, index) => (
                <article key={index}>
                  <h4>{finding.title}</h4>
                  <p>{finding.explanation}</p>
                  {finding.evidence.map((evidence, evidenceIndex) => (
                    <blockquote key={evidenceIndex}>{evidence}</blockquote>
                  ))}
                </article>
              ))
            ) : (
              <p>No findings supplied for this section.</p>
            )}
          </section>
        ))}
        {assignment.report.verdict ? (
          <section>
            <h3>Draft verdict</h3>
            <p>{assignment.report.verdict}</p>
          </section>
        ) : null}
      </details>

      <dl className={styles.facts}>
        <div>
          <dt>Reviewer</dt>
          <dd>{assignment.reviewer.display_name}</dd>
          <dd>
            <small>Person ID: {assignment.reviewer.person_id}</small>
          </dd>
        </div>
        <div>
          <dt>Run revision</dt>
          <dd>
            <code>{assignment.run_revision}</code>
          </dd>
        </div>
        <div>
          <dt>Assignment</dt>
          <dd>
            <code>{assignment.assignment_id}</code>
          </dd>
        </div>
      </dl>

      <div className={styles.evidence}>
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Evidence</span>
            <h3>Listen to the exact moments</h3>
          </div>
          <span className={styles.smallPill}>
            {assignment.clips.length} clips
          </span>
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
              onLoadedMetadata={() => {
                if (player.current)
                  player.current.currentTime = clip.start_ms / 1000;
              }}
              onPlay={() => {
                if (
                  player.current &&
                  (player.current.currentTime < clip.start_ms / 1000 ||
                    player.current.currentTime >= clip.end_ms / 1000)
                )
                  player.current.currentTime = clip.start_ms / 1000;
              }}
              onTimeUpdate={() => {
                if (
                  player.current &&
                  player.current.currentTime >= clip.end_ms / 1000
                )
                  player.current.pause();
              }}
              onError={() => {
                setAudioError(
                  "Audio could not be played. Retry to check the source again.",
                );
                if (verifyAudioAccess)
                  void verifyAudioAccess().catch((error: unknown) => {
                    setAudioError(
                      error instanceof Error
                        ? error.message
                        : "Review access could not be verified.",
                    );
                  });
              }}
            />
            {audioError ? (
              <p role="alert">
                {audioError}{" "}
                <button
                  type="button"
                  onClick={() => {
                    setAudioError(null);
                    player.current?.load();
                  }}
                >
                  Retry audio
                </button>
              </p>
            ) : null}
            <p className={styles.quote}>
              {clip.quote ?? "No transcript quote supplied."}
            </p>
          </>
        ) : (
          <p className={styles.empty}>
            The server returned no playable clip for this assignment.
          </p>
        )}
        <div
          className={styles.clipList}
          role="group"
          aria-label="Timestamped clips"
        >
          {assignment.clips.map((candidate) => (
            <button
              type="button"
              aria-pressed={clip?.segment_id === candidate.segment_id}
              disabled={locked}
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
              <span>
                {formatTimestamp(candidate.start_ms)}–
                {formatTimestamp(candidate.end_ms)}
              </span>
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
              disabled={locked || !available}
              key={candidate}
              onClick={() => {
                setLens(candidate);
                setTarget(CORRECTION_TARGETS[candidate][0]);
              }}
            >
              <strong>{lensCopy[candidate].label}</strong>
              <small>{lensCopy[candidate].detail}</small>
            </button>
          );
        })}
      </div>

      <div className={styles.fieldGrid}>
        <label>
          Feedback
          <textarea
            aria-label="Feedback"
            aria-describedby="review-feedback-count"
            value={feedback}
            disabled={locked}
            maxLength={4000}
            onChange={(event) => setFeedback(event.target.value)}
            placeholder="Capture the observable correction or feedback."
          />
          <small id="review-feedback-count">
            {feedback.length}/4000 characters
          </small>
        </label>
        <label>
          Confidence
          <select
            aria-label="Confidence"
            value={confidence}
            disabled={locked}
            onChange={(event) => setConfidence(event.target.value)}
          >
            <option value="">Select confidence</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
      </div>

      <label className={styles.check}>
        <input
          type="checkbox"
          checked={correction}
          disabled={locked}
          onChange={(event) => setCorrection(event.target.checked)}
        />
        Suggest a specific correction
      </label>
      {correction ? (
        <div className={styles.fieldGrid}>
          <label>
            Correction area
            <select
              aria-label="Correction area"
              disabled={locked}
              value={target}
              onChange={(event) =>
                setTarget(
                  event.target.value as ReviewCorrection["target_layer"],
                )
              }
            >
              {CORRECTION_TARGETS[lens].map((area) => (
                <option key={area} value={area}>
                  {area.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Current observation
            <textarea
              disabled={locked}
              maxLength={512}
              value={actual}
              onChange={(event) => setActual(event.target.value)}
            />
          </label>
          <label>
            Suggested correction
            <textarea
              disabled={locked}
              maxLength={512}
              value={expected}
              onChange={(event) => setExpected(event.target.value)}
            />
          </label>
          <label>
            Reason
            <textarea
              disabled={locked}
              maxLength={512}
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
            />
          </label>
        </div>
      ) : null}
      {submitState.status === "error" ? (
        <div
          className={styles.error}
          role="alert"
          tabIndex={-1}
          ref={statusMessage}
        >
          <strong>{submitState.message}</strong>
          <span>
            Retry unchanged feedback to recover the same submission. Editing
            creates a new submission.
          </span>
        </div>
      ) : null}
      {submitState.status === "saved" ? (
        <div
          className={styles.success}
          role="status"
          tabIndex={-1}
          ref={statusMessage}
        >
          <strong>Feedback saved.</strong>
          <span>
            {submitState.receipt.cursor ? (
              <>
                Server cursor: <code>{submitState.receipt.cursor}</code>
              </>
            ) : (
              <>
                Submission ID: <code>{submitState.receipt.submission_id}</code>
              </>
            )}
          </span>
        </div>
      ) : null}
      <button
        className={styles.submit}
        type="button"
        disabled={
          !canSubmit ||
          submitState.status === "submitting" ||
          submitState.status === "saved"
        }
        onClick={() => void submit()}
      >
        {submitState.status === "submitting"
          ? "Saving proposal…"
          : submitState.status === "saved"
            ? "Proposal saved"
            : submitState.status === "error"
              ? "Retry save"
              : "Save feedback"}
      </button>
      {submitState.status === "saved" ? (
        <button
          type="button"
          className={styles.clipButton}
          onClick={() => {
            setFeedback("");
            setConfidence("");
            setCorrection(false);
            setActual("");
            setExpected("");
            setRationale("");
            attempt.current = null;
            setSubmitState({ status: "idle" });
          }}
        >
          Add another review
        </button>
      ) : null}
      <p className={styles.disclaimer}>
        Saved feedback is added to the review history. Original evidence and
        earlier reviews remain unchanged.
      </p>
    </section>
  );
}
