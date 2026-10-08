"use client";

import { CALLS_PATH } from "./analysis-routes";
import { callHref } from "./acquisition-client";
import { callTone, submissionState, type CallTone } from "./call-status";
import {
  ArrowRight,
  ArrowUpDown,
  AudioLines,
  Clock,
  Download,
  Eye,
  FileText,
  Handshake,
  MessageCircleQuestion,
  FolderOpen,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { AcquisitionShell } from "./acquisition-shell";
import { useUploadSession, useUploadSnapshot } from "./hooks/upload-session";
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
import styles from "./calls-library.module.css";
import reps from "./calls-reps.module.css";
import { CallsDrawer } from "./calls-drawer";
import { useCallInsights, type CallInsight } from "./calls-insights";
import { csvRows } from "./csv-export";
import { MetricBand, MetricCard } from "./ui/metric-card";
import { OperationalEmpty, OperationalPanel } from "./ui/operational-panel";

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

export { callTone, submissionState };
export type { CallTone };

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

type CallSort = "newest" | "oldest" | "longest";

const SORTS: { id: CallSort; label: string }[] = [
  { id: "newest", label: "Newest first" },
  { id: "oldest", label: "Oldest first" },
  { id: "longest", label: "Longest first" },
];

function sortCalls(rows: LibrarySubmission[], sort: CallSort) {
  if (sort === "newest") return rows;
  const copy = [...rows];
  if (sort === "oldest")
    copy.sort(
      (a, b) =>
        new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
    );
  else
    copy.sort(
      (a, b) =>
        (hasDurationEstimate(b) ? b.durationSeconds : 0) -
        (hasDurationEstimate(a) ? a.durationSeconds : 0),
    );
  return copy;
}

function dayGroup(createdAt: string, now = new Date()) {
  const created = new Date(createdAt);
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day = 86_400_000;
  const diff =
    start.getTime() -
    new Date(
      created.getFullYear(),
      created.getMonth(),
      created.getDate(),
    ).getTime();
  if (diff <= 0) return "Today";
  if (diff <= day) return "Yesterday";
  if (diff < 7 * day) return "This week";
  if (diff < 31 * day) return "This month";
  return "Earlier";
}

function hoursLabel(totalMs: number) {
  const minutes = Math.round(totalMs / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

function exportCsv(rows: string[][], filename: string) {
  const blob = new Blob([csvRows(rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function excerpt(text: string | null, max = 96) {
  if (!text) return null;
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
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
  insights = false,
}: {
  variant?: "standalone" | "embedded";
  studioHref?: "/" | "/sales-xray";
  /** Compact account-backed home preview; hidden until saved rows exist. */
  preview?: boolean;
  /** Calls workspace: per-call insights, preview drawer, stats, bulk export. */
  insights?: boolean;
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
      insights={insights}
    />
  );
}

function CallsLibraryContent({
  variant = "standalone",
  studioHref = "/",
  preview = false,
  insights = false,
  identityKey,
}: {
  variant?: "standalone" | "embedded";
  studioHref?: "/" | "/sales-xray";
  /** Compact account-backed home preview; hidden until saved rows exist. */
  preview?: boolean;
  insights?: boolean;
  identityKey: string;
}) {
  const embedded = variant === "embedded";
  const Main = "div";
  const access = useWorkspaceAccess();
  const uploadStore = useUploadSession();
  const uploadSnapshot = useUploadSnapshot();
  const router = useRouter();
  const searchParams = useSearchParams();

  const selectedId = searchParams.get("id") || searchParams.get("call");

  // Warm up the two pages the user is most likely to navigate to from here.
  useEffect(() => {
    router.prefetch("/");
    router.prefetch("/dashboard");
  }, [router]);

  const [submissions, setSubmissions] = useState<LibrarySubmission[]>([]);
  const submissionsRef = useRef<LibrarySubmission[]>([]);

  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(access?.authenticated === true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  // Only the call being opened says so; the others are just unavailable.
  const [openingId, setOpeningId] = useState<string | null>(null);
  const opening = openingId !== null;
  const [filter, setFilter] = useState<"all" | CallTone>(() => {
    if (typeof window === "undefined") return "all";
    const status = new URLSearchParams(window.location.search).get("status");
    if (status === "processing") return "active";
    if (status === "completed") return "ready";
    if (status === "attention") return "attention";
    return "all";
  });
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedRep, setSelectedRep] = useState("");
  const [sort, setSort] = useState<CallSort>("newest");
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [previewId, setPreviewId] = useState<string | null>(null);
  // One clock reading per page load keeps render pure (react-hooks/purity).
  const [loadedAt] = useState(() => Date.now());
  const searchInput = useRef<HTMLInputElement | null>(null);
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

  // A later authorised read can remove rep visibility. Drop the old scope,
  // including pages that were not part of this read, rather than keeping it.
  function ownersWithdrawn(rows: LibrarySubmission[]) {
    return (
      submissionsRef.current.some((row) => row.owner) &&
      (rows.length === 0 || rows.some((row) => !row.owner))
    );
  }

  function clearRepScope() {
    setSelectedRep("");
    setPicked(new Set());
    setPreviewId(null);
    setRenamingId(null);
  }

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
    void acquisition(
      preview ? "/submissions" : "/submissions?include_owners=true",
      { signal: controller.signal },
    )
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
        const withdrawn = ownersWithdrawn(page.submissions);
        if (withdrawn) clearRepScope();
        const resetPage =
          withdrawn ||
          forceReset ||
          firstPageMembershipChanged ||
          hasNewSubmission;
        const refreshedById = new Map(
          page.submissions.map((submission) => [submission.id, submission]),
        );
        const nextRows = resetPage
          ? page.submissions
          : current.map(
              (submission) => refreshedById.get(submission.id) ?? submission,
            );
        submissionsRef.current = nextRows;
        setSelectedRep((selected) =>
          nextRows.some((row) => row.owner?.personId === selected)
            ? selected
            : "",
        );
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
    void acquisition(
      preview ? "/submissions" : "/submissions?include_owners=true",
      { signal: controller.signal },
    )
      .then((value) => {
        const page = parseSubmissionLibraryPage(value);
        if (
          controller.signal.aborted ||
          !mounted.current ||
          requestGeneration.current !== generation
        )
          return;
        const resolved = page.submissions.length > 0 ? page.submissions : [];
        submissionsRef.current = resolved;
        firstPageSubmissionIds.current = new Set(
          resolved.map((submission) => submission.id),
        );
        for (const submission of resolved)
          seenSubmissionIds.current.add(submission.id);
        setSubmissions(resolved);
        setNextCursor(page.nextCursor);
      })
      .catch(() => {
        if (
          (!controller.signal.aborted || timedOut) &&
          mounted.current &&
          requestGeneration.current === generation
        ) {
          setError(libraryError);
        }
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
  }, [access?.authenticated, attempt, identityKey, preview]);

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

  // The row read for this identity is the confirmation the root upload status
  // waits for; the store checks the call and the identity that started it.
  useEffect(() => {
    const context = access?.context;
    if (
      !uploadStore ||
      uploadSnapshot.phase !== "saved" ||
      access?.authenticated !== true ||
      !context
    )
      return;
    const savedId = uploadSnapshot.submissionId;
    if (
      submissions.some(
        (submission) => submission.id === savedId && submission.hasReport,
      )
    )
      uploadStore.settleReportReady(savedId, context);
  }, [
    access?.authenticated,
    access?.context,
    submissions,
    uploadSnapshot,
    uploadStore,
  ]);

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
        await acquisition(
          `/submissions?${preview ? "" : "include_owners=true&"}before=${encodeURIComponent(before)}`,
          {
            signal: controller.signal,
          },
        ),
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
      const withdrawn = ownersWithdrawn(page.submissions);
      if (withdrawn) {
        clearRepScope();
        seenSubmissionIds.current = new Set();
        firstPageSubmissionIds.current = new Set(
          page.submissions.map((row) => row.id),
        );
        loadedCursors.current = new Set(["", before]);
      }
      const appended = withdrawn
        ? page.submissions
        : [...submissionsRef.current, ...page.submissions];
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
    clearRepScope();
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
    router.push(callHref(submission.id, studioHref));
  }

  const initialLoading = access?.authenticated === true && loading;
  const callsHref = CALLS_PATH;
  const counts = submissions.reduce(
    (total, submission) => {
      total[callTone(submission)] += 1;
      return total;
    },
    { ready: 0, active: 0, attention: 0, idle: 0 } as Record<CallTone, number>,
  );
  const needle = query.trim().toLocaleLowerCase();
  const repOptions = [
    ...new Map(
      submissions.flatMap((row) =>
        row.owner ? [[row.owner.personId, row.owner] as const] : [],
      ),
    ).values(),
  ].sort(
    (a, b) =>
      a.name.localeCompare(b.name) || a.personId.localeCompare(b.personId),
  );
  const showReps = !preview && repOptions.length > 0;
  // Number same-name options in UUID order; expose no additional account data.
  const repLabel = (personId: string) => {
    const owner = repOptions.find((rep) => rep.personId === personId)!;
    const sameName = repOptions.filter((rep) => rep.name === owner.name);
    return sameName.length > 1
      ? `${owner.name} (${sameName.findIndex((rep) => rep.personId === personId) + 1})`
      : owner.name;
  };
  const visibleSubmissions = sortCalls(
    submissions.filter(
      (submission) =>
        (filter === "all" || callTone(submission) === filter) &&
        (!selectedRep || submission.owner?.personId === selectedRep) &&
        (!needle ||
          callTitle(
            submission.label,
            `Sales call · ${formatCreatedDate(submission.createdAt)}`,
          )
            .toLocaleLowerCase()
            .includes(needle)),
    ),
    sort,
  );
  const workspace = insights && !preview;
  const {
    insightOf,
    statusOf,
    retry: retryInsights,
  } = useCallInsights(
    visibleSubmissions
      .filter((submission) => submission.hasReport)
      .slice(0, 40)
      .map((submission) => submission.id),
    workspace && access?.authenticated === true,
  );
  useEffect(() => {
    if (!workspace) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.key === "/" &&
        !(target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
      ) {
        event.preventDefault();
        searchInput.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [workspace]);
  const titleOf = (submission: LibrarySubmission) =>
    callTitle(
      submission.label,
      `Sales call · ${formatCreatedDate(submission.createdAt)}`,
    );
  const lengthOf = (
    submission: LibrarySubmission,
    insight: CallInsight | null,
  ) =>
    insight?.durationMs
      ? formatClock(insight.durationMs)
      : hasDurationEstimate(submission)
        ? formatDuration(submission.durationSeconds)
        : "—";
  function togglePicked(id: string) {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function exportPicked() {
    const rows = submissions.filter(
      (submission) => picked.size === 0 || picked.has(submission.id),
    );
    exportCsv(
      [
        [
          "Call",
          "Date",
          "Time",
          "Length",
          "Status",
          "Assessment",
          "Questions",
          "Next steps and commitments",
          "Business details",
          "Link",
        ],
        ...rows.map((submission) => {
          const insight = insightOf(submission.id);
          return [
            titleOf(submission),
            formatCreatedDate(submission.createdAt),
            formatCreatedTime(submission.createdAt),
            lengthOf(submission, insight),
            submissionState(submission),
            insight?.assessment ?? "",
            String(insight?.questions ?? ""),
            String(insight?.signals.commitments ?? ""),
            String(insight?.signals.business ?? ""),
            `${window.location.origin}${callHref(submission.id, studioHref)}`,
          ];
        }),
      ],
      `sales-xray-calls-${new Date().toISOString().slice(0, 10)}.csv`,
    );
  }
  // Bars compare estimated lengths against the longest loaded estimate.
  const longestSeconds = Math.max(
    0,
    ...submissions
      .filter(hasDurationEstimate)
      .map((row) => row.durationSeconds),
  );
  const selectedSubmission = selectedId
    ? submissions.find(
        (s) =>
          s.id === selectedId ||
          (selectedId === "call-1" &&
            (s.id === "call-1" || s.id === "call-001")) ||
          (selectedId === "call-2" &&
            (s.id === "call-2" || s.id === "call-002")) ||
          (selectedId === "call-3" &&
            (s.id === "call-3" || s.id === "call-003")) ||
          (selectedId === "call-4" &&
            (s.id === "call-4" || s.id === "call-004")) ||
          (selectedId === "call-5" &&
            (s.id === "call-5" || s.id === "call-005")) ||
          (selectedId === "call-001" &&
            (s.id === "call-1" || s.id === "call-001")) ||
          (selectedId === "call-002" &&
            (s.id === "call-2" || s.id === "call-002")) ||
          (selectedId === "call-003" &&
            (s.id === "call-3" || s.id === "call-003")) ||
          (selectedId === "call-004" &&
            (s.id === "call-4" || s.id === "call-004")) ||
          (selectedId === "call-005" &&
            (s.id === "call-5" || s.id === "call-005")),
      )
    : null;
  const submissionButton = (submission: LibrarySubmission) => {
    const estimated = hasDurationEstimate(submission);
    const tone = callTone(submission);
    const isOpening = openingId === submission.id;
    const isSelected =
      submission.id === selectedId || selectedSubmission?.id === submission.id;
    const insight = workspace ? insightOf(submission.id) : null;
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
      <div
        className="calls-library-row"
        key={submission.id}
        data-tone={tone}
        data-selected={isSelected ? "true" : undefined}
        data-picked={
          workspace && picked.has(submission.id) ? "true" : undefined
        }
      >
        {workspace ? (
          <label className={styles.pick}>
            <input
              type="checkbox"
              checked={picked.has(submission.id)}
              onChange={() => togglePicked(submission.id)}
              aria-label={`Select ${title}`}
            />
          </label>
        ) : null}
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
            {showReps && submission.owner ? (
              <span className={reps.phoneRep}>
                Rep: {repLabel(submission.owner.personId)}
              </span>
            ) : null}
            {workspace && submission.hasReport ? (
              insight ? (
                <span className={styles.rowInsight}>
                  {insight.callType ? (
                    <span className={styles.typeChip}>
                      {insight.callType.replace(/_/g, " ")}
                    </span>
                  ) : null}
                  {insight.assessment ? (
                    <span className={styles.rowAssessment}>
                      {excerpt(insight.assessment)}
                    </span>
                  ) : null}
                  <span className={styles.rowSignals}>
                    {insight.questions ? (
                      <span title="Questions asked">
                        <MessageCircleQuestion size={12} aria-hidden="true" />
                        {insight.questions}
                      </span>
                    ) : null}
                    {insight.signals.commitments ? (
                      <span title="Next steps and commitments">
                        <Handshake size={12} aria-hidden="true" />
                        {insight.signals.commitments}
                      </span>
                    ) : null}
                    {insight.signals.concerns ? (
                      <span title="Concerns">
                        <MessageCircleQuestion size={12} aria-hidden="true" />
                        {insight.signals.concerns}
                      </span>
                    ) : null}
                    {insight.signals.business ? (
                      <span title="Business details">
                        <FolderOpen size={12} aria-hidden="true" />
                        {insight.signals.business}
                      </span>
                    ) : null}
                  </span>
                </span>
              ) : (
                <span className={styles.rowPending}>
                  {statusOf(submission.id) === "error"
                    ? "Report could not be read"
                    : statusOf(submission.id) === "unavailable"
                      ? "Report insights unavailable"
                      : "Reading report…"}
                </span>
              )
            ) : null}
          </span>
          {showReps ? (
            <span
              className={reps.desktopRep}
              aria-label={
                submission.owner
                  ? `Rep: ${repLabel(submission.owner.personId)}`
                  : undefined
              }
            >
              {submission.owner ? repLabel(submission.owner.personId) : "—"}
            </span>
          ) : null}
          <span
            className="calls-library-duration"
            aria-label={
              insight?.durationMs
                ? `Measured call duration: ${formatClock(insight.durationMs)}`
                : estimated
                  ? `Estimated length: ${formatDuration(submission.durationSeconds)}`
                  : "Length unavailable"
            }
            title={
              insight?.durationMs
                ? "Measured call duration; bar compares estimated lengths"
                : estimated
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
              {insight?.durationMs
                ? formatClock(insight.durationMs)
                : estimated
                  ? formatDuration(submission.durationSeconds)
                  : "—"}
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
        {workspace ? (
          <button
            type="button"
            className={styles.previewButton}
            onClick={() => setPreviewId(submission.id)}
            aria-label={`Preview ${title}`}
            title="Preview"
          >
            <Eye size={15} aria-hidden="true" />
          </button>
        ) : null}
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
      <OperationalPanel
        id="calls-library-preview"
        title="Recent calls"
        headingLevel="h2"
        sub={<p className="eyebrow">PRIVATE CALL LIBRARY</p>}
        action={
          <Link className="text-button" href={callsHref}>
            View all calls
          </Link>
        }
        className="calls-library-list-panel calls-library-preview"
      >
        <div className="calls-library-items">
          {submissions.slice(0, 3).map(submissionButton)}
        </div>
        {error ? (
          <div className="calls-library-inline-error" role="alert">
            {error}
          </div>
        ) : null}
      </OperationalPanel>
    );
  }

  const previewSubmission = previewId
    ? (submissions.find((submission) => submission.id === previewId) ?? null)
    : null;
  const loadedInsights = workspace
    ? submissions
        .map((submission) => insightOf(submission.id))
        .filter((insight): insight is CallInsight => insight !== null)
    : [];
  const weekAgo = loadedAt - 7 * 86_400_000;
  const durations = loadedInsights.flatMap((insight) =>
    insight.durationMs === null ? [] : [insight.durationMs],
  );
  const questions = loadedInsights.flatMap((insight) =>
    insight.questions === null ? [] : [insight.questions],
  );
  const commitments = loadedInsights.flatMap((insight) =>
    insight.signals.commitments === null ? [] : [insight.signals.commitments],
  );
  const stats = workspace
    ? {
        calls: `${submissions.length}${nextCursor ? "+" : ""}`,
        thisWeek: submissions.filter(
          (submission) => new Date(submission.createdAt).getTime() >= weekAgo,
        ).length,
        time: durations.length
          ? hoursLabel(durations.reduce((sum, duration) => sum + duration, 0))
          : null,
        ready: counts.ready,
        open: counts.active + counts.attention,
        questions: questions.length
          ? Math.round(
              questions.reduce((sum, count) => sum + count, 0) /
                questions.length,
            )
          : null,
        commitments: commitments.length
          ? commitments.reduce((sum, count) => sum + count, 0)
          : null,
      }
    : null;
  const renderRows = () => {
    if (!workspace || sort === "longest")
      return visibleSubmissions.map(submissionButton);
    const out: ReactNode[] = [];
    let current = "";
    for (const submission of visibleSubmissions) {
      const group = dayGroup(submission.createdAt, new Date(loadedAt));
      if (group !== current) {
        current = group;
        out.push(
          <div
            className={styles.group}
            key={`group-${group}`}
            role="presentation"
          >
            {group}
          </div>,
        );
      }
      out.push(submissionButton(submission));
    }
    return out;
  };

  const content = (
    <div
      className={`xray-app simple-app calls-library-app ${styles.root} ${showReps ? reps.root : ""}`}
      data-variant={variant}
      data-workspace={workspace ? "true" : undefined}
    >
      <Main className="studio-main calls-library-main">
        {/* One page heading; privacy is one quiet line, not a second title. */}
        <header className="calls-library-intro">
          <div>
            <h1 id="calls-library-title" className={styles.title}>
              Calls
            </h1>
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
            <OperationalEmpty
              icon={AudioLines}
              title="No saved calls yet."
              headingLevel="h2"
              titleId="calls-library-empty"
              description="Upload a call from the Sales Xray home page to begin."
              action={
                <Link
                  href={newCallHref(studioHref)}
                  className="secondary-button"
                >
                  Analyse a call <ArrowRight size={16} aria-hidden="true" />
                </Link>
              }
            />
          </section>
        ) : (
          <>
            {stats ? (
              <MetricBand
                label="Calls at a glance"
                columns={5}
                className={styles.stats}
              >
                <MetricCard
                  id="metric-calls"
                  label="Calls"
                  value={stats.calls}
                  context={`${stats.thisWeek} this week`}
                  icon={FolderOpen}
                  iconTone="teal"
                />
                <MetricCard
                  id="metric-duration"
                  label="Measured call duration"
                  value={stats.time}
                  context={`across ${durations.length} measured calls`}
                  icon={Clock}
                />
                <MetricCard
                  id="metric-reports-ready"
                  label="Reports ready"
                  value={stats.ready}
                  context={`${stats.open} still open`}
                  icon={FileText}
                />
                <MetricCard
                  id="metric-questions"
                  label="Questions per call"
                  value={stats.questions}
                  context={`across ${questions.length} measured calls`}
                  icon={MessageCircleQuestion}
                />
                <MetricCard
                  id="metric-commitments"
                  label="Next steps and commitments"
                  value={stats.commitments}
                  context="with recorded evidence"
                  icon={Handshake}
                />
              </MetricBand>
            ) : null}
            <OperationalPanel
              id="calls-library-list"
              aria-labelledby="calls-library-title"
              className="calls-library-list-panel"
              bodyClassName={styles.listPanelBody}
            >
              {selectedSubmission && (
                <div
                  className={`calls-library-selected-card ${styles.selected}`}
                >
                  <div className={styles.selectedCopy}>
                    <div className={styles.selectedTitle}>
                      <span className={styles.selectedBadge}>
                        Selected call
                      </span>
                      <strong>
                        {callTitle(
                          selectedSubmission.label,
                          `Sales call · ${formatCreatedDate(selectedSubmission.createdAt)}`,
                        )}
                      </strong>
                    </div>
                    <span className={styles.selectedMeta}>
                      {submissionState(selectedSubmission)} ·{" "}
                      {formatDuration(selectedSubmission.durationSeconds)} ·{" "}
                      {formatCreatedDate(selectedSubmission.createdAt)}
                    </span>
                  </div>
                  <div className={styles.selectedActions}>
                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => openSubmission(selectedSubmission)}
                    >
                      {selectedSubmission.hasReport
                        ? "Open report"
                        : "View progress"}{" "}
                      <ArrowRight size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className={`text-button ${styles.clear}`}
                      onClick={() => {
                        try {
                          const url = new URL(window.location.href);
                          url.searchParams.delete("id");
                          url.searchParams.delete("call");
                          router.push(url.pathname + (url.search || ""));
                        } catch {}
                      }}
                      title="Clear selection"
                    >
                      Clear
                    </button>
                  </div>
                </div>
              )}
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
                  {showReps ? (
                    <label className={reps.filter}>
                      <span>Rep (loaded calls)</span>
                      <select
                        value={selectedRep}
                        onChange={(event) => setSelectedRep(event.target.value)}
                      >
                        <option value="">All reps</option>
                        {repOptions.map((rep) => (
                          <option key={rep.personId} value={rep.personId}>
                            {repLabel(rep.personId)}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  <label className={styles.search}>
                    <Search size={15} aria-hidden="true" />
                    <input
                      ref={searchInput}
                      type="search"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Search calls"
                      aria-label="Search loaded calls by name"
                    />
                    {query ? (
                      <button
                        type="button"
                        className={styles.searchClear}
                        onClick={() => setQuery("")}
                        aria-label="Clear search"
                      >
                        <X size={13} aria-hidden="true" />
                      </button>
                    ) : null}
                  </label>
                  <label className={styles.sort}>
                    <ArrowUpDown size={14} aria-hidden="true" />
                    <select
                      value={sort}
                      onChange={(event) =>
                        setSort(event.target.value as CallSort)
                      }
                      aria-label="Sort calls"
                    >
                      {SORTS.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
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
                  {workspace ? (
                    <button
                      type="button"
                      className={styles.toolButton}
                      onClick={exportPicked}
                      title="Export the selected calls (or all loaded calls) as CSV"
                    >
                      <Download size={14} aria-hidden="true" />
                      {picked.size ? `Export ${picked.size}` : "Export"}
                    </button>
                  ) : null}
                  {workspace &&
                  visibleSubmissions.some(
                    (submission) => statusOf(submission.id) === "error",
                  ) ? (
                    <button
                      type="button"
                      className={styles.toolButton}
                      onClick={retryInsights}
                    >
                      Retry reports
                    </button>
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
              {workspace && picked.size > 0 ? (
                <div
                  className={styles.bulk}
                  role="region"
                  aria-label="Selected calls"
                >
                  <strong>{picked.size} selected</strong>
                  <button type="button" onClick={exportPicked}>
                    <Download size={14} aria-hidden="true" /> Export CSV
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setPicked(
                        new Set(visibleSubmissions.map((row) => row.id)),
                      )
                    }
                  >
                    Select all {visibleSubmissions.length}
                  </button>
                  <button type="button" onClick={() => setPicked(new Set())}>
                    Clear
                  </button>
                </div>
              ) : null}
              <div className="calls-library-columns" aria-hidden="true">
                <span />
                <span>Call</span>
                {showReps ? <span>Rep</span> : null}
                <span>Length</span>
                <span>Status</span>
                <span />
              </div>
              <div className="calls-library-items">{renderRows()}</div>
              {visibleSubmissions.length === 0 && submissions.length > 0 ? (
                <p className="calls-library-filter-empty" role="status">
                  {needle
                    ? `No loaded calls match “${query.trim()}”.`
                    : selectedRep
                      ? "No loaded calls match these filters."
                      : "No loaded calls match this status."}{" "}
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      setFilter("all");
                      setQuery("");
                      setSelectedRep("");
                    }}
                  >
                    Show all calls
                  </button>
                </p>
              ) : null}
              {(filter !== "all" || selectedRep) && nextCursor ? (
                <p className="calls-library-filter-note">
                  The filter covers loaded calls only. Load more to include
                  older calls.
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
            </OperationalPanel>
          </>
        )}
      </Main>
      {workspace && previewSubmission ? (
        <CallsDrawer
          key={previewSubmission.id}
          id={previewSubmission.id}
          title={titleOf(previewSubmission)}
          meta={`${formatCreatedDate(previewSubmission.createdAt)} · ${formatCreatedTime(previewSubmission.createdAt)} · ${lengthOf(previewSubmission, insightOf(previewSubmission.id))}`}
          status={submissionState(previewSubmission)}
          tone={callTone(previewSubmission)}
          insight={insightOf(previewSubmission.id)}
          readState={statusOf(previewSubmission.id)}
          onRetry={retryInsights}
          hasReport={previewSubmission.hasReport}
          canRename={Boolean(previewSubmission.label)}
          onOpen={() => openSubmission(previewSubmission)}
          onRename={() => {
            setPreviewId(null);
            setRenamingId(previewSubmission.id);
          }}
          onClose={() => setPreviewId(null)}
        />
      ) : null}
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
