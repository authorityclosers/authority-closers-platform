"use client";

/**
 * Calls (/analysis/calls): the seller's recorded calls and, for an owner, the
 * team's. sx-redesign board pick 08-calls, "summary first" (owner, 21 Nov
 * 2026), on Dipak's Reports V4 (docs/handoffs/dipak-folder-20261113/
 * REPORTS-V4-SPEC.md, 13 Nov 2026).
 *
 * - One hero card says the one thing that matters: how many calls need your
 *   review (no report yet, and nothing working on it), with one green button
 *   that shows them. With none, it counts the reports ready and the button is
 *   Analyse a call.
 * - A switch: All, Needs review (N), Reports ready. Search and Filters (lead
 *   type and a From–To calendar) work on every view; the filters show as
 *   chips, and nothing matching says so and clears everything in one tap.
 * - The calls, newest first, under Today, Yesterday and earlier days: the
 *   lead, how long and when, how the call ended in one word, and the report's
 *   state. Save keeps a report in Saved Reports.
 * - Under the list: Analyse a call (when the hero button is Review), Your
 *   phone calls in a workspace, and Find my old calls in the phone app.
 * - Analyse a call (?view=analyse): "Make your next call better." and Choose
 *   audio file; the file goes on to New analysis, the existing flow.
 * - Your calls (?view=calls, or a number from Home or Team): the phone's own
 *   calls, as before.
 *
 * A row opens the call's existing report (Report, Prospect, Coaching). The
 * view, search and filters live in the address, so Back from a report finds
 * the list as it was left.
 */

import {
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
import { callDate } from "../call-status";
import { OldCallsCard } from "../calls/old-calls/old-calls-card";
import { callsFilter, PhoneCalls } from "../calls/phone-calls";
import { CALLS_PAGE_NAME } from "../calls-page-name";
import { RecordingLine } from "../capture-setup/recording-check";
import { useDisplayDates } from "../display-clock";
import type { DisplayDates } from "../display-dates";
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
  activeFilterCount,
  completeRange,
  countLine,
  isDay,
  isLeadTypeFilter,
  leadTypeLabel,
  newestFirst,
  rangeWords,
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

/** Rows shown at first, and added by each Show more. */
export const PAGE_ROWS = 20;
/** While a call is being analysed, the list reads again this often. */
const ACTIVE_REREAD_MS = 20_000;
const RETURN_KEY = "sx.reports.return";

/** The switch: every call, the ones waiting on you, the ones with a report. */
export type Tab = "all" | "review" | "ready";
export const TABS: readonly (readonly [Tab, string])[] = [
  ["all", "All"],
  ["review", "Needs review"],
  ["ready", "Reports ready"],
];

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
  return tab === "review" || tab === "ready" ? tab : "all";
}

/** The list's address for this view and these filters, other keys kept. */
export function listAddress(
  current: URLSearchParams,
  tab: Tab,
  filters: ReportQuery,
): string {
  const next = new URLSearchParams(current);
  for (const key of ["tab", "q", "type", "from", "to"]) next.delete(key);
  if (tab !== "all") next.set("tab", tab);
  if (filters.query) next.set("q", filters.query);
  if (filters.leadType) next.set("type", filters.leadType);
  const range = completeRange(filters.from, filters.to);
  if (range) {
    next.set("from", range.from);
    next.set("to", range.to);
  }
  const search = next.toString();
  return `${CALLS_PATH}${search ? `?${search}` : ""}`;
}

/** The rows a view holds, before search and filters. */
export function rowsForTab(rows: readonly ReportRow[], tab: Tab): ReportRow[] {
  if (tab === "review") return rows.filter((row) => row.needsReview);
  if (tab === "ready") return rows.filter((row) => row.ready);
  return [...rows];
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
  // The Calls tab tapped while Calls is open: every call, at the top.
  useTabAgain("reports", () => {
    setSheetOpen(false);
    setTab("all");
    window.scrollTo?.({ top: 0 });
  });

  // The address follows the view and the filters without a new history
  // entry, so Back from a report returns to this list as it was left. Never
  // on an open sheet's own entry (back-close.ts): once Back or the sheet's
  // closing takes it off, the page's entry gets the address.
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

  const needs = load.rows.filter((row) => row.needsReview).length;
  const ready = load.rows.filter((row) => row.ready).length;
  const tabRows = rowsForTab(newestFirst(load.rows), tab);
  const shown = visibleReports(tabRows, filters);
  const count = activeFilterCount(filters);
  const range = completeRange(filters.from, filters.to);
  const narrowed = count > 0 || Boolean(filters.query.trim());
  const clearAll = () => setFilters(() => NO_FILTERS);
  // Exactly one green button: the hero's. Review when calls wait, else Analyse.
  const heroReviews = needs > 0;

  return (
    <div className={styles.page} ref={top} data-reports-v4="" data-tab={tab}>
      {/* The bar names the page; this is its heading for screen readers. */}
      <h1 className={styles.srOnly}>{CALLS_PAGE_NAME}</h1>
      <RecordingLine />
      <CallsHero
        load={load}
        needs={needs}
        ready={ready}
        onReview={() => showTab("review")}
        onAnalyse={openAnalyse}
      />
      <div className={styles.tabs} role="tablist" aria-label="Which calls">
        {TABS.map(([key, label]) => (
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
            {key === "review" && load.status === "ready"
              ? `${label} (${needs})`
              : label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        className={styles.panel}
        id={`reports-panel-${tab}`}
        aria-labelledby={`reports-tab-${tab}`}
      >
        <div className={styles.tools}>
          <label className={styles.search}>
            <Search size={18} aria-hidden="true" />
            <input
              type="search"
              placeholder="Search by lead name"
              aria-label="Search calls"
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
            onClick={() => setSheetOpen(true)}
          >
            {/* The count takes the icon's place, so the button keeps its
                width and the search box stays whole at large text. */}
            {count ? (
              <span className={styles.filterCount} aria-hidden="true">
                {count}
              </span>
            ) : (
              <SlidersHorizontal size={18} aria-hidden="true" />
            )}
            <span className={styles.filtersWord}>Filters</span>
          </button>
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
        {narrowed && load.status === "ready" ? (
          <p className={styles.resultRow} aria-live="polite">
            <span data-report-count="">
              {countLine(shown.length, tabRows.length, filters)}
            </span>
          </p>
        ) : null}
        <CallList
          key={`${tab}:${filters.query}:${filters.leadType}:${filters.from}:${filters.to}`}
          load={load}
          rows={shown}
          dates={dates}
          retry={retry}
          empty={
            load.rows.length === 0 ? (
              <div className={styles.firstTime} data-first-time="">
                <p>No calls yet. Analyse a call and its report shows here.</p>
              </div>
            ) : narrowed ? (
              <div className={styles.empty} data-no-match="">
                <span className={styles.emptyIcon} aria-hidden="true">
                  <Search size={20} />
                </span>
                <h3>No matching calls</h3>
                <p>
                  Try a different name, lead type or date. Your calls have not
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
            ) : (
              <div className={styles.firstTime} data-first-time="">
                <p>
                  {tab === "review"
                    ? "Nothing to review. Every call has its report or is on its way."
                    : "No reports ready yet. They show here when they are done."}
                </p>
              </div>
            )
          }
          onOpen={open}
          onSave={save}
        />
        {load.status === "ready" && !load.complete ? (
          <p className={styles.more} role="status">
            Loading older calls…
          </p>
        ) : null}
        <MoreLinks
          analyse={heroReviews}
          organisation={organisation}
          onAnalyse={openAnalyse}
        />
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

/** The ring's arc: `part` of `whole`, a full ring when there is nothing yet. */
function Ring({
  part,
  whole,
  value,
  label,
}: {
  part: number;
  whole: number;
  value: ReactNode;
  label: string;
}) {
  const radius = 42;
  const length = 2 * Math.PI * radius;
  const share = whole > 0 ? Math.min(1, Math.max(0, part / whole)) : 0;
  return (
    <span className={styles.ring} aria-hidden="true">
      <svg viewBox="0 0 100 100">
        <circle className={styles.ringTrack} cx="50" cy="50" r={radius} />
        {share > 0 ? (
          <circle
            className={styles.ringArc}
            cx="50"
            cy="50"
            r={radius}
            strokeDasharray={`${share * length} ${length}`}
          />
        ) : null}
      </svg>
      <span className={styles.ringText}>
        <b>{value}</b>
        <small>{label}</small>
      </span>
    </span>
  );
}

const plural = (count: number, one: string, many: string) =>
  `${count} ${count === 1 ? one : many}`;

/** The one hero: calls waiting on you, else the reports ready. */
function CallsHero({
  load,
  needs,
  ready,
  onReview,
  onAnalyse,
}: {
  load: Load;
  needs: number;
  ready: number;
  onReview: () => void;
  onAnalyse: () => void;
}) {
  if (load.status === "loading")
    return (
      <section
        className={styles.hero}
        aria-busy="true"
        aria-label="Loading your calls"
      >
        <Skeleton width={96} height={96} radius="circle" />
        <span className={styles.heroText}>
          <Skeleton width="80%" height={24} />
          <Skeleton width="60%" height={16} />
        </span>
      </section>
    );
  const total = load.rows.length;
  const review = needs > 0;
  const title = review
    ? `${plural(needs, "call needs", "calls need")} your review`
    : total
      ? `${plural(ready, "report", "reports")} ready`
      : "No reports yet";
  const line = review
    ? "They have no report yet. Open each one to get it."
    : total
      ? "You are all caught up. Analyse a new call any time."
      : "Analyse a call and its report shows here.";
  return (
    <section
      className={styles.hero}
      aria-labelledby="calls-hero-title"
      data-calls-hero={review ? "review" : "ready"}
    >
      <Ring
        part={review ? needs : ready}
        whole={total}
        value={review ? needs : ready}
        label={review ? "to review" : "ready"}
      />
      <span className={styles.heroText}>
        <h2 id="calls-hero-title">{title}</h2>
        <p>{line}</p>
        {review ? (
          <button
            type="button"
            className={`${styles.primary} ${styles.heroButton}`}
            onClick={onReview}
          >
            Review {plural(needs, "call", "calls")}
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            className={`${styles.primary} ${styles.heroButton}`}
            onClick={onAnalyse}
          >
            <Plus size={18} aria-hidden="true" />
            Analyse a call
          </button>
        )}
      </span>
    </section>
  );
}

/** "Today", "Yesterday", "13 Nov": the day groups, newest first. */
export function dayGroups(
  rows: readonly ReportRow[],
  dates: DisplayDates,
): { label: string; rows: ReportRow[] }[] {
  const groups: { label: string; rows: ReportRow[] }[] = [];
  for (const row of rows) {
    const label = callDate(row.createdAt, undefined, dates);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.rows.push(row);
    else groups.push({ label, rows: [row] });
  }
  return groups;
}

function CallList({
  load,
  rows,
  dates,
  retry,
  empty,
  onOpen,
  onSave,
}: {
  load: Load;
  rows: readonly ReportRow[];
  dates: DisplayDates;
  retry: () => void;
  empty: ReactNode;
  onOpen: () => void;
  onSave: (row: ReportRow) => void;
}) {
  const [limit, setLimit] = useState(PAGE_ROWS);
  if (load.status === "loading")
    return (
      <div
        className={styles.rowsCard}
        aria-busy="true"
        aria-label="Loading calls"
      >
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className={styles.rowSkeleton}>
            <Skeleton width={40} height={40} radius="circle" />
            <span>
              <Skeleton width="55%" height={16} />
              <Skeleton width="35%" height={13} />
            </span>
          </div>
        ))}
      </div>
    );
  if (load.status === "error" && load.rows.length === 0)
    return (
      <div className={styles.empty} role="alert">
        <h3>Your calls didn&apos;t load</h3>
        <p>Check your connection and try again.</p>
        <button type="button" className={styles.secondary} onClick={retry}>
          Try again
        </button>
      </div>
    );
  if (rows.length === 0) return <>{empty}</>;
  const groups = dayGroups(rows.slice(0, limit), dates);
  return (
    <div className={styles.groups}>
      {groups.map((group, index) => (
        <section
          key={`${group.label}-${index}`}
          className={styles.group}
          aria-labelledby={`calls-day-${index}`}
        >
          <h2 id={`calls-day-${index}`} className={styles.dayHead}>
            {group.label}
          </h2>
          <ol className={`${styles.rowsCard} ${styles.list}`}>
            {group.rows.map((row) => (
              <li key={row.id}>
                <CallRow
                  row={row}
                  dates={dates}
                  onOpen={onOpen}
                  onSave={onSave}
                />
              </li>
            ))}
          </ol>
        </section>
      ))}
      {rows.length > limit ? (
        <button
          type="button"
          className={styles.secondary}
          onClick={() => setLimit((value) => value + PAGE_ROWS)}
        >
          Show more calls
        </button>
      ) : null}
    </div>
  );
}

/** How the Report says the call ended, in one word (sx-redesign 21 Nov 2026). */
export const OUTCOME_WORD: Record<string, { word: string; tone: string }> = {
  closed: { word: "Won", tone: "good" },
  follow_up: { word: "Follow-up", tone: "action" },
  future_date: { word: "Meeting", tone: "calls" },
  no_sale: { word: "Lost", tone: "problem" },
  disqualified: { word: "Not a fit", tone: "muted" },
};

/** The report's state, short: Report ready, Analysing, Needs review, … */
export function statusWord(row: ReportRow): { word: string; tone: string } {
  if (row.ready) return { word: "Report ready", tone: "good" };
  if (row.active) return { word: "Analysing", tone: "calls" };
  if (row.needsReview) return { word: "Needs review", tone: "action" };
  return { word: row.status.split(" · ")[0], tone: "muted" };
}

/** "4 min 12 s", "56 s": the call's own length. */
export function lengthWords(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) return `${Math.max(1, whole)} s`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

/** "10:40 am" in the reader's zone. */
export function clockWords(
  row: Pick<ReportRow, "createdAt">,
  dates: Pick<DisplayDates, "locale" | "timeZone">,
): string {
  const at = new Date(row.createdAt);
  if (Number.isNaN(at.getTime())) return "";
  return new Intl.DateTimeFormat(dates.locale, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: dates.timeZone,
  })
    .format(at)
    .replace(
      /\s?([ap])\.?\s?m\.?$/i,
      (_, half: string) => ` ${half.toLowerCase()}m`,
    );
}

/** "AS" for Ashwini Salunkhe; null when no lead names the call. */
export function initials(name: string | null): string | null {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const letters =
    words.length > 1 ? [words[0], words[words.length - 1]] : words;
  return letters
    .map((word) => Array.from(word)[0] ?? "")
    .join("")
    .toLocaleUpperCase();
}

const AVATAR_TONES = ["good", "info", "action", "calls", "problem"] as const;

function avatarTone(name: string): string {
  let sum = 0;
  for (const char of name) sum = (sum + (char.codePointAt(0) ?? 0)) % 9973;
  return AVATAR_TONES[sum % AVATAR_TONES.length];
}

function CallRow({
  row,
  dates,
  onOpen,
  onSave,
}: {
  row: ReportRow;
  dates: DisplayDates;
  onOpen: () => void;
  onSave: (row: ReportRow) => void;
}) {
  const name = row.prospect ?? row.topic;
  const letters = initials(row.prospect);
  const outcome = row.outcome ? OUTCOME_WORD[row.outcome] : undefined;
  const status = statusWord(row);
  const heading = row.prospect ? `${row.prospect} · ${row.topic}` : row.topic;
  return (
    <article
      className={styles.row}
      data-report-card={row.id}
      data-source={row.source}
      data-saved={row.saved ? "" : undefined}
    >
      <span
        className={styles.avatar}
        data-tone={letters ? avatarTone(name) : "muted"}
        aria-hidden="true"
      >
        {letters ?? <Phone size={18} />}
      </span>
      <span className={styles.rowMain}>
        <h3 className={styles.rowName}>
          <Link
            href={callPath(row.id)}
            className={styles.rowLink}
            aria-label={heading}
            onClick={onOpen}
          >
            {name}
          </Link>
        </h3>
        <span className={styles.rowMeta}>
          {lengthWords(row.durationSeconds)} · {clockWords(row, dates)}
          {row.owner ? (
            <span className={styles.metaOwner}> · {row.owner}</span>
          ) : null}
        </span>
      </span>
      <span className={styles.rowChips}>
        {row.owner ? (
          <span className={styles.chipOwner} title={row.owner}>
            {row.owner.split(" ")[0]}
          </span>
        ) : null}
        {outcome ? (
          <span className={styles.word} data-tone={outcome.tone}>
            {outcome.word}
          </span>
        ) : null}
        <span
          className={styles.word}
          data-tone={status.tone}
          data-report-status=""
        >
          {status.word}
        </span>
      </span>
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
        <Bookmark size={18} aria-hidden="true" />
      </button>
      <ChevronRight className={styles.chevron} size={18} aria-hidden="true" />
    </article>
  );
}

/** Under the list: Analyse a call (when the hero reviews), the phone's calls, old calls. */
function MoreLinks({
  analyse,
  organisation,
  onAnalyse,
}: {
  analyse: boolean;
  organisation: boolean;
  onAnalyse: () => void;
}) {
  return (
    <>
      {analyse || organisation ? (
        <div className={styles.links}>
          {analyse ? (
            <button
              type="button"
              className={styles.callLog}
              onClick={onAnalyse}
              data-analyse-link=""
            >
              <span className={styles.linkIcon} aria-hidden="true">
                <Plus size={20} />
              </span>
              <span>
                <b>Analyse a call</b>
                <small>Upload a recording and get its report</small>
              </span>
              <ChevronRight size={18} aria-hidden="true" />
            </button>
          ) : null}
          {organisation ? (
            <Link
              href={`${CALLS_PATH}?view=calls`}
              className={styles.callLog}
              data-your-calls=""
            >
              <span className={styles.linkIcon} aria-hidden="true">
                <Phone size={20} />
              </span>
              <span>
                <b>Your phone calls</b>
                <small>Calls and recordings on this phone, newest first</small>
              </span>
              <ChevronRight size={18} aria-hidden="true" />
            </Link>
          ) : null}
        </div>
      ) : null}
      {/* Find my old calls: the phone app only; nothing shows elsewhere. */}
      <OldCallsCard />
    </>
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

function AnalyseScreen({ onBack }: { onBack: () => void }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  return (
    <div className={styles.page} data-reports-analyse="">
      <button type="button" className={styles.back} onClick={onBack}>
        <ChevronLeft size={20} aria-hidden="true" />
        Back to Calls
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
            // New analysis takes this screen's place: its Back is Calls.
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
        Back to Calls
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
      <div className={styles.hero} aria-hidden="true">
        <Skeleton width={96} height={96} radius="circle" />
        <span className={styles.heroText}>
          <Skeleton width="80%" height={24} />
          <Skeleton width="60%" height={16} />
        </span>
      </div>
      <div className={styles.tabs} aria-hidden="true">
        <span className={styles.tab} />
        <span className={styles.tab} />
        <span className={styles.tab} />
      </div>
      <Skeleton width="100%" height={52} />
      <Skeleton width="100%" height={180} />
    </div>
  );
}
