"use client";

import { AudioLines, ArrowRight, LoaderCircle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BrandMark } from "@ac/ui";
import { AccountNavigation } from "./account-navigation";
import {
  acquisition,
  parseSubmissionLibraryPage,
  rememberSubmission,
  type LibrarySubmission,
} from "./acquisition-client";
import { useWorkspaceAccess } from "./workspace-access";

const libraryError =
  "Saved calls could not be loaded. Try again; your completed work remains private.";
const duplicateError =
  "The saved calls list could not be verified. Try again before opening a call.";

function formatDuration(durationSeconds: number) {
  return `About ${Math.floor(durationSeconds / 60)
    .toString()
    .padStart(1, "0")}:${(durationSeconds % 60).toString().padStart(2, "0")}`;
}

function formatCreatedAt(createdAt: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(createdAt));
}

const STATE_COPY: Record<string, string> = {
  awaiting_upload: "Ready to analyse",
  ready: "Ready to analyse",
  uploading: "Preparing call",
  queued: "Queued for analysis",
  processing: "Analysis in progress",
  running: "Analysis in progress",
  active: "Analysis in progress",
  completed: "Analysis complete",
  held: "Analysis paused",
  uncertain: "Needs attention",
  failed: "Needs attention",
  blocked: "Needs attention",
  cancelled: "Cancelled",
};

function submissionState(submission: LibrarySubmission) {
  return submission.hasReport
    ? "Report ready"
    : (STATE_COPY[submission.state] ?? "Saved call");
}

export function CallsLibrary() {
  const access = useWorkspaceAccess();
  const [submissions, setSubmissions] = useState<LibrarySubmission[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [opening, setOpening] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const seenSubmissionIds = useRef(new Set<string>());
  const loadedCursors = useRef(new Set<string>());
  const activeRequest = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);
  const mounted = useRef(true);

  useEffect(
    () => () => {
      mounted.current = false;
      requestGeneration.current += 1;
      activeRequest.current?.abort();
      activeRequest.current = null;
    },
    [],
  );

  useEffect(() => {
    if (access?.authenticated !== true) return;
    const controller = new AbortController();
    activeRequest.current?.abort();
    activeRequest.current = controller;
    const generation = ++requestGeneration.current;
    mounted.current = true;
    seenSubmissionIds.current = new Set();
    loadedCursors.current = new Set([""]);
    void acquisition("/submissions", { signal: controller.signal })
      .then((value) => {
        const page = parseSubmissionLibraryPage(value);
        if (
          controller.signal.aborted ||
          !mounted.current ||
          requestGeneration.current !== generation
        )
          return;
        for (const submission of page.submissions)
          seenSubmissionIds.current.add(submission.id);
        setSubmissions(page.submissions);
        setNextCursor(page.nextCursor);
      })
      .catch(() => {
        if (
          !controller.signal.aborted &&
          mounted.current &&
          requestGeneration.current === generation
        )
          setError(libraryError);
      })
      .finally(() => {
        if (
          !controller.signal.aborted &&
          mounted.current &&
          requestGeneration.current === generation
        )
          setLoading(false);
        if (activeRequest.current === controller) activeRequest.current = null;
      });
    return () => {
      controller.abort();
      if (activeRequest.current === controller) activeRequest.current = null;
      if (requestGeneration.current === generation)
        requestGeneration.current += 1;
    };
  }, [access?.authenticated, attempt]);

  async function loadMore() {
    const before = nextCursor;
    if (!before || loading || opening || loadedCursors.current.has(before))
      return;
    loadedCursors.current.add(before);
    setLoading(true);
    setError("");
    const controller = new AbortController();
    activeRequest.current?.abort();
    activeRequest.current = controller;
    const generation = ++requestGeneration.current;
    try {
      const page = parseSubmissionLibraryPage(
        await acquisition(`/submissions?before=${encodeURIComponent(before)}`, {
          signal: controller.signal,
        }),
      );
      if (
        controller.signal.aborted ||
        !mounted.current ||
        requestGeneration.current !== generation
      )
        return;
      if (page.nextCursor === before) throw new Error("library_cursor_loop");
      if (
        page.submissions.some((submission) =>
          seenSubmissionIds.current.has(submission.id),
        )
      )
        throw new Error("library_duplicate_submission");
      for (const submission of page.submissions)
        seenSubmissionIds.current.add(submission.id);
      setSubmissions((current) => [...current, ...page.submissions]);
      setNextCursor(page.nextCursor);
    } catch (caught) {
      loadedCursors.current.delete(before);
      if (
        !controller.signal.aborted &&
        mounted.current &&
        requestGeneration.current === generation
      )
        setError(
          caught instanceof Error &&
            (caught.message === "library_duplicate_submission" ||
              caught.message === "library_cursor_loop")
            ? duplicateError
            : libraryError,
        );
    } finally {
      if (
        !controller.signal.aborted &&
        mounted.current &&
        requestGeneration.current === generation
      )
        setLoading(false);
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }

  function retry() {
    if (loading) return;
    requestGeneration.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    setSubmissions([]);
    setNextCursor(null);
    setError("");
    setLoading(true);
    setAttempt((value) => value + 1);
  }

  function openSubmission(submission: LibrarySubmission) {
    if (opening) return;
    setOpening(true);
    rememberSubmission(submission.id);
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- Explicit row activation opens the existing acquisition studio in a fresh document.
    window.location.assign("/");
  }

  return (
    <div className="xray-app simple-app calls-library-app" data-theme="light">
      <header className="studio-header calls-library-header">
        <Link href="/" aria-label="Sales Xray home">
          <span className="studio-mark">
            <BrandMark />
          </span>
          <span>
            Dipak’s <strong>Sales Xray</strong>
            <small>AUTHORITY CLOSERS</small>
          </span>
        </Link>
        <AccountNavigation />
      </header>
      <main id="main" className="studio-main calls-library-main">
        <div className="calls-library-intro">
          <p className="eyebrow">YOUR AC ACCOUNT</p>
          <h1>Saved calls</h1>
          <p>
            Open a saved call and continue with its report in Sales Xray. Calls
            stay private to your account and selected workspace.
          </p>
        </div>

        {access?.authenticated === false ? (
          <section
            className="panel calls-library-state"
            aria-labelledby="calls-library-sign-in"
          >
            <h2 id="calls-library-sign-in">Sign in to see saved calls.</h2>
            <p>Your account keeps calls and reports together.</p>
            <Link href="/login" className="primary-button">
              Sign in <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </section>
        ) : error && submissions.length === 0 ? (
          <section className="panel calls-library-state" role="alert">
            <h2>Saved calls need another check.</h2>
            <p>{error}</p>
            <button
              type="button"
              className="secondary-button"
              onClick={retry}
              disabled={loading}
            >
              <RefreshCw size={16} aria-hidden="true" /> Try again
            </button>
          </section>
        ) : loading && submissions.length === 0 ? (
          <p className="calls-library-loading" role="status" aria-busy="true">
            <LoaderCircle className="spin" size={18} aria-hidden="true" />{" "}
            Checking your saved calls…
          </p>
        ) : submissions.length === 0 && !nextCursor ? (
          <section
            className="panel calls-library-state"
            aria-labelledby="calls-library-empty"
          >
            <AudioLines size={26} aria-hidden="true" />
            <h2 id="calls-library-empty">No saved calls yet.</h2>
            <p>Upload a call from the Sales Xray home page to begin.</p>
            <Link href="/" className="secondary-button">
              Analyse a call <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </section>
        ) : (
          <section
            className="panel calls-library-list-panel"
            aria-labelledby="calls-library-list-heading"
          >
            <div className="calls-library-list-heading">
              <div>
                <p className="eyebrow">PRIVATE CALL LIBRARY</p>
                <h2 id="calls-library-list-heading">Your calls</h2>
              </div>
              {loading ? (
                <span className="calls-library-inline-status" role="status">
                  <LoaderCircle className="spin" size={15} aria-hidden="true" />{" "}
                  Updating…
                </span>
              ) : null}
            </div>
            <div className="calls-library-items">
              {submissions.map((submission) => (
                <button
                  className="calls-library-item"
                  key={submission.id}
                  data-submission-id={submission.id}
                  type="button"
                  disabled={opening}
                  onClick={() => openSubmission(submission)}
                >
                  <span className="calls-library-icon" aria-hidden="true">
                    <AudioLines size={19} />
                  </span>
                  <span className="calls-library-copy">
                    <strong>
                      Sales call · {formatCreatedAt(submission.createdAt)}
                    </strong>
                    <small>{formatDuration(submission.durationSeconds)}</small>
                  </span>
                  <span className="calls-library-state">
                    {submissionState(submission)}
                  </span>
                  <span className="calls-library-open">
                    {opening ? "Opening…" : "Open call"}{" "}
                    <ArrowRight size={15} aria-hidden="true" />
                  </span>
                </button>
              ))}
            </div>
            {nextCursor ? (
              <button
                type="button"
                className="secondary-button calls-library-more"
                onClick={() => void loadMore()}
                disabled={loading || opening}
              >
                {loading ? "Loading…" : "Load more calls"}{" "}
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            ) : null}
            {error ? (
              <div className="calls-library-inline-error" role="alert">
                <span>{error}</span>
                {nextCursor ? (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => void loadMore()}
                    disabled={loading || opening}
                  >
                    Try again
                  </button>
                ) : null}
              </div>
            ) : null}
          </section>
        )}
      </main>
    </div>
  );
}
