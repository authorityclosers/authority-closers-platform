"use client";

import { AssignedReviewForm } from "@ac/sales-xray-review-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createReviewerAssignmentApi,
  reviewerErrorMessage,
  type LoadedReviewAssignment,
  type SavedReview,
  type Transcript,
} from "../reviewer-api";
import { registerReviewerNavigationGuard } from "./reviewer-navigation";
import styles from "./reviewer-workspace.module.css";

function formatTime(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function TranscriptPanel({ value }: { value: Transcript }) {
  const [query, setQuery] = useState("");
  const rows = value.segments.filter((segment) =>
    `${segment.speaker_id} ${segment.text} ${formatTime(segment.start_ms)}`.toLowerCase().includes(query.trim().toLowerCase()),
  );
  return (
    <section className={styles.transcript} aria-labelledby="full-transcript-title">
      <div className={styles.transcriptHeading}>
        <div>
          <span className={styles.eyebrow}>Source record</span>
          <h2 id="full-transcript-title">Full transcript</h2>
        </div>
        <span className={styles.metaPill}>{value.segments.length} segments</span>
      </div>
      <label className={styles.transcriptSearch}>
        Find a line
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search the transcript" />
      </label>
      <div className={styles.transcriptList} role="list" aria-label="Conversation transcript">
        {rows.map((segment) => (
          <article key={segment.id} className={styles.transcriptRow} role="listitem">
            <div className={styles.transcriptMeta}><span>{segment.speaker_id}</span><time>{formatTime(segment.start_ms)}</time></div>
            <p>{segment.text}</p>
          </article>
        ))}
        {rows.length === 0 ? <p className={styles.empty}>No transcript lines match this search.</p> : null}
      </div>
      <p className={styles.integrityNote}>Transcript revision {value.revision}. Source text is bound to this assignment and remains read-only.</p>
    </section>
  );
}

export function ReviewerAssignmentAdapter({ assignmentId }: { assignmentId: string }) {
  return <ReviewerAssignmentSession key={assignmentId} assignmentId={assignmentId} />;
}

function ReviewerAssignmentSession({ assignmentId }: { assignmentId: string }) {
  const api = useMemo(() => createReviewerAssignmentApi(), []);
  const current = useRef(assignmentId);
  const [loaded, setLoaded] = useState<LoadedReviewAssignment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [history, setHistory] = useState<SavedReview[]>([]);
  const [historyState, setHistoryState] = useState<"loading" | "ready" | "error">("loading");
  const [historyError, setHistoryError] = useState("");

  const loadHistory = useCallback(async (value: LoadedReviewAssignment, signal?: AbortSignal) => {
    setHistoryState("loading");
    try {
      const items = await api.history(value, signal);
      if (signal?.aborted || current.current !== value.binding.id) return;
      setHistory((previous) => {
        const byId = new Map([...items, ...previous.filter((item) => item.assignment_id === value.binding.id)].map((item) => [item.id, item]));
        return [...byId.values()].sort((a, b) => a.created_at_epoch - b.created_at_epoch);
      });
      setHistoryState("ready");
      setHistoryError("");
    } catch (reason) {
      if (signal?.aborted || current.current !== value.binding.id) return;
      setHistoryError(reviewerErrorMessage(reason));
      setHistoryState("error");
    }
  }, [api]);

  useEffect(() => {
    const controller = new AbortController();
    current.current = assignmentId;
    void api.get(assignmentId, controller.signal).then((value) => {
      if (controller.signal.aborted || current.current !== assignmentId) return;
      setLoaded(value);
      void loadHistory(value, controller.signal);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted && current.current === assignmentId) setError(reviewerErrorMessage(reason));
    });
    return () => { current.current = ""; controller.abort(); };
  }, [api, assignmentId, loadHistory, reload]);

  const retry = () => {
    setLoaded(null);
    setError(null);
    setHistory([]);
    setHistoryState("loading");
    setReload((value) => value + 1);
  };
  return (
    <main id="admin-content" className={styles.main} tabIndex={-1}>
      <div className={styles.container}>
        <div className={styles.breadcrumb}>Reviewer workspace / Assigned review</div>
        {loaded?.binding.id === assignmentId ? (
          <>
            <div className={styles.assignmentHeader}>
              <div>
                <span className={styles.eyebrow}>Private assigned source</span>
                <h1>Review the conversation</h1>
                <p>Listen to the exact call, inspect the report and transcript, then leave feedback through the lens you were assigned.</p>
              </div>
              <dl className={styles.assignmentFacts}>
                <div><dt>Assignment</dt><dd>{loaded.binding.id.slice(0, 8)}…</dd></div>
                <div><dt>Expires</dt><dd>{new Date(loaded.binding.expires_at_epoch * 1000).toLocaleString()}</dd></div>
                <div><dt>Lenses</dt><dd>{loaded.binding.allowed_lenses.join(" · ")}</dd></div>
              </dl>
            </div>
            <AssignedReviewForm
              key={assignmentId}
              assignment={loaded.assignment}
              registerNavigationGuard={registerReviewerNavigationGuard}
              verifyAudioAccess={async () => {
                try { await api.get(assignmentId); } catch (reason) { throw new Error(reviewerErrorMessage(reason)); }
              }}
              onSubmit={async (draft, key) => {
                try {
                  const saved = await api.submit(loaded, draft, key);
                  if (current.current === assignmentId) setHistory((items) => items.some((item) => item.id === saved.id) ? items : [...items, saved]);
                  return { submission_id: saved.id };
                } catch (reason) { throw new Error(reviewerErrorMessage(reason)); }
              }}
            />
            <TranscriptPanel value={loaded.transcript} />
            <section className={styles.history} aria-labelledby="review-history-title">
              <div className={styles.sectionHeading}>
                <div><span className={styles.eyebrow}>Saved feedback</span><h2 id="review-history-title">Review history</h2></div>
                <button className={styles.secondaryButton} type="button" disabled={historyState === "loading"} onClick={() => void loadHistory(loaded)}>Refresh history</button>
              </div>
              {historyState === "loading" ? <p role="status">Loading saved feedback…</p> : null}
              {historyState === "error" ? <p className={styles.error} role="alert">{historyError} Use Refresh history to retry.</p> : null}
              {historyState === "ready" && history.length === 0 ? <p className={styles.empty}>No feedback has been saved for this assignment yet.</p> : null}
              {history.map((item) => (
                <article key={item.id} className={styles.historyItem}>
                  <div className={styles.historyItemHeading}><strong>{item.lens === "ux" ? "UX" : item.lens === "sales" ? "Sales" : "Technical"} review</strong><span>{item.confidence} confidence · {new Date(item.created_at_epoch * 1000).toLocaleString()}</span></div>
                  <p>{item.feedback}</p>
                  <small>Evidence: {item.evidence_refs.map((ref) => ref.span_id).join(", ")}</small>
                  {item.proposed_correction ? <dl className={styles.correction}><div><dt>Correction area</dt><dd>{item.proposed_correction.target_layer.replaceAll("_", " ")}</dd></div><div><dt>Suggested correction</dt><dd>{item.proposed_correction.expected}</dd></div></dl> : null}
                  <small>Submission <code>{item.id}</code></small>
                </article>
              ))}
              {history.length >= 100 ? <p className={styles.integrityNote}>The service returns at most 100 saved reviews. Newly confirmed feedback remains visible during this visit.</p> : null}
            </section>
          </>
        ) : (
          <section className={styles.stateCard} aria-label="Assignment status">
            {error ? <><span className={styles.eyebrow}>Access check</span><h1>Review unavailable</h1><p className={styles.error} role="alert">{error}</p><button className={styles.primaryButton} type="button" onClick={retry}>Retry assignment</button></> : <p role="status">Loading your assigned report, transcript and evidence…</p>}
          </section>
        )}
      </div>
    </main>
  );
}
