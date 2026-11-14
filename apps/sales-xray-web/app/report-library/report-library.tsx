"use client";

/**
 * Reports, the phone's Reports tab (/analysis/calls): Dipak's Reports V4
 * (docs/handoffs/dipak-folder-20261113/REPORTS-V4-SPEC.md, 13 Nov 2026).
 *
 * - Main (the default): a waveform, "+ Analyse a call", and the three newest
 *   reports with View all.
 * - All Reports: "+ New analysis", a search, Filters (lead type and a From–To
 *   calendar), the filters as chips, "N of M reports", newest first, and the
 *   cards; nothing matching says so and clears everything in one tap.
 * - Analyse a call (?view=analyse): "Make your next call better." and Choose
 *   audio file; the file goes on to New analysis, the existing flow.
 * - Your calls (?view=calls, or a number from Home or Team): the phone's own
 *   calls, as before, behind a link on Main.
 *
 * A card opens the call's existing report (Sales X-ray Report, Prospect's
 * Information, Coaching) unchanged. The tab, search and filters live in the
 * address, so Back from a report finds the list as it was left.
 */

import {
  ArrowDownUp,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  FileAudio,
  Phone,
  Plus,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { CALLS_PATH, NEW_ANALYSIS_PATH, callPath } from "../analysis-routes";
import { callsFilter, PhoneCalls } from "../calls/phone-calls";
import { CALLS_PAGE_NAME } from "../calls-page-name";
import { RecordingLine } from "../capture-setup/recording-check";
import { useDisplayDates } from "../display-clock";
import { notify } from "../notice-center";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { useTabAgain } from "../shell/tab-again";
import { OVERLAY_DEPTH_KEY } from "../ui/back-close";
import { Skeleton } from "../ui/kit";
import { SectionBoundary } from "../ui/section-boundary";
import { useWorkspaceAccess } from "../workspace-access";
import { FilterSheet } from "./filter-sheet";
import {
  NO_FILTERS,
  SAVED_LABEL,
  SOURCE_LABEL,
  activeFilterCount,
  completeRange,
  countLine,
  isDay,
  isLeadTypeFilter,
  leadTypeLabel,
  newestFirst,
  rangeWords,
  summaryLine,
  visibleReports,
  type ReportQuery,
  type ReportRow,
} from "./report-filter";
import {
  markSaved,
  readReports,
  saveReport,
  shelveReports,
  shelvedReports,
  watchShelves,
} from "./report-rows";
import styles from "./report-library.module.css";
import {
  RECORDING_ACCEPT,
  RECORDING_FORMATS,
  handOverRecording,
} from "./upload-handoff";
import { Waveform } from "./waveform";

/** Recent reports on Main (section 5). */
export const RECENT_REPORTS = 3;
/** While a call is being analysed, the list reads again this often. */
const ACTIVE_REREAD_MS = 20_000;
const RETURN_KEY = "sx.reports.return";

type Tab = "main" | "all";

/** The filters a list address carries (tab=all&q=…&type=…&from=…&to=…). */
export function filtersFromAddress(params: URLSearchParams): ReportQuery {
  const type = params.get("type");
  const from = params.get("from");
  const to = params.get("to");
  const range = completeRange(isDay(from) ? from : null, isDay(to) ? to : null);
  return {
    query: params.get("q") ?? "",
    leadType: isLeadTypeFilter(type) ? type : null,
    from: range?.from ?? null,
    to: range?.to ?? null,
  };
}

export function tabFromAddress(params: URLSearchParams): Tab {
  const tab = params.get("tab");
  if (tab === "all") return "all";
  if (tab === "main") return "main";
  // A search sent here (the header's "Search calls for …") is a library search.
  return params.get("q") ? "all" : "main";
}

/** The list's address for this tab and these filters, other keys kept. */
export function listAddress(
  current: URLSearchParams,
  tab: Tab,
  filters: ReportQuery,
): string {
  const next = new URLSearchParams(current);
  for (const key of ["tab", "q", "type", "from", "to"]) next.delete(key);
  if (tab === "all") {
    next.set("tab", "all");
    if (filters.query) next.set("q", filters.query);
    if (filters.leadType) next.set("type", filters.leadType);
    const range = completeRange(filters.from, filters.to);
    if (range) {
      next.set("from", range.from);
      next.set("to", range.to);
    }
  }
  const search = next.toString();
  return `${CALLS_PATH}${search ? `?${search}` : ""}`;
}

/** The list a report was opened from, for its way back (session only). */
export function rememberReturn(address: string) {
  try {
    sessionStorage.setItem(RETURN_KEY, address);
  } catch {
    /* no storage: Back still returns through history */
  }
}

function useIdentity() {
  const access = useWorkspaceAccess();
  const context =
    access?.authenticated === true && access.status === "ready"
      ? access.context
      : null;
  const workspace = access?.workspaces?.find(
    (item) => item.tenant_id === context?.tenantId,
  );
  return {
    access,
    context,
    identity: context
      ? JSON.stringify([context.personId, context.sessionId, context.tenantId])
      : null,
    organisation: workspace?.kind === "organisation",
  };
}

export function ReportLibrary() {
  const { access, context, identity, organisation } = useIdentity();
  if (!context || !identity) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        loading={loading}
        active="calls"
        mobileFit={false}
      >
        {loading ? (
          <ReportsSkeleton />
        ) : (
          <SignedOutWelcome
            title="Sign in to see your reports"
            text="Your analysed calls and their reports, in one place."
          />
        )}
      </AcquisitionShell>
    );
  }
  return (
    <AcquisitionShell authenticated active="calls" mobileFit={false}>
      <LibraryBody
        key={identity}
        identity={identity}
        viewerId={context.personId}
        organisation={organisation}
      />
    </AcquisitionShell>
  );
}

type Load = {
  rows: ReportRow[];
  status: "loading" | "ready" | "error";
  complete: boolean;
};

/** Every report of this identity: the shelf at once, then a fresh read. */
function useReports(identity: string, viewerId: string): [Load, () => void] {
  const dates = useDisplayDates();
  const shelf = useSyncExternalStore(
    watchShelves,
    () => shelvedReports(identity),
    () => null,
  );
  const [status, setStatus] = useState<Load["status"]>(
    shelf ? "ready" : "loading",
  );
  const [round, setRound] = useState(0);
  const timeZone = dates.timeZone;
  useEffect(() => {
    const controller = new AbortController();
    readReports({ timeZone }, viewerId, controller.signal, (rows, complete) => {
      if (controller.signal.aborted) return;
      // A partial read never hides rows the shelf already shows.
      const known = shelvedReports(identity);
      if (complete || !known || rows.length >= known.rows.length)
        shelveReports(identity, { rows, complete });
      setStatus("ready");
    }).catch(() => {
      if (!controller.signal.aborted)
        setStatus((current) => (current === "ready" ? current : "error"));
    });
    return () => controller.abort();
  }, [identity, viewerId, timeZone, round]);
  const rows = shelf?.rows ?? [];
  const active = rows.some((row) => row.active);
  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(
      () => setRound((value) => value + 1),
      ACTIVE_REREAD_MS,
    );
    return () => window.clearTimeout(timer);
  }, [active, round]);
  useEffect(() => {
    const again = () => {
      if (document.visibilityState === "visible")
        setRound((value) => value + 1);
    };
    document.addEventListener("visibilitychange", again);
    return () => document.removeEventListener("visibilitychange", again);
  }, []);
  const retry = useCallback(() => {
    setStatus("loading");
    setRound((value) => value + 1);
  }, []);
  return [
    {
      rows,
      status: shelf ? "ready" : status,
      complete: shelf?.complete ?? false,
    },
    retry,
  ];
}

function LibraryBody({
  identity,
  viewerId,
  organisation,
}: {
  identity: string;
  viewerId: string;
  organisation: boolean;
}) {
  const params = useSearchParams();
  const router = useRouter();
  const dates = useDisplayDates();
  const view = params.get("view");
  const phoneFilter = callsFilter(params);
  const listShown = view !== "analyse" && view !== "calls" && !phoneFilter;
  const [tab, setTab] = useState<Tab>(() => tabFromAddress(params));
  const [filters, setFilters] = useState<ReportQuery>(() =>
    filtersFromAddress(params),
  );
  const [sheetOpen, setSheetOpen] = useState(false);
  const [load, retry] = useReports(identity, viewerId);
  const top = useRef<HTMLDivElement>(null);
  // The Reports tab tapped while Reports is open: back to Main, at the top
  // (the prototype's Reports tab; the filters stay for All Reports).
  useTabAgain("reports", () => {
    setSheetOpen(false);
    setTab("main");
    window.scrollTo?.({ top: 0 });
  });

  // The address follows the tab and the filters without a new history entry,
  // so Back from a report returns to this list as it was left. Never on an
  // open sheet's own entry (back-close.ts): once Back or the sheet's closing
  // takes it off, the page's entry gets the address.
  const syncAddress = useCallback(() => {
    if (!listShown) return;
    const state: unknown = window.history.state;
    const depth =
      state && typeof state === "object"
        ? (state as Record<string, unknown>)[OVERLAY_DEPTH_KEY]
        : undefined;
    if (typeof depth === "number" && depth > 0) return;
    const address = listAddress(
      new URLSearchParams(window.location.search),
      tab,
      filters,
    );
    if (address !== `${window.location.pathname}${window.location.search}`)
      window.history.replaceState(window.history.state, "", address);
  }, [tab, filters, listShown]);
  useEffect(() => {
    syncAddress();
    const again = () => window.setTimeout(syncAddress, 0);
    window.addEventListener("popstate", again);
    return () => window.removeEventListener("popstate", again);
  }, [syncAddress]);

  const openAnalyse = () => {
    router.push(`${CALLS_PATH}?view=analyse`);
  };
  const showTab = (next: Tab) => {
    setTab(next);
    top.current?.scrollIntoView?.({ block: "start" });
  };

  if (view === "analyse")
    return (
      <AnalyseScreen
        onBack={() =>
          window.history.length > 1 ? router.back() : router.replace(CALLS_PATH)
        }
      />
    );
  if (view === "calls" || phoneFilter)
    return (
      <YourCalls
        query={view === "calls" ? (params.get("q") ?? "") : ""}
        filter={phoneFilter}
        identity={identity}
      />
    );

  const save = async (row: ReportRow) => {
    const next = !row.saved;
    markSaved(row.id, next);
    try {
      const saved = await saveReport(row.id, next);
      if (saved !== next) markSaved(row.id, saved);
    } catch {
      markSaved(row.id, row.saved);
      notify({
        id: `report-save-${row.id}`,
        tone: "error",
        title: next ? "The report wasn't saved" : "The report is still saved",
        message: "Check your connection and try again.",
      });
    }
  };
  const open = () =>
    rememberReturn(`${window.location.pathname}${window.location.search}`);

  return (
    <div className={styles.page} ref={top} data-reports-v4="" data-tab={tab}>
      {/* The bar names the page; this is its heading for screen readers. */}
      <h1 className={styles.srOnly}>{CALLS_PAGE_NAME}</h1>
      <RecordingLine />
      <p className={styles.subtitle}>
        {tab === "main"
          ? "Turn your sales conversations into clearer next steps."
          : "All your analysed calls, easy to revisit."}
      </p>
      <div className={styles.tabs} role="tablist" aria-label="Report sections">
        {(
          [
            ["main", "Main"],
            ["all", "All Reports"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            id={`reports-tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`reports-panel-${key}`}
            className={styles.tab}
            onClick={() => showTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        className={styles.panel}
        id={`reports-panel-${tab}`}
        aria-labelledby={`reports-tab-${tab}`}
      >
        {tab === "main" ? (
          <MainTab
            load={load}
            retry={retry}
            organisation={organisation}
            onAnalyse={openAnalyse}
            onViewAll={() => showTab("all")}
            onOpen={open}
            onSave={save}
          />
        ) : (
          <AllTab
            load={load}
            retry={retry}
            filters={filters}
            setFilters={setFilters}
            onAnalyse={openAnalyse}
            onFilters={() => setSheetOpen(true)}
            onOpen={open}
            onSave={save}
          />
        )}
      </div>
      <FilterSheet
        open={sheetOpen}
        applied={filters}
        rows={load.rows}
        today={dates.today}
        onClose={() => setSheetOpen(false)}
        onApply={(next) => {
          setFilters((current) => ({ ...current, ...next }));
          setSheetOpen(false);
        }}
      />
    </div>
  );
}

function MainTab({
  load,
  retry,
  organisation,
  onAnalyse,
  onViewAll,
  onOpen,
  onSave,
}: {
  load: Load;
  retry: () => void;
  organisation: boolean;
  onAnalyse: () => void;
  onViewAll: () => void;
  onOpen: () => void;
  onSave: (row: ReportRow) => void;
}) {
  const recent = newestFirst(load.rows).slice(0, RECENT_REPORTS);
  return (
    <>
      <section className={styles.analyse} aria-label="Analyse a call">
        <Waveform />
        <button
          type="button"
          className={`${styles.primary} ${styles.analyseButton}`}
          onClick={onAnalyse}
        >
          <Plus size={20} aria-hidden="true" />
          Analyse a call
        </button>
      </section>
      <div className={styles.sectionLine}>
        <h2 id="recent-reports">Recent reports</h2>
        <button type="button" className={styles.textButton} onClick={onViewAll}>
          View all
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      </div>
      <ReportList
        load={load}
        rows={recent}
        retry={retry}
        labelledBy="recent-reports"
        empty={
          <div className={styles.firstTime} data-first-time="">
            <p>No reports yet. Analyse a call and its report shows here.</p>
          </div>
        }
        onOpen={onOpen}
        onSave={onSave}
        placeholders={RECENT_REPORTS}
      />
      {organisation ? (
        <Link
          href={`${CALLS_PATH}?view=calls`}
          className={styles.callLog}
          data-your-calls=""
        >
          <Phone size={18} aria-hidden="true" />
          <span>
            <b>Your phone calls</b>
            <small>Calls and recordings on this phone, newest first</small>
          </span>
          <ChevronRight size={18} aria-hidden="true" />
        </Link>
      ) : null}
    </>
  );
}

function AllTab({
  load,
  retry,
  filters,
  setFilters,
  onAnalyse,
  onFilters,
  onOpen,
  onSave,
}: {
  load: Load;
  retry: () => void;
  filters: ReportQuery;
  setFilters: (update: (current: ReportQuery) => ReportQuery) => void;
  onAnalyse: () => void;
  onFilters: () => void;
  onOpen: () => void;
  onSave: (row: ReportRow) => void;
}) {
  const shown = visibleReports(load.rows, filters);
  const count = activeFilterCount(filters);
  const range = completeRange(filters.from, filters.to);
  const clearAll = () => setFilters(() => NO_FILTERS);
  return (
    <>
      <div className={styles.sectionLine}>
        <h2 id="all-reports">All reports</h2>
        <button type="button" className={styles.textButton} onClick={onAnalyse}>
          <Plus size={18} aria-hidden="true" />
          New analysis
        </button>
      </div>
      <div className={styles.tools}>
        <label className={styles.search}>
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            placeholder="Search reports"
            aria-label="Search reports"
            value={filters.query}
            enterKeyHint="search"
            onChange={(event) => {
              const query = event.target.value;
              setFilters((current) => ({ ...current, query }));
            }}
          />
        </label>
        <button
          type="button"
          className={styles.filters}
          data-active={count ? "" : undefined}
          aria-label={
            count
              ? `Filters, ${count} active ${count === 1 ? "filter" : "filters"}`
              : "Filters"
          }
          onClick={onFilters}
        >
          {/* The count takes the icon's place, so the button keeps its width
              and "Search reports" stays whole at large text. */}
          {count ? (
            <span className={styles.filterCount} aria-hidden="true">
              {count}
            </span>
          ) : (
            <SlidersHorizontal size={18} aria-hidden="true" />
          )}
          Filters
        </button>
      </div>
      <div className={styles.resultRow} aria-live="polite">
        <span data-report-count="">
          {load.status === "ready" ? (
            countLine(shown.length, load.rows.length, filters)
          ) : (
            <Skeleton width={120} height={14} />
          )}
        </span>
        <span className={styles.sort}>
          <ArrowDownUp size={14} aria-hidden="true" />
          Newest first
        </span>
      </div>
      {count ? (
        <div className={styles.chips} aria-label="Applied filters">
          {filters.leadType ? (
            <span className={styles.chip}>
              {leadTypeLabel(filters.leadType)}
              <button
                type="button"
                aria-label="Remove lead type filter"
                onClick={() =>
                  setFilters((current) => ({ ...current, leadType: null }))
                }
              >
                <X size={16} aria-hidden="true" />
              </button>
            </span>
          ) : null}
          {range ? (
            <span className={styles.chip}>
              {rangeWords(range.from, range.to)}
              <button
                type="button"
                aria-label="Remove date filter"
                onClick={() =>
                  setFilters((current) => ({
                    ...current,
                    from: null,
                    to: null,
                  }))
                }
              >
                <X size={16} aria-hidden="true" />
              </button>
            </span>
          ) : null}
        </div>
      ) : null}
      <ReportList
        load={load}
        rows={shown}
        retry={retry}
        labelledBy="all-reports"
        empty={
          load.rows.length === 0 ? (
            <div className={styles.firstTime} data-first-time="">
              <p>No reports yet. Analyse a call and its report shows here.</p>
            </div>
          ) : (
            <div className={styles.empty} data-no-match="">
              <span className={styles.emptyIcon} aria-hidden="true">
                <Search size={20} />
              </span>
              <h3>No matching reports</h3>
              <p>
                Try a different lead type or date range. Your reports have not
                been removed.
              </p>
              <button
                type="button"
                className={styles.secondary}
                onClick={clearAll}
              >
                Clear filters &amp; search
              </button>
            </div>
          )
        }
        onOpen={onOpen}
        onSave={onSave}
        placeholders={4}
      />
      {load.status === "ready" && !load.complete ? (
        <p className={styles.more} role="status">
          Loading older reports…
        </p>
      ) : null}
    </>
  );
}

function ReportList({
  load,
  rows,
  retry,
  labelledBy,
  empty,
  onOpen,
  onSave,
  placeholders,
}: {
  load: Load;
  rows: readonly ReportRow[];
  retry: () => void;
  labelledBy: string;
  empty: ReactNode;
  onOpen: () => void;
  onSave: (row: ReportRow) => void;
  placeholders: number;
}) {
  if (load.status === "loading")
    return (
      <div
        className={styles.list}
        aria-busy="true"
        aria-label="Loading reports"
      >
        {Array.from({ length: placeholders }, (_, index) => (
          <div key={index} className={styles.cardSkeleton}>
            <Skeleton width="40%" height={14} />
            <Skeleton width="80%" height={18} />
            <Skeleton width="95%" height={14} />
          </div>
        ))}
      </div>
    );
  if (load.status === "error" && load.rows.length === 0)
    return (
      <div className={styles.empty} role="alert">
        <h3>Your reports didn&apos;t load</h3>
        <p>Check your connection and try again.</p>
        <button type="button" className={styles.secondary} onClick={retry}>
          Try again
        </button>
      </div>
    );
  if (rows.length === 0) return <>{empty}</>;
  return (
    <ol className={styles.list} aria-labelledby={labelledBy}>
      {rows.map((row) => (
        <li key={row.id}>
          <ReportCard row={row} onOpen={onOpen} onSave={onSave} />
        </li>
      ))}
    </ol>
  );
}

/** "13 Nov · 6:40 PM", with the year when it isn't this year (section 16 B). */
export function cardWhen(
  row: Pick<ReportRow, "createdAt">,
  dates: { locale: string; timeZone: string; today: string },
): string {
  const at = new Date(row.createdAt);
  if (Number.isNaN(at.getTime())) return "";
  const year = new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    timeZone: dates.timeZone,
  }).format(at);
  const day = new Intl.DateTimeFormat(dates.locale, {
    day: "numeric",
    month: "short",
    year: year === dates.today.slice(0, 4) ? undefined : "numeric",
    timeZone: dates.timeZone,
  }).format(at);
  const time = new Intl.DateTimeFormat(dates.locale, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: dates.timeZone,
  })
    .format(at)
    .replace(
      /\s?([ap])\.?\s?m\.?$/i,
      (_, half: string) => ` ${half.toUpperCase()}M`,
    );
  return `${day} · ${time}`;
}

/** "21 min", "45 sec" (section 16 F). */
export function durationWords(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec`;
  return `${Math.round(seconds / 60)} min`;
}

function ReportCard({
  row,
  onOpen,
  onSave,
}: {
  row: ReportRow;
  onOpen: () => void;
  onSave: (row: ReportRow) => void;
}) {
  const dates = useDisplayDates();
  const heading = `${row.prospect ?? "Unassigned prospect"} · ${row.topic}`;
  return (
    <article
      className={styles.card}
      data-report-card={row.id}
      data-source={row.source}
      data-saved={row.saved ? "" : undefined}
    >
      <div className={styles.cardTop}>
        <span className={styles.pill} data-source={row.source}>
          {SOURCE_LABEL[row.source]}
        </span>
        <span className={styles.when}>{cardWhen(row, dates)}</span>
      </div>
      <div className={styles.cardTitle}>
        <h3>
          <Link
            href={callPath(row.id)}
            className={styles.cardLink}
            onClick={onOpen}
          >
            {heading}
          </Link>
        </h3>
        <button
          type="button"
          className={styles.save}
          aria-pressed={row.saved}
          aria-label={
            row.saved ? `${SAVED_LABEL}: ${heading}` : `Save report: ${heading}`
          }
          title={row.saved ? SAVED_LABEL : "Save report"}
          onClick={() => onSave(row)}
        >
          <Bookmark size={20} aria-hidden="true" />
        </button>
      </div>
      {row.summary ? (
        <p className={styles.summary}>{summaryLine(row.summary)}</p>
      ) : null}
      <div className={styles.cardFoot}>
        <span className={styles.meta}>
          {durationWords(row.durationSeconds)} · {row.status}
          {row.owner ? ` · ${row.owner}` : ""}
        </span>
        <span className={styles.open} aria-hidden="true">
          View report
          <ChevronRight size={16} />
        </span>
      </div>
    </article>
  );
}

function AnalyseScreen({ onBack }: { onBack: () => void }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  return (
    <div className={styles.page} data-reports-analyse="">
      <button type="button" className={styles.back} onClick={onBack}>
        <ChevronLeft size={20} aria-hidden="true" />
        Back to Reports
      </button>
      <h1 className={styles.uploadTitle}>Make your next call better.</h1>
      <p className={styles.subtitle}>
        Upload a call, get clear feedback you can use.
      </p>
      <div className={styles.upload}>
        <span className={styles.uploadIcon} aria-hidden="true">
          <FileAudio size={28} />
        </span>
        <button
          type="button"
          className={`${styles.primary} ${styles.uploadButton}`}
          onClick={() => input.current?.click()}
        >
          Choose audio file
        </button>
        <input
          ref={input}
          type="file"
          accept={RECORDING_ACCEPT}
          hidden
          data-recording-input=""
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            setChosen(file.name);
            handOverRecording(file);
            // New analysis takes this screen's place: its Back is Reports.
            router.replace(NEW_ANALYSIS_PATH);
          }}
        />
        <p className={styles.chosen} aria-live="polite" data-chosen-file="">
          {chosen ? `Selected: ${chosen}` : "No file selected"}
        </p>
        <p className={styles.formats}>{RECORDING_FORMATS}</p>
      </div>
    </div>
  );
}

function YourCalls({
  query,
  filter,
  identity,
}: {
  query: string;
  filter: ReturnType<typeof callsFilter>;
  identity: string;
}) {
  return (
    <div className={styles.page} data-reports-calls="">
      <Link href={CALLS_PATH} className={styles.back}>
        <ChevronLeft size={20} aria-hidden="true" />
        Back to Reports
      </Link>
      <RecordingLine />
      <SectionBoundary name="Your calls" resetKey={identity}>
        <PhoneCalls key={identity} filter={filter} query={query} />
      </SectionBoundary>
    </div>
  );
}

export function ReportsSkeleton() {
  return (
    <div className={styles.page} aria-busy="true" data-reports-loading="">
      <h1 className={styles.srOnly}>{CALLS_PAGE_NAME}</h1>
      <Skeleton width="80%" height={16} />
      <div className={styles.tabs} aria-hidden="true">
        <span className={styles.tab} />
        <span className={styles.tab} />
      </div>
      <Skeleton width="100%" height={87} />
      <Skeleton width="100%" height={52} />
    </div>
  );
}
