"use client";

import {
  ArrowRight,
  AudioLines,
  FolderOpen,
  LoaderCircle,
  Plus,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AcquisitionShell } from "./acquisition-shell";
import { useUploadSnapshot } from "./hooks/upload-session";
import {
  acquisition,
  parseSubmissionLibraryPage,
  rememberSubmission,
  type LibrarySubmission,
} from "./acquisition-client";
import { useWorkspaceAccess } from "./workspace-access";
import { formatClock } from "./lightbox/time";
import { newCallHref } from "./new-call-navigation";
import { callTitle, type CallLabel } from "./call-label";
import { readCallLabel, renameCall } from "./call-label-client";
import { CallLabelEditor, RenameCallButton } from "./call-label-editor";

const libraryError =
  "Saved calls could not be loaded. Try again; your completed work remains private.";
const duplicateError =
  "The saved calls list could not be verified. Try again before opening a call.";
const libraryReadTimeoutMs = 12_000;
const processingRefreshIntervalMs = 15_000;

/*
 * The library's duration_seconds is the reserved (estimated) length recorded
 * when the call was admitted, not a measured source duration. It is always
 * presented as approximate until the list API supplies a measured field.
 */
function hasDurationEstimate(submission: LibrarySubmission) {
  return (
    Number.isFinite(submission.durationSeconds) &&
    submission.durationSeconds > 0
  );
}

function formatDuration(durationSeconds: number) {
  return `About ${formatClock(durationSeconds * 1000)}`;
}

function formatCreatedDate(createdAt: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
    new Date(createdAt),
  );
}

function formatCreatedTime(createdAt: string) {
  return new Intl.DateTimeFormat(undefined, { timeStyle: "short" }).format(
    new Date(createdAt),
  );
}

/** Status families from the saved state only; no inferred outcome. */
type CallTone = "ready" | "active" | "attention" | "idle";

function callTone(submission: LibrarySubmission): CallTone {
  if (submission.hasReport) return "ready";
  if (
    ["uploading", "queued", "processing", "running", "active"].includes(
      submission.state,
    )
  )
    return "active";
  if (["held", "uncertain", "failed", "blocked"].includes(submission.state))
    return "attention";
  return "idle";
}

const FILTERS: { id: "all" | CallTone; label: string }[] = [
  { id: "all", label: "All" },
  { id: "ready", label: "Report ready" },
  { id: "active", label: "In progress" },
  { id: "attention", label: "Needs attention" },
];

function openLabel(submission: LibrarySubmission) {
  const tone = callTone(submission);
  return tone === "ready"
    ? "Open report"
    : tone === "active"
      ? "View progress"
      : "Open call";
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

function isProcessing(submission: LibrarySubmission) {
  return (
    !submission.hasReport &&
    ["queued", "processing", "running", "active"].includes(submission.state)
  );
}

export function CallsLibrary({
  variant = "standalone",
  studioHref = "/",
  preview = false,
}: {
  variant?: "standalone" | "embedded";
  studioHref?: "/" | "/sales-xray";
  /** Compact account-backed home preview; hidden until saved rows exist. */
  preview?: boolean;
}) {
  const access = useWorkspaceAccess();
  const identityKey =
    access?.authenticated === true
      ? access.context
        ? JSON.stringify([
            access.context.personId,
            access.context.sessionId,
            access.context.tenantId,
          ])
        : "authenticated-context-pending"
      : `authentication:${String(access?.authenticated ?? "unknown")}`;
  return (
    <CallsLibraryContent
      key={identityKey}
      identityKey={identityKey}
      variant={variant}
      studioHref={studioHref}
      preview={preview}
    />
  );
}

function CallsLibraryContent({
  variant = "standalone",
  studioHref = "/",
  preview = false,
  identityKey,
}: {
  variant?: "standalone" | "embedded";
  studioHref?: "/" | "/sales-xray";
  /** Compact account-backed home preview; hidden until saved rows exist. */
  preview?: boolean;
  identityKey: string;
}) {
  const embedded = variant === "embedded";
  const Main = "div";
  const access = useWorkspaceAccess();
  const uploadSnapshot = useUploadSnapshot();
  const router = useRouter();
  const [submissions, setSubmissions] = useState<LibrarySubmission[]>([]);
  const submissionsRef = useRef<LibrarySubmission[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(access?.authenticated === true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  // Only the call being opened says so; the others are just unavailable.
  const [openingId, setOpeningId] = useState<string | null>(null);
  const opening = openingId !== null;
  const [filter, setFilter] = useState<"all" | CallTone>("all");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const seenSubmissionIds = useRef(new Set<string>());
  const firstPageSubmissionIds = useRef(new Set<string>());
  const loadedCursors = useRef(new Set<string>());
  const activeRequest = useRef<AbortController | null>(null);
  const activeRequestKind = useRef<"initial" | "more" | "refresh" | null>(null);
  const pendingRefresh = useRef<{
    identityKey: string;
    forceReset: boolean;
  } | null>(null);
  const refreshHandler = useRef<
    (identityKey: string, forceReset: boolean) => void
  >(() => {});
  // A saved outcome can outlive this view in the root upload provider. The
  // initial list read covers it; only a new saved ID after mount is a refresh
  // event for this identity.
  const lastSavedUploadId = useRef<string | null>(
    uploadSnapshot.phase === "saved" ? uploadSnapshot.submissionId : null,
  );
  const requestGeneration = useRef(0);
  const mounted = useRef(true);

  function refreshFirstPage(identityKey: string, forceReset: boolean) {
    if (!mounted.current || access?.authenticated !== true) return;
    if (activeRequest.current) {
      if (activeRequestKind.current === "refresh") {
        if (forceReset)
          pendingRefresh.current = { identityKey, forceReset: true };
        return;
      }
      const queued = pendingRefresh.current;
      pendingRefresh.current = {
        identityKey,
        forceReset: forceReset || queued?.forceReset === true,
      };
      return;
    }

    const controller = new AbortController();
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, libraryReadTimeoutMs);
    activeRequest.current = controller;
    activeRequestKind.current = "refresh";
    const generation = ++requestGeneration.current;
    setRefreshing(true);
    void acquisition("/submissions", { signal: controller.signal })
      .then((value) => {
        const page = parseSubmissionLibraryPage(value);
        if (
          controller.signal.aborted ||
          !mounted.current ||
          requestGeneration.current !== generation
        )
          return;

        const current = submissionsRef.current;
        const currentIds = new Set(current.map((submission) => submission.id));
        const refreshedFirstPageIds = new Set(
          page.submissions.map((submission) => submission.id),
        );
        const firstPageMembershipChanged =
          refreshedFirstPageIds.size !== firstPageSubmissionIds.current.size ||
          [...refreshedFirstPageIds].some(
            (id) => !firstPageSubmissionIds.current.has(id),
          );
        const hasNewSubmission = page.submissions.some(
          (submission) => !currentIds.has(submission.id),
        );
        const resetPage =
          forceReset || firstPageMembershipChanged || hasNewSubmission;
        const refreshedById = new Map(
          page.submissions.map((submission) => [submission.id, submission]),
        );
        const nextRows = resetPage
          ? page.submissions
          : current.map(
              (submission) => refreshedById.get(submission.id) ?? submission,
            );
        submissionsRef.current = nextRows;
        setSubmissions(nextRows);
        firstPageSubmissionIds.current = refreshedFirstPageIds;
        if (resetPage) {
          seenSubmissionIds.current = new Set(
            page.submissions.map((submission) => submission.id),
          );
          loadedCursors.current = new Set([""]);
          setNextCursor(page.nextCursor);
        }
        setError("");
      })
      .catch(() => {
        if (
          (!controller.signal.aborted || timedOut) &&
          mounted.current &&
          requestGeneration.current === generation &&
          access?.authenticated === true
        )
          setError(libraryError);
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (activeRequest.current === controller) {
          activeRequest.current = null;
          activeRequestKind.current = null;
        }
        if (mounted.current && requestGeneration.current === generation)
          setRefreshing(false);
        const queued = pendingRefresh.current;
        if (queued && queued.identityKey === identityKey) {
          pendingRefresh.current = null;
          refreshHandler.current(queued.identityKey, queued.forceReset);
        } else if (queued) {
          pendingRefresh.current = null;
        }
      });
  }

  useEffect(() => {
    refreshHandler.current = refreshFirstPage;
  });

  useEffect(
    () => () => {
      mounted.current = false;
      requestGeneration.current += 1;
      pendingRefresh.current = null;
      activeRequest.current?.abort();
      activeRequest.current = null;
    },
    [],
  );

  useEffect(() => {
    if (access?.authenticated !== true) return;
    const controller = new AbortController();
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, libraryReadTimeoutMs);
    activeRequest.current = controller;
    activeRequestKind.current = "initial";
    const generation = ++requestGeneration.current;
    mounted.current = true;
    void acquisition("/submissions", { signal: controller.signal })
      .then((value) => {
        const page = parseSubmissionLibraryPage(value);
        if (
          controller.signal.aborted ||
          !mounted.current ||
          requestGeneration.current !== generation
        )
          return;
        submissionsRef.current = page.submissions;
        firstPageSubmissionIds.current = new Set(
          page.submissions.map((submission) => submission.id),
        );
        for (const submission of page.submissions)
          seenSubmissionIds.current.add(submission.id);
        setSubmissions(page.submissions);
        setNextCursor(page.nextCursor);
      })
      .catch(() => {
        if (
          (!controller.signal.aborted || timedOut) &&
          mounted.current &&
          requestGeneration.current === generation
        )
          setError(libraryError);
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (activeRequest.current === controller) {
          activeRequest.current = null;
          activeRequestKind.current = null;
        }
        if (mounted.current && requestGeneration.current === generation)
          setLoading(false);
        const queued = pendingRefresh.current;
        if (queued && queued.identityKey === identityKey) {
          pendingRefresh.current = null;
          refreshHandler.current(queued.identityKey, queued.forceReset);
        } else if (queued) {
          pendingRefresh.current = null;
        }
      });
    return () => {
      controller.abort();
      if (activeRequest.current === controller) activeRequest.current = null;
      if (activeRequestKind.current === "initial")
        activeRequestKind.current = null;
      if (requestGeneration.current === generation)
        requestGeneration.current += 1;
    };
  }, [access?.authenticated, attempt, identityKey]);

  useEffect(() => {
    if (
      uploadSnapshot.phase !== "saved" ||
      uploadSnapshot.submissionId === lastSavedUploadId.current ||
      access?.authenticated !== true
    )
      return;
    lastSavedUploadId.current = uploadSnapshot.submissionId;
    refreshHandler.current(identityKey, true);
  }, [access?.authenticated, identityKey, uploadSnapshot]);

  useEffect(() => {
    const refreshIfProcessing = () => {
      if (
        document.visibilityState !== "hidden" &&
        submissionsRef.current.some(
          (submission, index) =>
            firstPageSubmissionIds.current.has(submission.id) &&
            (!preview || index < 3) &&
            isProcessing(submission),
        ) &&
        access?.authenticated === true
      )
        refreshHandler.current(identityKey, false);
    };
    window.addEventListener("focus", refreshIfProcessing);
    document.addEventListener("visibilitychange", refreshIfProcessing);
    return () => {
      window.removeEventListener("focus", refreshIfProcessing);
      document.removeEventListener("visibilitychange", refreshIfProcessing);
    };
  }, [access?.authenticated, identityKey, preview]);

  useEffect(() => {
    const hasProcessingRows = submissions.some(
      (submission, index) =>
        firstPageSubmissionIds.current.has(submission.id) &&
        (!preview || index < 3) &&
        isProcessing(submission),
    );
    if (access?.authenticated !== true || !hasProcessingRows) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "hidden")
        refreshHandler.current(identityKey, false);
    }, processingRefreshIntervalMs);
    return () => window.clearInterval(interval);
  }, [access?.authenticated, identityKey, preview, submissions]);

  async function loadMore() {
    const before = nextCursor;
    if (
      !before ||
      loading ||
      refreshing ||
      opening ||
      activeRequest.current !== null ||
      loadedCursors.current.has(before)
    )
      return;
    loadedCursors.current.add(before);
    setLoading(true);
    setError("");
    const controller = new AbortController();
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, libraryReadTimeoutMs);
    activeRequest.current = controller;
    activeRequestKind.current = "more";
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
      const appended = [...submissionsRef.current, ...page.submissions];
      submissionsRef.current = appended;
      for (const submission of page.submissions)
        seenSubmissionIds.current.add(submission.id);
      setSubmissions(appended);
      setNextCursor(page.nextCursor);
    } catch (caught) {
      loadedCursors.current.delete(before);
      if (
        (!controller.signal.aborted || timedOut) &&
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
      window.clearTimeout(timeout);
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        activeRequestKind.current = null;
      }
      if (mounted.current && requestGeneration.current === generation)
        setLoading(false);
      const queued = pendingRefresh.current;
      if (queued && queued.identityKey === identityKey) {
        pendingRefresh.current = null;
        refreshHandler.current(queued.identityKey, queued.forceReset);
      } else if (queued) {
        pendingRefresh.current = null;
      }
    }
  }

  function retry() {
    if (loading || refreshing) return;
    if (submissionsRef.current.length > 0 && access?.authenticated === true) {
      refreshHandler.current(identityKey, false);
      return;
    }
    requestGeneration.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    activeRequestKind.current = null;
    pendingRefresh.current = null;
    submissionsRef.current = [];
    firstPageSubmissionIds.current = new Set();
    seenSubmissionIds.current = new Set();
    loadedCursors.current = new Set([""]);
    setSubmissions([]);
    setNextCursor(null);
    setError("");
    setLoading(true);
    setAttempt((value) => value + 1);
  }

  /** Apply a server-confirmed label to its own row only. */
  function applyLabel(id: string, label: CallLabel) {
    const next = submissionsRef.current.map((row) =>
      row.id === id ? { ...row, label } : row,
    );
    submissionsRef.current = next;
    setSubmissions(next);
  }

  function openSubmission(submission: LibrarySubmission) {
    if (opening) return;
    setOpeningId(submission.id);
    rememberSubmission(submission.id);
    router.push(`${studioHref}?call=${submission.id}`);
  }

  const initialLoading = access?.authenticated === true && loading;
  const callsHref = "/calls";
  const counts = submissions.reduce(
    (total, submission) => {
      total[callTone(submission)] += 1;
      return total;
    },
    { ready: 0, active: 0, attention: 0, idle: 0 } as Record<CallTone, number>,
  );
  const visibleSubmissions =
    filter === "all"
      ? submissions
      : submissions.filter((submission) => callTone(submission) === filter);
  // Bars compare estimated lengths against the longest loaded estimate.
  const longestSeconds = Math.max(
    0,
    ...submissions
      .filter(hasDurationEstimate)
      .map((row) => row.durationSeconds),
  );
  const submissionButton = (submission: LibrarySubmission) => {
    const estimated = hasDurationEstimate(submission);
    const tone = callTone(submission);
    const isOpening = openingId === submission.id;
    const title = callTitle(
      submission.label,
      `Sales call · ${formatCreatedDate(submission.createdAt)}`,
    );
    // Rename needs a server that supplies labels; the server enforces ownership.
    const label = submission.label;
    if (renamingId === submission.id && label && !preview)
      return (
        <div
          className="calls-library-row"
          key={submission.id}
          data-renaming="true"
        >
          <div className="calls-library-rename">
            <CallLabelEditor
              label={label}
              onSave={(name, revision, signal) =>
                renameCall(submission.id, name, revision, signal)
              }
              onRefresh={(signal) => readCallLabel(submission.id, signal)}
              onConfirmed={(confirmed) => applyLabel(submission.id, confirmed)}
              onClose={() => setRenamingId(null)}
            />
          </div>
        </div>
      );
    return (
      <div className="calls-library-row" key={submission.id}>
        <button
          className="calls-library-item"
          data-submission-id={submission.id}
          data-tone={tone}
          type="button"
          disabled={opening}
          aria-busy={isOpening || undefined}
          onClick={() => openSubmission(submission)}
        >
          <span className="calls-library-icon" aria-hidden="true">
            <AudioLines size={19} />
          </span>
          <span className="calls-library-copy">
            <strong>{title}</strong>
            <small>
              {label?.displayName
                ? `${formatCreatedDate(submission.createdAt)} · ${formatCreatedTime(submission.createdAt)}`
                : formatCreatedTime(submission.createdAt)}
            </small>
          </span>
          <span
            className="calls-library-duration"
            aria-label={
              estimated
                ? `Estimated length: ${formatDuration(submission.durationSeconds)}`
                : "Length unavailable"
            }
            title={
              estimated
                ? "Estimated length, compared with the longest call in this list"
                : undefined
            }
          >
            <span className="calls-library-duration-track" aria-hidden="true">
              {estimated && longestSeconds > 0 ? (
                <span
                  className="calls-library-duration-fill"
                  style={{
                    width: `${Math.max(4, (submission.durationSeconds / longestSeconds) * 100)}%`,
                  }}
                />
              ) : null}
            </span>
            <span className="calls-library-duration-clock" aria-hidden="true">
              {estimated ? formatDuration(submission.durationSeconds) : "—"}
            </span>
          </span>
          <span className="calls-library-state" data-tone={tone}>
            {tone === "active" ? (
              <span className="calls-library-pulse" aria-hidden="true" />
            ) : null}
            {submissionState(submission)}
          </span>
          <span className="calls-library-open">
            {isOpening ? "Opening…" : openLabel(submission)}{" "}
            {isOpening ? (
              <LoaderCircle className="spin" size={15} aria-hidden="true" />
            ) : (
              <ArrowRight size={15} aria-hidden="true" />
            )}
          </span>
        </button>
        {label && !preview ? (
          <RenameCallButton
            callTitle={title}
            onClick={() => setRenamingId(submission.id)}
          />
        ) : null}
      </div>
    );
  };

  if (preview) {
    if (
      access?.authenticated !== true ||
      initialLoading ||
      submissions.length === 0
    )
      return null;
    return (
      <section
        className="panel calls-library-list-panel calls-library-preview"
        aria-labelledby="calls-library-preview-heading"
      >
        <div className="calls-library-list-heading">
          <div>
            <p className="eyebrow">PRIVATE CALL LIBRARY</p>
            <h2 id="calls-library-preview-heading">Recent calls</h2>
          </div>
          <Link className="text-button" href={callsHref}>
            View all calls
          </Link>
        </div>
        <div className="calls-library-items">
          {submissions.slice(0, 3).map(submissionButton)}
        </div>
        {error ? (
          <div className="calls-library-inline-error" role="alert">
            {error}
          </div>
        ) : null}
      </section>
    );
  }

  const content = (
    <div
      className="xray-app simple-app calls-library-app"
      data-theme="light"
      data-variant={variant}
    >
      <Main className="studio-main calls-library-main">
        {/* One page heading; privacy is one quiet line, not a second title. */}
        <header className="calls-library-intro">
          <div>
            <h1 id="calls-library-title">Calls</h1>
            <p className="calls-library-summary">
              {access?.authenticated === true && submissions.length > 0
                ? `${submissions.length}${nextCursor ? "+" : ""} saved ${submissions.length === 1 && !nextCursor ? "call" : "calls"} · private to your account and workspace`
                : "Private to your account and workspace"}
            </p>
          </div>
          {access?.authenticated === true ? (
            <Link href={newCallHref(studioHref)} className="calls-library-new">
              <Plus size={16} aria-hidden="true" /> New analysis
            </Link>
          ) : null}
        </header>

        {access?.authenticated === false ? (
          <section
            className="panel calls-library-state"
            aria-labelledby="calls-library-sign-in"
          >
            <span className="calls-library-state-icon" aria-hidden="true">
              <FolderOpen size={28} />
            </span>
            <h2 id="calls-library-sign-in">Sign in to see saved calls.</h2>
            <p>
              Keep your calls and reports together, then come back whenever you
              are ready to review the next step.
            </p>
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
        ) : initialLoading && visibleSubmissions.length === 0 ? (
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
            <Link href={newCallHref(studioHref)} className="secondary-button">
              Analyse a call <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </section>
        ) : (
          <section
            className="panel calls-library-list-panel"
            aria-labelledby="calls-library-title"
          >
            <div className="calls-library-list-heading">
              <div
                className="calls-library-filters"
                role="group"
                aria-label="Filter loaded calls by status"
              >
                {FILTERS.map((option) => {
                  const count =
                    option.id === "all"
                      ? submissions.length
                      : counts[option.id];
                  if (option.id !== "all" && count === 0) return null;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      aria-pressed={filter === option.id}
                      data-tone={option.id}
                      onClick={() => setFilter(option.id)}
                    >
                      {option.label}
                      <span className="calls-library-count">{count}</span>
                    </button>
                  );
                })}
              </div>
              <div className="calls-library-tools">
                {loading || refreshing ? (
                  <span className="calls-library-inline-status" role="status">
                    <LoaderCircle
                      className="spin"
                      size={15}
                      aria-hidden="true"
                    />{" "}
                    Updating…
                  </span>
                ) : null}
                <button
                  type="button"
                  className="text-button calls-library-refresh"
                  onClick={() => {
                    refreshHandler.current(identityKey, true);
                  }}
                  disabled={loading || refreshing || opening}
                >
                  <RefreshCw size={14} aria-hidden="true" /> Refresh
                </button>
              </div>
            </div>
            <div className="calls-library-columns" aria-hidden="true">
              <span />
              <span>Call</span>
              <span>Est. length</span>
              <span>Status</span>
              <span />
            </div>
            <div className="calls-library-items">
              {visibleSubmissions.map(submissionButton)}
            </div>
            {visibleSubmissions.length === 0 && submissions.length > 0 ? (
              <p className="calls-library-filter-empty" role="status">
                No loaded calls match this status.{" "}
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setFilter("all")}
                >
                  Show all calls
                </button>
              </p>
            ) : null}
            {filter !== "all" && nextCursor ? (
              <p className="calls-library-filter-note">
                The filter covers loaded calls only. Load more to include older
                calls.
              </p>
            ) : null}
            {nextCursor ? (
              <button
                type="button"
                className="secondary-button calls-library-more"
                onClick={() => void loadMore()}
                disabled={loading || refreshing || opening}
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
                    disabled={loading || refreshing || opening}
                  >
                    Try again
                  </button>
                ) : null}
              </div>
            ) : null}
          </section>
        )}
      </Main>
    </div>
  );
  if (embedded) return content;
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      homeHref={studioHref}
      active="calls"
      /* Calls read as a normal page: the document scrolls, not an inner box. */
      mobileFit={false}
    >
      {content}
    </AcquisitionShell>
  );
}
