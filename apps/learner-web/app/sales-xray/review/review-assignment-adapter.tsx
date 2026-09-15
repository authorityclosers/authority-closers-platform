"use client";

import { AssignedReviewForm } from "@ac/sales-xray-review-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createReviewAssignmentApi,
  reviewApiErrorMessage,
  type LoadedReviewAssignment,
  type SavedReview,
} from "./review-assignment-api";
import styles from "./review-assignment.module.css";
import { registerReviewNavigationGuard } from "./review-navigation";

export function ReviewAssignmentAdapter({
  assignmentId,
}: {
  assignmentId: string;
}) {
  return (
    <ReviewAssignmentSession key={assignmentId} assignmentId={assignmentId} />
  );
}

function ReviewAssignmentSession({ assignmentId }: { assignmentId: string }) {
  const api = useMemo(() => createReviewAssignmentApi(), []);
  const current = useRef(assignmentId);
  const [loaded, setLoaded] = useState<LoadedReviewAssignment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [history, setHistory] = useState<SavedReview[]>([]);
  const [historyState, setHistoryState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [historyError, setHistoryError] = useState("");

  const loadHistory = useCallback(
    async (value: LoadedReviewAssignment, signal?: AbortSignal) => {
      setHistoryState("loading");
      try {
        const items = await api.history(value, signal);
        if (signal?.aborted || current.current !== value.binding.id) return;
        // Preserve a newly confirmed POST if an earlier GET finishes afterwards.
        setHistory((previous) => {
          const byId = new Map(
            [
              ...items,
              ...previous.filter(
                (item) => item.assignment_id === value.binding.id,
              ),
            ].map((item) => [item.id, item]),
          );
          return [...byId.values()].sort(
            (a, b) => a.created_at_epoch - b.created_at_epoch,
          );
        });
        setHistoryState("ready");
      } catch (reason) {
        if (signal?.aborted || current.current !== value.binding.id) return;
        setHistoryError(reviewApiErrorMessage(reason));
        setHistoryState("error");
      }
    },
    [api],
  );

  useEffect(() => {
    const controller = new AbortController();
    current.current = assignmentId;
    void api
      .get(assignmentId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setLoaded(value);
        void loadHistory(value, controller.signal);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reviewApiErrorMessage(reason));
      });
    return () => {
      current.current = "";
      controller.abort();
    };
  }, [api, assignmentId, reload, loadHistory]);

  return (
    <main id="main-content" className="learner-main" tabIndex={-1}>
      <div className="page-container">
        <div className={styles.page}>
          <div className={styles.breadcrumb}>Sales Xray / Assigned review</div>
          <h1 className={styles.title}>Conversation review</h1>
          {loaded?.binding.id === assignmentId ? (
            <>
              <AssignedReviewForm
                key={assignmentId}
                assignment={loaded.assignment}
                registerNavigationGuard={registerReviewNavigationGuard}
                verifyAudioAccess={async () => {
                  try {
                    await api.get(assignmentId);
                  } catch (reason) {
                    throw new Error(reviewApiErrorMessage(reason));
                  }
                }}
                onSubmit={async (draft, key) => {
                  try {
                    const saved = await api.submit(loaded, draft, key);
                    if (current.current === assignmentId) {
                      setHistory((items) =>
                        items.some((item) => item.id === saved.id)
                          ? items
                          : [...items, saved],
                      );
                    }
                    return { submission_id: saved.id };
                  } catch (reason) {
                    throw new Error(reviewApiErrorMessage(reason));
                  }
                }}
              />
              <section
                className={styles.history}
                aria-labelledby="review-history-title"
              >
                <div className={styles.historyHeading}>
                  <div>
                    <span className={styles.eyebrow}>Saved feedback</span>
                    <h2 id="review-history-title">Review history</h2>
                  </div>
                  <button
                    type="button"
                    disabled={historyState === "loading"}
                    onClick={() => void loadHistory(loaded)}
                  >
                    Refresh history
                  </button>
                </div>
                {historyState === "loading" ? (
                  <p role="status">Loading saved feedback…</p>
                ) : null}
                {historyState === "error" ? (
                  <p role="alert">
                    {historyError} Use Refresh history to retry.
                  </p>
                ) : null}
                {historyState === "ready" && history.length === 0 ? (
                  <p>No feedback has been saved for this assignment yet.</p>
                ) : null}
                {history.map((item) => (
                  <article key={item.id} className={styles.historyItem}>
                    <div>
                      <strong>
                        {item.lens === "ux"
                          ? "UX"
                          : item.lens === "sales"
                            ? "Sales"
                            : "Technical"}{" "}
                        review
                      </strong>
                      <span>
                        {" "}
                        · {item.confidence} confidence ·{" "}
                        {new Date(
                          item.created_at_epoch * 1000,
                        ).toLocaleString()}
                      </span>
                    </div>
                    <p>{item.feedback}</p>
                    <small>
                      Evidence:{" "}
                      {item.evidence_refs.map((ref) => ref.span_id).join(", ")}
                    </small>
                    {item.proposed_correction ? (
                      <dl>
                        <div>
                          <dt>Correction area</dt>
                          <dd>
                            {item.proposed_correction.target_layer.replaceAll(
                              "_",
                              " ",
                            )}
                          </dd>
                        </div>
                        <div>
                          <dt>Current observation</dt>
                          <dd>{item.proposed_correction.actual}</dd>
                        </div>
                        <div>
                          <dt>Suggested correction</dt>
                          <dd>{item.proposed_correction.expected}</dd>
                        </div>
                        <div>
                          <dt>Reason</dt>
                          <dd>{item.proposed_correction.rationale}</dd>
                        </div>
                      </dl>
                    ) : null}
                    <small>
                      Submission <code>{item.id}</code>
                    </small>
                  </article>
                ))}
                {history.length >= 100 ? (
                  <p>
                    The service returns the first 100 saved reviews. Newly
                    confirmed feedback also appears during this visit.
                  </p>
                ) : null}
              </section>
            </>
          ) : (
            <section className={styles.pending} aria-label="Assignment status">
              {error ? (
                <>
                  <h2>Review unavailable</h2>
                  <p role="alert">{error}</p>
                  <button
                    type="button"
                    onClick={() => {
                      setLoaded(null);
                      setError(null);
                      setHistory([]);
                      setHistoryState("loading");
                      setReload((value) => value + 1);
                    }}
                  >
                    Retry assignment
                  </button>
                </>
              ) : (
                <p role="status">Loading your assigned report and evidence…</p>
              )}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
