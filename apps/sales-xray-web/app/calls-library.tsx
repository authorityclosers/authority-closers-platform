"use client";

import { CALLS_PATH } from "./analysis-routes";
import { callHref } from "./acquisition-client";
import {
  callDate,
  callTone,
  submissionState,
  type CallTone,
} from "./call-status";
import {
  AlertCircle,
  ArrowRight,
  ArrowUpDown,
  AudioLines,
  ChevronRight,
  Download,
  Eye,
  FolderOpen,
  LoaderCircle,
  RefreshCw,
  Search,
  Users,
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
import { callTitle, unnamedCallName, type CallLabel } from "./call-label";
import {
  CALL_LABEL_EVENT,
  readCallLabel,
  renameCall,
  type CallLabelChange,
} from "./call-label-client";
import { ownsCall, requestWorkspace } from "./call-ownership";
import { CallLabelEditor, RenameCallButton } from "./call-label-editor";
import styles from "./calls-library.module.css";
import { CallsDrawer } from "./calls-drawer";
import { useCallInsights, type CallInsight } from "./calls-insights";
import { csvRows } from "./csv-export";
import { OperationalPanel } from "./ui/operational-panel";

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

/** The phone meta line's short status; the full wording is in the drawer. */
function shortState(submission: LibrarySubmission) {
  const tone = callTone(submission);
  if (tone === "ready") return "Ready";
  if (tone === "active")
    return submission.state === "queued" ? "Queued" : "Analysing";
  if (tone === "attention")
    return submission.state === "held" ? "Paused" : "Needs attention";
  return submissionState(submission);
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
  // The sidebar search opens Calls with ?q=; a new one replaces the box.
  const urlQuery = searchParams.get("q") ?? "";
  const [query, setQuery] = useState(urlQuery);
  const [appliedUrlQuery, setAppliedUrlQuery] = useState(urlQuery);
  if (urlQuery !== appliedUrlQuery) {
    setAppliedUrlQuery(urlQuery);
    setQuery(urlQuery);
  }
  const [selectedRep, setSelectedRep] = useState("");
  const [sort, setSort] = useState<CallSort>("newest");
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [previewId, setPreviewId] = useState<string | null>(null);
  // Phones show row checkboxes only in Select mode; desktops always do.
  const [selecting, setSelecting] = useState(false);
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

  // A rename anywhere else (sidebar, report header) shows here at once.
  useEffect(() => {
    const onLabel = (event: Event) => {
      const { submissionId, label } = (event as CustomEvent<CallLabelChange>)
        .detail;
      const row = submissionsRef.current.find(
        (item) => item.id === submissionId,
      );
      if (!row || (row.label && row.label.revision >= label.revision)) return;
      const next = submissionsRef.current.map((item) =>
        item.id === submissionId ? { ...item, label } : item,
      );
      submissionsRef.current = next;
      setSubmissions(next);
    };
    window.addEventListener(CALL_LABEL_EVENT, onLabel);
    return () => window.removeEventListener(CALL_LABEL_EVENT, onLabel);
  }, []);

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
  const viewerId = access?.context?.personId ?? null;
  const callers = new Set(
    submissions.map((row) => row.owner?.personId ?? viewerId),
  ).size;
  // Number same-name options in UUID order; expose no additional account data.
  const repLabel = (personId: string) => {
    if (personId === viewerId) return "You";
    const owner = repOptions.find((rep) => rep.personId === personId)!;
    // The viewer reads as "You", so only teammates share a numbered name.
    const sameName = repOptions.filter(
      (rep) => rep.name === owner.name && rep.personId !== viewerId,
    );
    return sameName.length > 1
      ? `${owner.name} (${sameName.findIndex((rep) => rep.personId === personId) + 1})`
      : owner.name;
  };
  // An owner or admin sees the team's calls here. When none are theirs, say
  // where their own work lives (the whole list is loaded, so this is certain).
  const currentWorkspace = access?.workspaces?.find(
    (item) => item.tenant_id === access?.context?.tenantId,
  );
  const personalWorkspace = access?.workspaces?.find(
    (item) => item.kind === "personal" && item.sales_xray_enabled,
  );
  const elsewhere =
    showReps &&
    !nextCursor &&
    currentWorkspace?.kind === "organisation" &&
    personalWorkspace &&
    submissions.length > 0 &&
    !submissions.some((row) => ownsCall(row.owner, viewerId))
      ? { tenant_id: personalWorkspace.tenant_id, name: "Personal" }
      : null;
  const visibleSubmissions = sortCalls(
    submissions.filter(
      (submission) =>
        (filter === "all" || callTone(submission) === filter) &&
        (!selectedRep || submission.owner?.personId === selectedRep) &&
        (!needle ||
          callTitle(submission.label, unnamedCallName(submission.createdAt))
            .toLocaleLowerCase()
            .includes(needle)),
    ),
    sort,
  );
  const workspace = insights && !preview;
  // Summaries for the first screens of ready rows only, not one per call.
  const insightIds = visibleSubmissions
    .filter((submission) => submission.hasReport)
    .slice(0, 24)
    .map((submission) => submission.id);
  const {
    insightOf,
    statusOf,
    retry: retryInsights,
  } = useCallInsights(insightIds, workspace && access?.authenticated === true);
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
    callTitle(submission.label, unnamedCallName(submission.createdAt));
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
  /* Home preview row (New analysis page): the legacy compact row, unchanged. */
  const previewRow = (submission: LibrarySubmission) => {
    const estimated = hasDurationEstimate(submission);
    const tone = callTone(submission);
    const isOpening = openingId === submission.id;
    const isSelected =
      submission.id === selectedId || selectedSubmission?.id === submission.id;
    return (
      <div
        className="calls-library-row"
        key={submission.id}
        data-tone={tone}
        data-selected={isSelected ? "true" : undefined}
      >
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
            <strong>{titleOf(submission)}</strong>
            <small>
              {submission.label?.displayName
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
          {submissions.slice(0, 3).map(previewRow)}
        </div>
        {error ? (
          <div className="calls-library-inline-error" role="alert">
            {error}
          </div>
        ) : null}
      </OperationalPanel>
    );
  }

  const now = new Date(loadedAt);
  const grouped = workspace && sort !== "longest";
  /** Measured length when the report has it; otherwise the upload estimate. */
  const lengthCell = (
    submission: LibrarySubmission,
    insight: CallInsight | null,
  ) =>
    insight?.durationMs
      ? {
          text: formatClock(insight.durationMs),
          label: `Measured call duration: ${formatClock(insight.durationMs)}`,
          title: "Measured from the recording",
        }
      : hasDurationEstimate(submission)
        ? {
            text: `~${formatClock(submission.durationSeconds * 1000)}`,
            label: `Estimated length: ${formatDuration(submission.durationSeconds)}`,
            title: "Estimated at upload; the report measures it",
          }
        : { text: "", label: "Length unavailable", title: undefined };

  const callRow = (submission: LibrarySubmission) => {
    const tone = callTone(submission);
    const isOpening = openingId === submission.id;
    const isSelected =
      submission.id === selectedId || selectedSubmission?.id === submission.id;
    const insight = workspace ? insightOf(submission.id) : null;
    const read =
      workspace && submission.hasReport ? statusOf(submission.id) : null;
    const title = titleOf(submission);
    const label = submission.label;
    const length = lengthCell(submission, insight);
    const rep =
      showReps && submission.owner ? repLabel(submission.owner.personId) : null;
    const day = callDate(submission.createdAt, now);
    // Under a Today or Yesterday heading the time says more than the day.
    const when =
      grouped && (day === "Today" || day === "Yesterday")
        ? formatCreatedTime(submission.createdAt)
        : day;
    const fullDate = `${formatCreatedDate(submission.createdAt)}, ${formatCreatedTime(submission.createdAt)}`;
    // Rename needs a server that supplies labels, and only the owner may.
    const mine = ownsCall(submission.owner, viewerId);
    if (renamingId === submission.id && label && mine)
      return (
        <div
          className={`${styles.row} calls-library-row`}
          key={submission.id}
          data-renaming="true"
        >
          <div className={`${styles.rename} calls-library-rename`}>
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
        className={`${styles.row} calls-library-row`}
        key={submission.id}
        data-tone={tone}
        data-selected={isSelected ? "true" : undefined}
        data-picked={picked.has(submission.id) ? "true" : undefined}
      >
        <span className={styles.pick}>
          {workspace ? (
            <input
              type="checkbox"
              checked={picked.has(submission.id)}
              onChange={() => togglePicked(submission.id)}
              aria-label={`Select ${title}`}
            />
          ) : null}
        </span>
        <button
          className={`${styles.item} calls-library-item`}
          data-submission-id={submission.id}
          data-tone={tone}
          type="button"
          disabled={opening}
          aria-busy={isOpening || undefined}
          onClick={() => openSubmission(submission)}
        >
          <span className={`${styles.copy} calls-library-copy`}>
            <strong data-unnamed={label?.displayName ? undefined : "true"}>
              {title}
            </strong>
            {/* Phone: one quiet line carries what the desktop columns show. */}
            <small className={styles.meta}>
              <span className={styles.metaStatus} data-tone={tone}>
                <i aria-hidden="true" />
                {shortState(submission)}
              </span>
              <span>{when}</span>
              {length.text ? <span>{length.text}</span> : null}
              {rep ? <span>{rep}</span> : null}
            </small>
            {read ? (
              <span className={styles.snippet}>
                {insight ? (
                  <>
                    {insight.callType ? (
                      <span className={styles.type}>
                        {insight.callType.replace(/_/g, " ")}
                      </span>
                    ) : null}
                    {insight.assessment ? (
                      <span className={styles.assessment}>
                        {excerpt(insight.assessment, 160)}
                      </span>
                    ) : null}
                  </>
                ) : read === "error" ? (
                  <span className={styles.snippetQuiet}>
                    Summary didn&apos;t load
                  </span>
                ) : read === "loading" ? (
                  <span className={styles.snippetSkeleton} aria-hidden="true" />
                ) : null}
              </span>
            ) : null}
          </span>
          {showReps ? (
            <span
              className={styles.rep}
              aria-label={rep ? `Rep: ${rep}` : "Rep not shown"}
            >
              {rep ? (
                <>
                  <i aria-hidden="true">{initials(rep)}</i>
                  <span aria-hidden="true">{rep}</span>
                </>
              ) : null}
            </span>
          ) : null}
          <span className={styles.date} title={fullDate}>
            {when}
          </span>
          <span
            className={`${styles.length} calls-library-duration`}
            aria-label={length.label}
            title={length.title}
          >
            <span className="calls-library-duration-clock" aria-hidden="true">
              {length.text}
            </span>
          </span>
          <span
            className={`${styles.status} calls-library-state`}
            data-tone={tone}
          >
            <i aria-hidden="true" />
            {submissionState(submission)}
          </span>
          <span className={`${styles.open} calls-library-open`}>
            {isOpening ? (
              <>
                <LoaderCircle
                  className={styles.spin}
                  size={15}
                  aria-hidden="true"
                />
                <span className={styles.srOnly}>Opening…</span>
              </>
            ) : (
              <>
                <span className={styles.srOnly}>{openLabel(submission)}</span>
                <ChevronRight size={16} aria-hidden="true" />
              </>
            )}
          </span>
        </button>
        <span className={styles.actions}>
          {workspace ? (
            <button
              type="button"
              className={styles.iconButton}
              onClick={() => setPreviewId(submission.id)}
              aria-label={`Preview ${title}`}
              title="Preview"
            >
              <Eye size={15} aria-hidden="true" />
            </button>
          ) : null}
          {label && mine ? (
            <span className={styles.renameSlot}>
              <RenameCallButton
                callTitle={title}
                onClick={() => setRenamingId(submission.id)}
              />
            </span>
          ) : null}
        </span>
      </div>
    );
  };

  const previewSubmission = previewId
    ? (submissions.find((submission) => submission.id === previewId) ?? null)
    : null;
  const loadedInsights = workspace
    ? submissions
        .map((submission) => insightOf(submission.id))
        .filter((insight): insight is CallInsight => insight !== null)
    : [];
  const weekAgo = loadedAt - 7 * 86_400_000;
  // Call time: a measured length where a report gave one, otherwise the
  // estimate reserved at upload, never passed off as measured.
  const time = { measured: 0, measuredMs: 0, estimated: 0, estimatedMs: 0 };
  for (const submission of submissions) {
    const measuredMs = workspace ? insightOf(submission.id)?.durationMs : null;
    if (measuredMs) {
      time.measured += 1;
      time.measuredMs += measuredMs;
    } else if (hasDurationEstimate(submission)) {
      time.estimated += 1;
      time.estimatedMs += submission.durationSeconds * 1000;
    }
  }
  // How the reports read so far say calls ended (their own labels).
  const outcomes = loadedInsights.flatMap((insight) =>
    insight.outcome ? [insight.outcome] : [],
  );
  const readingReports = insightIds.some((id) => statusOf(id) === "loading");
  const nextSteps = outcomes.filter((kind) => kind === "follow_up").length;
  const closed = outcomes.filter((kind) => kind === "closed").length;
  // Calls per day over the last 14 days, from the same loaded rows.
  const days = Array.from({ length: 14 }, (_, index) => {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    start.setDate(start.getDate() - (13 - index));
    const end = start.getTime() + 86_400_000;
    return submissions.filter((submission) => {
      const at = new Date(submission.createdAt).getTime();
      return at >= start.getTime() && at < end;
    }).length;
  });
  const activeDays = days.filter((count) => count > 0).length;
  const busiestDay = Math.max(1, ...days);
  const stats = workspace
    ? {
        calls: `${submissions.length}${nextCursor ? "+" : ""}`,
        thisWeek: submissions.filter(
          (submission) => new Date(submission.createdAt).getTime() >= weekAgo,
        ).length,
        time:
          time.measured + time.estimated
            ? `${time.estimated ? "~" : ""}${hoursLabel(time.measuredMs + time.estimatedMs)}`
            : null,
      }
    : null;
  const waiting = [
    counts.active ? `${counts.active} in progress` : "",
    counts.attention
      ? `${counts.attention} ${counts.attention === 1 ? "needs" : "need"} attention`
      : "",
  ].filter(Boolean);
  const renderRows = () => {
    if (!grouped) return visibleSubmissions.map(callRow);
    const out: ReactNode[] = [];
    let current = "";
    for (const submission of visibleSubmissions) {
      const group = dayGroup(submission.createdAt, now);
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
      out.push(callRow(submission));
    }
    return out;
  };
  const insightErrors =
    workspace &&
    visibleSubmissions.some(
      (submission) => statusOf(submission.id) === "error",
    );

  const content = (
    <div
      className={styles.page}
      data-variant={variant}
      data-workspace={workspace ? "true" : undefined}
      data-reps={showReps ? "true" : undefined}
      data-selecting={selecting || picked.size > 0 ? "true" : undefined}
    >
      {/* One page heading; New analysis lives in the shell, not here too. */}
      <header className={styles.header}>
        <div className={styles.headerCopy}>
          <h1 id="calls-library-title">Calls</h1>
          <p className="calls-library-summary">
            {access?.authenticated === true && submissions.length > 0 ? (
              <>
                {`${submissions.length}${nextCursor ? "+" : ""} saved ${submissions.length === 1 && !nextCursor ? "call" : "calls"}`}
                <span className={styles.privacy}>
                  {" "}
                  {/* Owners and admins see the team's calls, not just theirs. */}
                  {showReps
                    ? `· from ${callers}${nextCursor ? "+" : ""} ${callers === 1 && !nextCursor ? "person" : "people"} in this workspace`
                    : "· private to your account and workspace"}
                </span>
              </>
            ) : (
              "Private to your account and workspace"
            )}
          </p>
        </div>
        <div className={styles.headerTools}>
          {insightErrors ? (
            <button
              type="button"
              className={styles.tool}
              onClick={retryInsights}
            >
              Retry reports
            </button>
          ) : null}
          {workspace && submissions.length > 0 ? (
            <button
              type="button"
              className={`${styles.tool} ${styles.export}`}
              onClick={exportPicked}
              title="Export the selected calls (or all loaded calls) as CSV"
            >
              <Download size={14} aria-hidden="true" />
              {picked.size ? `Export ${picked.size}` : "Export"}
            </button>
          ) : null}
          {access?.authenticated === true && !initialLoading ? (
            <button
              type="button"
              className={`${styles.refresh} calls-library-refresh`}
              onClick={() => {
                refreshHandler.current(identityKey, true);
              }}
              disabled={loading || refreshing || opening}
              title="Check for new calls and status changes"
            >
              <RefreshCw
                className={refreshing ? styles.spin : undefined}
                size={14}
                aria-hidden="true"
              />
              <span>{refreshing ? "Updating…" : "Refresh"}</span>
            </button>
          ) : null}
        </div>
      </header>

      {access?.authenticated === false ? (
        <section
          className={styles.empty}
          aria-labelledby="calls-library-sign-in"
        >
          <span className={styles.emptyIcon} aria-hidden="true">
            <FolderOpen size={20} />
          </span>
          <h2 id="calls-library-sign-in">Sign in to see your calls</h2>
          <p>Your calls and reports stay together in your account.</p>
          <Link href="/login" className={styles.primary}>
            Sign in <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </section>
      ) : error && submissions.length === 0 ? (
        <section className={`${styles.empty} calls-library-state`} role="alert">
          <span
            className={styles.emptyIcon}
            data-tone="attention"
            aria-hidden="true"
          >
            <AlertCircle size={20} />
          </span>
          <h2>Your calls didn&apos;t load</h2>
          <p>{error}</p>
          <button
            type="button"
            className={styles.secondary}
            onClick={retry}
            disabled={loading}
          >
            <RefreshCw size={14} aria-hidden="true" /> Try again
          </button>
        </section>
      ) : initialLoading && visibleSubmissions.length === 0 ? (
        <CallsBodySkeleton workspace={workspace} />
      ) : submissions.length === 0 && !nextCursor ? (
        <section className={styles.empty} aria-labelledby="calls-library-empty">
          <span className={styles.emptyIcon} aria-hidden="true">
            <AudioLines size={20} />
          </span>
          <h2 id="calls-library-empty">No calls yet</h2>
          <p>Upload a sales call recording to get its report here.</p>
          <Link href={newCallHref(studioHref)} className={styles.primary}>
            Analyse a call <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </section>
      ) : (
        <>
          {stats ? (
            <dl className={styles.strip} aria-label="Calls at a glance">
              <div className={styles.kpi} id="metric-calls">
                <dt>Calls</dt>
                <dd>
                  <b>{stats.calls}</b>
                  {activeDays >= 3 ? (
                    <span
                      className={styles.spark}
                      role="img"
                      aria-label={`Calls per day, last 14 days: ${days.join(", ")}`}
                    >
                      {days.map((count, index) => (
                        <i
                          key={index}
                          data-empty={count === 0 || undefined}
                          style={{
                            height: `${count === 0 ? 8 : 24 + (count / busiestDay) * 76}%`,
                          }}
                        />
                      ))}
                    </span>
                  ) : null}
                </dd>
                <dd className={styles.kpiContext}>
                  {stats.thisWeek} in the last 7 days
                </dd>
              </div>
              <div className={styles.kpi} id="metric-reports-ready">
                <dt>Reports ready</dt>
                <dd>
                  <b>{counts.ready}</b>
                </dd>
                <dd className={styles.kpiContext}>
                  {waiting.length
                    ? waiting.join(" · ")
                    : `of ${stats.calls} ${submissions.length === 1 && !nextCursor ? "call" : "calls"}`}
                </dd>
              </div>
              <div className={styles.kpi} id="metric-duration">
                <dt>Call time</dt>
                <dd>
                  {stats.time ? (
                    <b>{stats.time}</b>
                  ) : (
                    <span className={styles.unknown}>Not known yet</span>
                  )}
                </dd>
                <dd className={styles.kpiContext}>
                  {time.measured && time.estimated
                    ? `${time.measured} measured · ${time.estimated} estimated at upload`
                    : time.measured
                      ? `across ${time.measured} measured ${time.measured === 1 ? "call" : "calls"}`
                      : time.estimated
                        ? `estimated at upload, ${time.estimated} ${time.estimated === 1 ? "call" : "calls"}`
                        : "Shown once calls have a length"}
                </dd>
              </div>
              <div className={styles.kpi} id="metric-next-step">
                <dt>Next step agreed</dt>
                <dd>
                  {outcomes.length ? (
                    <b>{nextSteps}</b>
                  ) : (
                    <span className={styles.unknown}>
                      {readingReports
                        ? "Reading reports"
                        : insightErrors
                          ? "Not loaded"
                          : insightIds.length
                            ? "Not recorded"
                            : "No reports yet"}
                    </span>
                  )}
                </dd>
                <dd className={styles.kpiContext}>
                  {outcomes.length
                    ? `of ${outcomes.length} ${outcomes.length === 1 ? "report" : "reports"} read${closed ? ` · ${closed} closed` : ""}`
                    : insightIds.length
                      ? "How each report says the call ended"
                      : "Shown once a report is ready"}
                </dd>
              </div>
            </dl>
          ) : null}
          <section
            id="calls-library-list"
            aria-labelledby="calls-library-title"
            className={styles.list}
          >
            {selectedSubmission && (
              <div className={styles.selected}>
                <span className={styles.selectedTag}>Selected call</span>
                <div className={styles.selectedCopy}>
                  <strong>{titleOf(selectedSubmission)}</strong>
                  <span>
                    {submissionState(selectedSubmission)} ·{" "}
                    {formatCreatedDate(selectedSubmission.createdAt)}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.textButton}
                  onClick={() => openSubmission(selectedSubmission)}
                >
                  {selectedSubmission.hasReport
                    ? "Open report"
                    : "View progress"}{" "}
                  <ArrowRight size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className={styles.quietButton}
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
            )}
            <div className={styles.toolbar}>
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
                ) : workspace ? (
                  <kbd className={styles.kbd} aria-hidden="true">
                    /
                  </kbd>
                ) : null}
              </label>
              <div
                className={`${styles.filters} calls-library-filters`}
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
                      <span className={styles.chipCount}>{count}</span>
                    </button>
                  );
                })}
              </div>
              {showReps ? (
                <label className={styles.repFilter}>
                  <Users size={14} aria-hidden="true" />
                  <span className={styles.srOnly}>Rep (loaded calls)</span>
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
              <label className={styles.sort}>
                <ArrowUpDown size={14} aria-hidden="true" />
                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value as CallSort)}
                  aria-label="Sort calls"
                >
                  {SORTS.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              {workspace ? (
                <button
                  type="button"
                  className={`${styles.tool} ${styles.selectToggle}`}
                  aria-pressed={selecting || picked.size > 0}
                  onClick={() => {
                    if (selecting || picked.size > 0) {
                      setSelecting(false);
                      setPicked(new Set());
                    } else setSelecting(true);
                  }}
                >
                  {selecting || picked.size > 0 ? "Done" : "Select"}
                </button>
              ) : null}
            </div>
            {elsewhere ? (
              <p className={`${styles.elsewhere} calls-library-elsewhere`}>
                <span>
                  None of these calls are yours. Calls you saved in{" "}
                  {elsewhere.name} stay there.
                </span>
                <button
                  type="button"
                  className={styles.textButton}
                  onClick={() => requestWorkspace(elsewhere.tenant_id)}
                >
                  Switch to {elsewhere.name}
                </button>
              </p>
            ) : null}
            <div className={styles.table}>
              <div className={styles.head} aria-hidden="true">
                <span className={styles.pick} />
                <span className={styles.headCells}>
                  <span>Call</span>
                  {showReps ? <span>Rep</span> : null}
                  <span>Date</span>
                  <span className={styles.num}>Length</span>
                  <span>Status</span>
                  <span />
                </span>
                <span className={styles.actions} />
              </div>
              <div className={`${styles.rows} calls-library-items`}>
                {renderRows()}
              </div>
              {visibleSubmissions.length === 0 && submissions.length > 0 ? (
                <p
                  className={`${styles.note} calls-library-filter-empty`}
                  role="status"
                >
                  {needle
                    ? `No loaded calls match “${query.trim()}”.`
                    : selectedRep
                      ? "No loaded calls match these filters."
                      : "No loaded calls match this status."}{" "}
                  <button
                    type="button"
                    className={styles.textButton}
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
                <p className={`${styles.note} calls-library-filter-note`}>
                  The filter covers loaded calls only. Load more to include
                  older calls.
                </p>
              ) : null}
              {nextCursor ? (
                <button
                  type="button"
                  className={`${styles.more} calls-library-more`}
                  onClick={() => void loadMore()}
                  disabled={loading || refreshing || opening}
                >
                  {loading ? (
                    <>
                      <LoaderCircle
                        className={styles.spin}
                        size={14}
                        aria-hidden="true"
                      />{" "}
                      Loading…
                    </>
                  ) : (
                    "Load more calls"
                  )}
                </button>
              ) : null}
              {error ? (
                <div
                  className={`${styles.note} ${styles.problem} calls-library-inline-error`}
                  role="alert"
                >
                  <AlertCircle size={14} aria-hidden="true" />
                  <span>{error}</span>
                  {nextCursor ? (
                    <button
                      type="button"
                      className={styles.textButton}
                      onClick={() => void loadMore()}
                      disabled={loading || refreshing || opening}
                    >
                      Try again
                    </button>
                  ) : null}
                </div>
              ) : null}
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
                    setPicked(new Set(visibleSubmissions.map((row) => row.id)))
                  }
                >
                  Select all {visibleSubmissions.length}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPicked(new Set());
                    setSelecting(false);
                  }}
                >
                  Clear
                </button>
              </div>
            ) : null}
          </section>
        </>
      )}
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
          canRename={Boolean(
            previewSubmission.label &&
              ownsCall(previewSubmission.owner, viewerId),
          )}
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

function initials(name: string) {
  const words = name
    .replace(/\(\d+\)$/, "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return (
    words
      .slice(0, 2)
      .map((word) => word[0])
      .join("")
      .toLocaleUpperCase() || "?"
  );
}

/** The loaded page's own blocks in loading mode, so nothing moves. */
export function CallsBodySkeleton({
  workspace = true,
}: {
  workspace?: boolean;
}) {
  return (
    <div
      className={styles.skeleton}
      role="status"
      aria-busy="true"
      aria-label="Loading your calls"
    >
      {workspace ? (
        <div className={`${styles.strip} ${styles.skeletonStrip}`}>
          {[0, 1, 2, 3].map((tile) => (
            <div className={styles.kpi} key={tile}>
              <i data-w="label" />
              <i data-w="value" />
              <i data-w="context" />
            </div>
          ))}
        </div>
      ) : null}
      <div className={styles.skeletonToolbar}>
        <i data-w="search" />
        <i data-w="chips" />
      </div>
      <div className={styles.table}>
        <div className={styles.head} aria-hidden="true" />
        {Array.from({ length: 8 }, (_, row) => (
          <div className={styles.skeletonRow} key={row}>
            <i data-w="title" />
            <i data-w="meta" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Route-level loading: the header plus the same skeleton blocks. */
export function CallsSkeleton() {
  return (
    <div className={styles.page} data-workspace="true">
      <header className={styles.header}>
        <div className={styles.headerCopy}>
          <h1>Calls</h1>
          <p>Private to your account and workspace</p>
        </div>
      </header>
      <CallsBodySkeleton />
    </div>
  );
}
