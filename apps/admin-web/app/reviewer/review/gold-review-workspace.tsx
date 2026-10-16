"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  goldEndpoint,
  goldRequest,
  goldWorkspace,
  saveGold,
  type GoldRow,
  type GoldValue,
  type GoldWorkspace,
} from "./gold-review-api";
import { registerReviewerNavigationGuard } from "./reviewer-navigation";
import styles from "./gold-review-workspace.module.css";

function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : "This review did not load. Try again.";
}

/** Existing assignments retain their original feedback workspace. */
export function GoldReviewEntry({
  assignmentId,
  children,
}: {
  assignmentId: string;
  children: ReactNode;
}) {
  const [state, setState] = useState<GoldWorkspace | "legacy" | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void goldRequest(goldEndpoint(assignmentId), { signal: controller.signal })
      .then((body) => {
        if (!controller.signal.aborted) setState(goldWorkspace.parse(body));
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (
          reason &&
          typeof reason === "object" &&
          "status" in reason &&
          reason.status === 404
        )
          setState("legacy");
        else setError(message(reason));
      });
    return () => controller.abort();
  }, [assignmentId, attempt]);
  if (state === "legacy") return children;
  if (state)
    return (
      <GoldReviewWorkspace
        key={assignmentId}
        assignmentId={assignmentId}
        initial={state}
      />
    );
  return (
    <main id="admin-content" className={styles.main}>
      <section className={styles.panel} aria-busy={!error}>
        <h1>Review the sales call</h1>
        {error ? (
          <>
            <p role="alert">{error}</p>
            <button
              onClick={() => {
                setError("");
                setAttempt(attempt + 1);
              }}
            >
              Try again
            </button>
          </>
        ) : (
          <p role="status">Loading the saved AI report…</p>
        )}
      </section>
    </main>
  );
}

function texts(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(texts);
  if (value && typeof value === "object")
    return Object.entries(value)
      .filter(
        ([key]) =>
          ![
            "id",
            "number",
            "label",
            "score",
            "status",
            "segment_id",
            "start_ms",
            "end_ms",
            "owner",
          ].includes(key),
      )
      .flatMap(([, v]) => texts(v));
  return [];
}

export function AiValue({ value }: { value: unknown }) {
  const item =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  const feedback = texts(
    item
      ? Object.fromEntries(
          Object.entries(item).filter(([k]) => k !== "evidence"),
        )
      : value,
  );
  const evidence =
    item && Array.isArray(item.evidence)
      ? (item.evidence as { quote?: string }[])
      : [];
  return (
    <div className={styles.ai}>
      <span className={styles.eyebrow}>AI draft</span>
      {item &&
      (typeof item.status === "string" || typeof item.score === "number") ? (
        <p className={styles.status}>
          {typeof item.status === "string"
            ? item.status.replaceAll("_", " ")
            : ""}
          <strong>
            {typeof item.score === "number" ? `${item.score}/100` : "No score"}
          </strong>
        </p>
      ) : null}
      {feedback.length ? (
        feedback.map((line, i) => <p key={i}>{line}</p>)
      ) : (
        <p>
          No AI feedback was saved for this line. You can still leave your
          opinion.
        </p>
      )}
      {evidence.map((quote, i) =>
        quote.quote ? <blockquote key={i}>{quote.quote}</blockquote> : null,
      )}
    </div>
  );
}

function LineReview({
  line,
  saved,
  onSave,
  onDirty,
  reviewId,
  aiDigest,
}: {
  line: GoldWorkspace["lines"][number];
  saved: GoldRow | undefined;
  reviewId: string;
  aiDigest: string;
  onSave: (value: GoldValue, key: string) => Promise<GoldRow>;
  onDirty: (target: string, dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<GoldValue>(
    saved?.value ?? { verdict: null, score: null, opinion: "" },
  );
  const [status, setStatus] = useState<"idle" | "saving" | "saved">(
    saved ? "saved" : "idle",
  );
  const [error, setError] = useState("");
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const change = (next: GoldValue) => {
    setDraft(next);
    setStatus("idle");
    onDirty(
      line.target,
      JSON.stringify(next) !==
        JSON.stringify(
          saved?.value ?? { verdict: null, score: null, opinion: "" },
        ),
    );
  };
  const submit = async () => {
    setStatus("saving");
    setError("");
    const fingerprint = JSON.stringify(draft);
    if (retry.current?.fingerprint !== fingerprint)
      retry.current = { fingerprint, key: crypto.randomUUID() };
    try {
      await onSave(draft, retry.current.key);
      setStatus("saved");
      onDirty(line.target, false);
      retry.current = null;
    } catch (reason) {
      setError(message(reason));
      setStatus("idle");
    }
  };
  return (
    <details
      className={styles.line}
      open={line.target === "opening" || line.label.startsWith("1.")}
    >
      <summary>
        <span>{line.label}</span>
        <span className={styles.saved}>
          {status === "saved"
            ? "Saved to gold"
            : saved
              ? "Saved · changes pending"
              : "Needs your review"}
        </span>
      </summary>
      <div className={styles.columns}>
        <AiValue value={line.ai} />
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <span className={styles.eyebrow}>Your review</span>
          {saved &&
          (saved.review_id !== reviewId || saved.ai_sha256 !== aiDigest) ? (
            <p>
              Your saved opinion judged an earlier AI version. Save again to
              judge this version.
            </p>
          ) : null}
          <fieldset disabled={status === "saving"}>
            <legend>Do you agree with the AI?</legend>
            <div className={styles.verdicts}>
              {(
                [
                  ["agree", "Agree"],
                  ["partly", "Partly"],
                  ["disagree", "Disagree"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} data-selected={draft.verdict === key}>
                  <input
                    type="radio"
                    name={`${line.target}-verdict`}
                    checked={draft.verdict === key}
                    onChange={() => change({ ...draft, verdict: key })}
                  />
                  {label}
                </label>
              ))}
            </div>
            <label className={styles.score}>
              Your score <span>(optional, out of 100)</span>
              <input
                type="number"
                min="0"
                max="100"
                step="1"
                inputMode="numeric"
                value={draft.score ?? ""}
                onChange={(event) =>
                  change({
                    ...draft,
                    score:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  })
                }
              />
            </label>
            <label>
              Your opinion
              <textarea
                required
                minLength={1}
                maxLength={4000}
                rows={3}
                placeholder="What was right, what was missed, and what should the seller do?"
                value={draft.opinion}
                onChange={(event) =>
                  change({ ...draft, opinion: event.target.value })
                }
              />
            </label>
          </fieldset>
          <div className={styles.save}>
            <button
              type="submit"
              disabled={
                status === "saving" ||
                (!draft.verdict && draft.score === null) ||
                !draft.opinion.trim()
              }
            >
              {status === "saving"
                ? "Saving…"
                : status === "saved"
                  ? "Save another version"
                  : "Save this line"}
            </button>
            <span role="status">
              {status === "saved"
                ? "Saved to gold dataset"
                : "Each save keeps a new version"}
            </span>
          </div>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
        </form>
      </div>
    </details>
  );
}

export function GoldReviewWorkspace({
  assignmentId,
  initial,
}: {
  assignmentId: string;
  initial: GoldWorkspace;
}) {
  const [saved, setSaved] = useState(initial.saved);
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  useEffect(
    () => registerReviewerNavigationGuard(dirty.size > 0),
    [dirty.size],
  );
  const mark = (target: string, value: boolean) =>
    setDirty((old) => {
      const next = new Set(old);
      if (value) next.add(target);
      else next.delete(target);
      return next;
    });
  const progress = saved.filter((row) => row.value !== null).length;
  return (
    <main id="admin-content" className={styles.main}>
      <header className={styles.heading}>
        <div>
          <span className={styles.eyebrow}>Reviewer workspace</span>
          <h1>Review the sales call</h1>
          <p>
            Judge each pointer, the call outcome and the coaching. Your opinion
            saves straight to the gold dataset.
          </p>
        </div>
        <span className={styles.badge}>AI draft · not reviewed by Dipak</span>
      </header>
      <section className={styles.panel} aria-label="Call and review progress">
        <div className={styles.progress}>
          <strong>{progress} of 29 lines reviewed</strong>
          <span>
            {dirty.size
              ? `${dirty.size} unsaved ${dirty.size === 1 ? "line" : "lines"}`
              : "Every save keeps its history"}
          </span>
        </div>
        <progress value={progress} max={29} aria-label="Lines reviewed" />
        <p className={styles.meta}>
          Call {initial.call.recording_id.slice(0, 8)} · AI review{" "}
          {initial.review_id.slice(0, 8)}
        </p>
        <audio
          controls
          preload="none"
          src={`/v1/reviewer/review-assignments/${encodeURIComponent(assignmentId)}/source`}
          aria-label="Assigned sales call"
        />
        <details>
          <summary>Read the call transcript</summary>
          <div className={styles.transcript}>
            {initial.transcript.segments.map((segment) => (
              <p key={segment.id}>
                <strong>
                  {segment.speaker_id} · {Math.floor(segment.start_ms / 60000)}:
                  {String(Math.floor(segment.start_ms / 1000) % 60).padStart(
                    2,
                    "0",
                  )}
                </strong>{" "}
                {segment.text}
              </p>
            ))}
          </div>
        </details>
      </section>
      <div className={styles.list}>
        {initial.lines.map((line) => {
          const previous = saved.find((row) => row.target === line.target);
          return (
            <LineReview
              key={line.target}
              reviewId={initial.review_id}
              aiDigest={initial.ai_sha256}
              line={line}
              saved={previous}
              onDirty={mark}
              onSave={async (draft, key) => {
                const row = await saveGold(
                  assignmentId,
                  initial.review_id,
                  line.target,
                  draft,
                  previous?.id ?? null,
                  key,
                );
                setSaved((items) => [
                  ...items.filter((item) => item.target !== line.target),
                  row,
                ]);
                return row;
              }}
            />
          );
        })}
      </div>
    </main>
  );
}
