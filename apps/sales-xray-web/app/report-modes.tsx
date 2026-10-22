"use client";

import { callIdFromPath } from "./analysis-routes";
import {
  Radar,
  AudioLines,
  BookOpen,
  ChartNoAxesColumnIncreasing,
  Ellipsis,
  FileText,
  Flag,
  Lightbulb,
  ListChecks,
  PanelsTopLeft,
  Route,
  Scale,
  TableProperties,
  Undo2,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { DEAL, NAV, VIEWS as VIEWS_COPY, backTo } from "./report-copy";
import {
  CallOutcomeProvider,
  FixtureCallOutcomeProvider,
} from "./report-outcome-context";
import { ReportReadingProvider } from "./report-reading-context";
import {
  ReportLookContext,
  applyReportSettings,
  reportLook,
  useReportSettings,
  type ReportLook,
} from "./report-settings";
import styles from "./report-modes.module.css";
import { TargetArrow } from "./xray-report/icons";
import type { XrayView } from "./xray-report/model";
import {
  PartHead,
  prospectPanel,
  xrayReportPanels,
} from "./xray-report/panels";

export type ReportPanel = {
  id: string;
  label: string;
  compactLabel?: string;
  content: ReactNode;
  summary?: string;
  /** A Report part head (15 Oct structure): icon square and an optional aside. */
  icon?: ReactNode;
  aside?: ReactNode;
};

export type { DocumentReportData } from "./report-document-data";
import {
  DOCUMENT_CHAPTERS,
  type DocumentReportData,
} from "./report-document-data";
import { ReportDocument } from "./report-document";
import { ReportCallCoaching } from "./report-call-coaching";
import type { ReportEvidence } from "./report-contract";
import type { ContextualSourcePlayback } from "./source-playback-context";
import { OperationalPanel } from "./ui/operational-panel";
import { useWorkspaceAccess } from "./workspace-access";

export type View =
  | "reading"
  | "tabs"
  | "document"
  | "story"
  | "prospect"
  | "coaching";
const VIEWS: readonly View[] = [
  "reading",
  "tabs",
  "document",
  "story",
  "prospect",
  "coaching",
];
type TextSize = "100" | "112.5" | "125";
const TEXT_SIZE_KEY = "ac:report-text-size";
const TEXT_SIZE_CHANGE = "ac:report-text-size-change";
function subscribeTextSize(notify: () => void) {
  window.addEventListener("storage", notify);
  window.addEventListener(TEXT_SIZE_CHANGE, notify);
  return () => {
    window.removeEventListener("storage", notify);
    window.removeEventListener(TEXT_SIZE_CHANGE, notify);
  };
}
function savedTextSizeSnapshot(): TextSize {
  try {
    const saved = localStorage.getItem(TEXT_SIZE_KEY);
    if (saved === "112.5" || saved === "125") return saved;
  } catch {}
  return "100";
}
function serverTextSizeSnapshot(): TextSize {
  return "100";
}

/** `view: null` means nobody chose yet: the viewport default applies. */
type Address = { view: View | null; section: string };
/** Desktop report width where Sections (tabbed) is the better first view. */
const TABBED_DEFAULT_QUERY = "(min-width: 1100px)";
/** Wide screens host the report navigation in the shell's top bar. */
const TOOLBAR_QUERY = "(min-width: 1280px)";
const CHANGE = "ac:report-mode-change";
/** A pillar asks for another view (event, so render never reads refs). */
const OPEN_VIEW = "ac:report-open-view";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const sectionIcons: Record<string, LucideIcon> = {
  overview: FileText,
  prospect: UserRound,
  moments: AudioLines,
  signals: Radar,
  skills: ChartNoAxesColumnIncreasing,
  "next-call-plan": Lightbulb,
  transcript: BookOpen,
  "raw-data": TableProperties,
  "call-coaching": Lightbulb,
  "prospect-information": UserRound,
};

/** The Report's parts (15 Oct structure); the six pillars kept their old ids. */
const pillarIcons: Record<string, LucideIcon> = {
  analysis: ListChecks,
  outcome: TargetArrow as LucideIcon,
  overview: ChartNoAxesColumnIncreasing,
  coaching: Route,
  moments: Scale,
  missed: AudioLines,
  skills: ChartNoAxesColumnIncreasing,
  facts: Flag,
};

function SectionIcon({ id, pillar = false }: { id: string; pillar?: boolean }) {
  const Icon = (pillar ? pillarIcons[id] : sectionIcons[id]) ?? FileText;
  return <Icon className={styles.sectionIcon} aria-hidden="true" />;
}

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  window.addEventListener("storage", notify);
  window.addEventListener(CHANGE, notify);
  return () => {
    window.removeEventListener("popstate", notify);
    window.removeEventListener("storage", notify);
    window.removeEventListener(CHANGE, notify);
  };
}

function addressFromSearch(
  search: string,
  boundCallId: string,
  panels: ReportPanel[],
  pathname: string,
): Address | null {
  const query = new URLSearchParams(search);
  const calls = query.getAll("call");
  const pathCallId = callIdFromPath(pathname);
  const requestedCallId = calls.length === 0 ? pathCallId : calls[0];
  const sections = query.getAll("section");
  const views = query.getAll("view");
  if (
    !UUID.test(boundCallId) ||
    calls.length > 1 ||
    requestedCallId !== boundCallId ||
    (pathCallId !== null && pathCallId !== boundCallId)
  )
    return null;
  // No explicit view: the caller applies its preferred default.
  const view: View | null =
    views.length === 1 && VIEWS.includes(views[0] as View)
      ? (views[0] as View)
      : null;
  const section =
    sections.length === 1 && panels.some((panel) => panel.id === sections[0])
      ? sections[0]
      : panels[0]?.id;
  return section ? { view, section } : null;
}

function browserLocation() {
  return window.location.pathname + window.location.search;
}

function scrollBehavior(): ScrollBehavior {
  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}

/** Reader input that takes over scrolling from a pending jump correction. */
const READER_SCROLL_INPUT = ["wheel", "touchstart", "pointerdown", "keydown"];
/** Upper bound on frames spent waiting for a jump's scroll to finish. */
const SETTLE_FRAME_LIMIT = 240;

/** The element that really scrolls the report: its nearest scrolling ancestor, else the document. */
function reportScroller(element: HTMLElement): HTMLElement {
  for (
    let parent = element.parentElement;
    parent;
    parent = parent.parentElement
  ) {
    const { overflowY } = window.getComputedStyle(parent);
    if (
      ["auto", "scroll", "overlay"].includes(overflowY) &&
      parent.scrollHeight > parent.clientHeight
    )
      return parent;
  }
  return (
    (document.scrollingElement as HTMLElement | null) ??
    document.documentElement
  );
}

/**
 * Waits for a jump's scroll to finish, then puts the destination exactly
 * below the sticky navigation. The scroll's end point is resolved once, when
 * it starts; content laid out for the first time during the motion (after a
 * viewport or view change) can shift the destination under the navigation.
 * Only the report's own scroller is corrected, once, and never after the
 * reader starts scrolling. Returns a cancel function.
 */
function settleJump(
  destination: HTMLElement,
  scroller: HTMLElement,
  startTop: number,
  measureOffset: () => number,
): () => void {
  const isDocument =
    scroller === document.scrollingElement ||
    scroller === document.documentElement;
  const events: EventTarget = isDocument ? window : scroller;
  let frame = 0;
  let frames = 0;
  let stableFrames = 0;
  let moved = false;
  let last = startTop;
  let done = false;

  const stop = () => {
    if (done) return;
    done = true;
    cancelAnimationFrame(frame);
    events.removeEventListener("scrollend", onScrollEnd);
    for (const type of READER_SCROLL_INPUT)
      window.removeEventListener(type, stop, true);
  };
  const correct = () => {
    stop();
    if (!destination.isConnected) return;
    const bounds = destination.getBoundingClientRect();
    // Hidden or not laid out: nothing can be measured or corrected.
    if (!bounds.width && !bounds.height) return;
    const scrollportTop = isDocument
      ? 0
      : scroller.getBoundingClientRect().top + scroller.clientTop;
    const drift = bounds.top - (scrollportTop + measureOffset());
    if (Math.abs(drift) <= 1) return;
    const top = scroller.scrollTop + drift;
    if (typeof scroller.scrollTo === "function")
      scroller.scrollTo({ top, behavior: "instant" });
    else scroller.scrollTop = top;
  };
  function onScrollEnd() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(correct);
  }
  const watch = () => {
    frames += 1;
    const position = scroller.scrollTop;
    if (position !== last) {
      moved = true;
      stableFrames = 0;
    } else stableFrames += 1;
    last = position;
    // Settled: motion stopped, the scroll never started, or the bound ran out.
    if (
      (moved && stableFrames >= 3) ||
      (!moved && frames >= 10) ||
      frames >= SETTLE_FRAME_LIMIT
    )
      correct();
    else frame = requestAnimationFrame(watch);
  };

  events.addEventListener("scrollend", onScrollEnd);
  for (const type of READER_SCROLL_INPUT)
    window.addEventListener(type, stop, { capture: true, passive: true });
  frame = requestAnimationFrame(watch);
  return stop;
}

/** Where an in-report jump started: the control, its section and its URL. */
type ReturnPoint = {
  label: string;
  element: HTMLElement;
  href: string;
  /** History entries this component pushed since the jump started. */
  pushes: number;
};

/** Brings the reader back to the exact control that started a jump. */
function restoreOrigin(point: ReturnPoint, done: () => void) {
  if (!point.element.isConnected) {
    done();
    return;
  }
  // Two frames: let a restored tab/section render first. The restored URL's
  // own section scroll is suppressed until this finishes, so it can't compete.
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      done();
      if (!point.element.isConnected) return;
      point.element.focus({ preventScroll: true });
      point.element.scrollIntoView?.({
        block: "center",
        behavior: scrollBehavior(),
      });
    }),
  );
}

function serverLocation() {
  return "";
}

function subscribeViewport(notify: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(TABBED_DEFAULT_QUERY);
  query.addEventListener?.("change", notify);
  return () => query.removeEventListener?.("change", notify);
}

function desktopSnapshot() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia(TABBED_DEFAULT_QUERY).matches
  );
}

function serverDesktopSnapshot() {
  return false;
}

function subscribeToolbar(notify: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(TOOLBAR_QUERY);
  query.addEventListener?.("change", notify);
  return () => query.removeEventListener?.("change", notify);
}

/** The shell's top-bar slot, on screens wide enough to hold the sections. */
function toolbarSlot(): HTMLElement | null {
  if (
    typeof window.matchMedia !== "function" ||
    !window.matchMedia(TOOLBAR_QUERY).matches
  )
    return null;
  return document.querySelector<HTMLElement>(
    "[data-lightbox-shell] [data-shell-toolbar]",
  );
}

function serverToolbarSlot() {
  return null;
}

function nearestScrollport(element: HTMLElement): HTMLElement | null {
  for (
    let parent = element.parentElement;
    parent;
    parent = parent.parentElement
  ) {
    const style = window.getComputedStyle(parent);
    const scrollableOverflow = [style.overflowY, style.overflow].some((value) =>
      ["auto", "scroll", "hidden", "overlay"].includes(value),
    );
    if (scrollableOverflow) {
      return parent;
    }
  }
  return null;
}

/**
 * Measures the shell chrome that can actually cover report scroll targets and
 * returns the scroll-target offset from the scrollport's top edge.
 */
function updateReportLayerOffsets(
  workspace: HTMLElement,
  navRow: HTMLElement,
): number {
  const shell = workspace.closest<HTMLElement>("[data-lightbox-shell]");
  const mobileBar = shell?.querySelector<HTMLElement>("header");
  const mobileBarPosition = mobileBar
    ? window.getComputedStyle(mobileBar).position
    : "static";
  const mobileBarIsSticky =
    mobileBarPosition === "sticky" || mobileBarPosition === "fixed";
  const scrollport = nearestScrollport(workspace);
  const scrollportTop = scrollport
    ? scrollport.getBoundingClientRect().top + scrollport.clientTop
    : 0;
  const mobileBarOverlap =
    mobileBar && mobileBarIsSticky
      ? Math.max(0, mobileBar.getBoundingClientRect().bottom - scrollportTop)
      : 0;
  // A sticky row sits inside its scroll container's padding, while scroll
  // margins are measured from the scrollport edge: count that padding too.
  const scrollportPadding = scrollport
    ? Number.parseFloat(window.getComputedStyle(scrollport).paddingTop) || 0
    : 0;
  // The pinned report title row (data-report-sticky) covers the top too.
  const stickyBar = scrollport?.querySelector<HTMLElement>(
    "[data-report-sticky]",
  );
  const stickyHeight =
    stickyBar && window.getComputedStyle(stickyBar).position === "sticky"
      ? stickyBar.getBoundingClientRect().height
      : 0;
  // A row hosted in the shell's top bar sits outside the report scrollport.
  const navCovers = workspace.contains(navRow);
  const measuredNavHeight = navCovers
    ? navRow.getBoundingClientRect().height || 56
    : 0;
  const targetOffset = Math.max(
    navCovers ? 64 : 16,
    mobileBarOverlap + scrollportPadding + stickyHeight + measuredNavHeight + 8,
  );

  workspace.style.setProperty(
    "--report-nav-sticky-top",
    `${mobileBarOverlap + stickyHeight}px`,
  );
  workspace.style.setProperty(
    "--report-scroll-target-offset",
    `${targetOffset}px`,
  );

  const dock = shell?.querySelector<HTMLElement>(
    '[aria-label="Call audio player"][data-embedded="false"]',
  );
  if (
    shell &&
    window.innerWidth < 900 &&
    window.innerHeight > 560 &&
    dock &&
    window.getComputedStyle(dock).position === "fixed"
  ) {
    const dockTop = dock.getBoundingClientRect().top;
    const bottomClearance = window.innerHeight - dockTop + 12;
    if (Number.isFinite(bottomClearance) && bottomClearance > 12) {
      workspace.style.setProperty(
        "--report-return-bottom",
        `${bottomClearance}px`,
      );
      return targetOffset;
    }
  }
  workspace.style.removeProperty("--report-return-bottom");
  return targetOffset;
}

function renderReportPanels(
  id: string,
  panels: ReportPanel[],
  view: View,
  selected: string,
) {
  return (
    <div className={styles.sections}>
      {panels.map((panel, index) => (
        <section
          key={panel.id}
          id={`${id}-section-${panel.id}`}
          className={styles.section}
          data-report-mode-section={panel.id}
          role={view === "tabs" ? "tabpanel" : "region"}
          aria-labelledby={
            view === "tabs"
              ? `${id}-tab-${panel.id}`
              : `${id}-heading-${panel.id}`
          }
          hidden={view === "tabs" && selected !== panel.id}
          tabIndex={view === "tabs" ? 0 : -1}
        >
          {view === "story" && panel.icon ? (
            <>
              <PartHead
                number={index + 1}
                icon={panel.icon}
                title={panel.label}
                summary={panel.summary ?? ""}
                aside={panel.aside}
                headingId={`${id}-heading-${panel.id}`}
              />
              {panel.content}
            </>
          ) : view === "story" ? (
            <>
              <header className={styles.pillarHead}>
                <span className={styles.pillarNumber} aria-hidden="true">
                  {index + 1}
                </span>
                <div>
                  <h2
                    id={`${id}-heading-${panel.id}`}
                    tabIndex={-1}
                    className={styles.pillarTitle}
                  >
                    {panel.label}
                  </h2>
                  {panel.summary ? (
                    <p className={styles.pillarSubtitle}>{panel.summary}</p>
                  ) : null}
                </div>
              </header>
              {panel.content}
            </>
          ) : view === "prospect" ? (
            <>
              <h2
                id={`${id}-heading-${panel.id}`}
                tabIndex={-1}
                className={styles.visuallyHiddenHeading}
              >
                {panel.label}
              </h2>
              {panel.content}
            </>
          ) : view === "coaching" ? (
            <OperationalPanel
              title={
                <span id={`${id}-heading-${panel.id}`} tabIndex={-1}>
                  {panel.label}
                </span>
              }
              headingLevel="h2"
              // Phones: Coaching's own pillar cards are the frame.
              className={styles.coachingPanel}
              headClassName={styles.coachingPanelHead}
              bodyClassName={styles.coachingPanelBody}
            >
              {panel.content}
            </OperationalPanel>
          ) : view === "tabs" ? (
            <h2
              id={`${id}-heading-${panel.id}`}
              tabIndex={-1}
              className={styles.visuallyHiddenHeading}
            >
              {panel.label}
            </h2>
          ) : (
            <div className={styles.chapterOpener}>
              <div className={styles.chapterHeader}>
                <span className={styles.chapterNumber}>{index + 1}.</span>
                <h2
                  id={`${id}-heading-${panel.id}`}
                  tabIndex={-1}
                  className={styles.chapterTitle}
                >
                  {panel.label}
                </h2>
              </div>
              <div className={styles.chapterRule} aria-hidden="true" />
              <p className={styles.chapterSummary}>
                {panel.summary ?? `${panel.label} report section.`}
              </p>
            </div>
          )}
          {view !== "story" && view !== "coaching" && view !== "prospect" && (
            <div className={styles.reportContent}>{panel.content}</div>
          )}
        </section>
      ))}
    </div>
  );
}

/**
 * Nobody wants the full transcript while reading (AUT-785): Reading leaves it
 * out, and Document keeps it only as the last appendix for print and PDF.
 */
function panelsForView(panels: ReportPanel[], view: View) {
  if (view === "tabs") return panels;
  const rest = panels.filter((panel) => panel.id !== "transcript");
  const transcript = panels.find((panel) => panel.id === "transcript");
  return view === "document" && transcript ? [...rest, transcript] : rest;
}

/** Keeps all real report sections available in a bookmarkable reading, tabbed or document view. */

export function ReportModes({
  label = "Report sections",
  panels: suppliedPanels,
  boundCallId,
  lightSurface = true,
  documentData,
  initialView,
  onSelectEvidence,
  onSelectContextualPlayback,
  structure = "custom",
  fixture = false,
  fixtureLook,
  illustration = null,
  onViewChange,
}: {
  label?: string;
  initialView?: View;
  panels: ReportPanel[];
  /** Keeps the report on the light surface; false follows a dark app theme. */
  lightSurface?: boolean;
  /** Enables view and section bookmarks for this already-bound report. */
  boundCallId?: string;
  /** Optional custom document report data */
  documentData?: DocumentReportData;
  onSelectEvidence?: (evidence: ReportEvidence, title: string) => void;
  onSelectContextualPlayback?: (
    playback: ContextualSourcePlayback,
    title: string,
  ) => void;
  structure?: "custom" | "pillars";
  /** Kept for callers; the 15 Oct Report has no prospect panel yet. */
  prospectControls?: ReactNode;
  /** A fictional fixture: the Report shows its data but reads nothing live. */
  fixture?: boolean;
  /** A fixture's report settings look (a fixture reads no settings); ignored otherwise. */
  fixtureLook?: ReportLook;
  /** The doc's illustrative example (review fixture only): every number fictional. */
  illustration?: XrayView | null;
  /** Told which view shows, so the page header can follow it (owner, 19 Oct). */
  onViewChange?: (view: View) => void;
}) {
  // This workspace's report settings version (Admin, 19 Oct 2026), read once
  // per workspace; version 1, an older server or any failure is today's look.
  const reportSettings = useReportSettings(!fixture);
  const look = (fixture && fixtureLook) || reportLook(reportSettings);
  const allStoryPanels =
    // A guest preview gets the Report too when the caller asks for pillars;
    // its locked items show as "more after you sign in".
    documentData?.report &&
    (!documentData.report.preview || structure === "pillars")
      ? xrayReportPanels(documentData, onSelectEvidence, {
          callId: boundCallId ?? null,
          illustration: fixture ? illustration : null,
          look,
        })
      : [];
  // Owner 19 Oct: Prospect's Information is its own top tab, like Coaching.
  const prospect =
    documentData && structure === "pillars" && !fixture
      ? prospectPanel(documentData, onSelectEvidence, {
          callId: boundCallId ?? null,
        })
      : null;
  const allProspectPanels: ReportPanel[] = prospect ? [prospect] : [];
  const allCoachingPanels: ReportPanel[] =
    documentData?.report && !documentData.report.preview
      ? [
          {
            id: "call-coaching",
            label: DEAL.coachingForCall,
            content: (
              <ReportCallCoaching
                data={documentData}
                callId={boundCallId}
                onSelectEvidence={onSelectEvidence}
                onSelectContextualPlayback={onSelectContextualPlayback}
              />
            ),
          },
        ]
      : [];
  // The Report parts and tabs this version shows (all of them in version 1).
  const {
    story: storyPanels,
    prospect: prospectPanels,
    coaching: coachingPanels,
  } = applyReportSettings(
    {
      story: allStoryPanels,
      prospect: allProspectPanels,
      coaching: allCoachingPanels,
    },
    reportSettings,
  );
  // The six-pillar Report replaces the old supplements; Details keeps the
  // original sections (transcript, raw data) unchanged.
  const enrichedPanels = suppliedPanels;
  const id = useId();
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const navRowRef = useRef<HTMLDivElement | null>(null);
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const skipBookmarkScroll = useRef(false);
  // Cancels a pending jump correction; set while an origin restore owns scrolling.
  const cancelSettle = useRef<(() => void) | null>(null);
  const restoring = useRef(false);
  const [local, setLocal] = useState<
    Address & { preferenceKey?: string | null }
  >({
    view: null,
    section: suppliedPanels[0]?.id ?? "",
  });

  const savedTextSize = useSyncExternalStore(
    subscribeTextSize,
    savedTextSizeSnapshot,
    serverTextSizeSnapshot,
  );
  // A size chosen earlier still applies; browser zoom replaces the old control.
  const textSize = savedTextSize;

  // Server render and hydration read "reading"; a desktop viewport then
  // prefers Tabbed unless the URL or the reader already chose a view.
  const desktop = useSyncExternalStore(
    subscribeViewport,
    desktopSnapshot,
    serverDesktopSnapshot,
  );
  const access = useWorkspaceAccess();
  const preferenceKey =
    access?.authenticated && access.context
      ? `ac:report-view2:${access.context.tenantId}:${access.context.personId}`
      : null;
  const savedView = useSyncExternalStore(
    subscribe,
    () => {
      try {
        const saved = preferenceKey
          ? localStorage.getItem(preferenceKey)
          : null;
        return VIEWS.includes(saved as View) ? (saved as View) : null;
      } catch {
        return null;
      }
    },
    () => null,
  );
  const preferredView: View =
    initialView ??
    savedView ??
    (storyPanels.length ? "story" : desktop ? "tabs" : "reading");
  const slot = useSyncExternalStore(
    subscribeToolbar,
    toolbarSlot,
    serverToolbarSlot,
  );
  const [readingSection, setReadingSection] = useState(
    suppliedPanels[0]?.id ?? "",
  );
  const [returnPoint, setReturnPointState] = useState<ReturnPoint | null>(null);
  const returnRef = useRef<ReturnPoint | null>(null);
  const setReturnPoint = (point: ReturnPoint | null) => {
    returnRef.current = point;
    setReturnPointState(point);
  };
  const location = useSyncExternalStore(
    subscribe,
    browserLocation,
    serverLocation,
  );
  const { pathname, search } = new URL(location, "https://sales-xray.invalid");

  useEffect(() => {
    const workspace = workspaceRef.current;
    const navRow = navRowRef.current;
    if (!workspace || !navRow) return;

    const shell = workspace.closest<HTMLElement>("[data-lightbox-shell]");
    const mobileBar = shell?.querySelector<HTMLElement>("header");
    const scrollport = nearestScrollport(workspace);
    const dock = shell?.querySelector<HTMLElement>(
      '[aria-label="Call audio player"][data-embedded="false"]',
    );
    const update = () => updateReportLayerOffsets(workspace, navRow);
    update();

    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(navRow);
    if (mobileBar) observer?.observe(mobileBar);
    if (scrollport) observer?.observe(scrollport);
    if (dock) observer?.observe(dock);
    const stickyBar = scrollport?.querySelector<HTMLElement>(
      "[data-report-sticky]",
    );
    if (stickyBar) observer?.observe(stickyBar);
    window.addEventListener("resize", update);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [slot]);

  // Browser Back to the URL where a jump started restores that exact place,
  // including an original URL that had no section at all.
  useEffect(() => {
    const settle = cancelSettle;
    const onPopState = () => {
      // Browser chrome can navigate without sending reader-input events to
      // this page. Every history move cancels the previous jump's correction.
      settle.current?.();
      const point = returnRef.current;
      if (!point || window.location.href !== point.href) return;
      returnRef.current = null;
      setReturnPointState(null);
      restoring.current = true;
      restoreOrigin(point, () => {
        restoring.current = false;
      });
    };
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("popstate", onPopState);
      settle.current?.();
    };
  }, []);

  const linked = boundCallId
    ? addressFromSearch(
        search,
        boundCallId,
        documentData?.report &&
          new URLSearchParams(search).get("view") === "document"
          ? DOCUMENT_CHAPTERS.map((chapter) => ({ ...chapter, content: null }))
          : [
              ...enrichedPanels,
              ...storyPanels,
              ...prospectPanels,
              ...coachingPanels,
            ],
        pathname,
      )
    : null;
  const scopedLocal =
    local.preferenceKey === preferenceKey ? local : { ...local, view: null };
  const address = linked ?? scopedLocal;
  const requestedView: View = linked
    ? (linked.view ?? preferredView)
    : (scopedLocal.view ?? preferredView);
  // 16 Oct owner: the new Report replaces the old views on every report that
  // has it. No menu, default or saved choice leads to Details, Reading or
  // Document any more; only an explicit link to one (print and Word use the
  // Document link) still opens it. Review fixtures keep demoing them.
  const legacy = (value: View | null | undefined) =>
    value === "reading" || value === "tabs" || value === "document";
  const linkedLegacy =
    legacy(linked?.view) || (fixture && legacy(requestedView));
  const view: View = storyPanels.length
    ? requestedView === "coaching" && coachingPanels.length
      ? "coaching"
      : requestedView === "prospect" && prospectPanels.length
        ? "prospect"
        : linkedLegacy
          ? requestedView
          : "story"
    : (requestedView === "story" && !storyPanels.length) ||
        (requestedView === "coaching" && !coachingPanels.length) ||
        (requestedView === "prospect" && !prospectPanels.length)
      ? "reading"
      : requestedView;
  const panels =
    view === "story"
      ? storyPanels
      : view === "coaching"
        ? coachingPanels
        : view === "prospect"
          ? prospectPanels
          : enrichedPanels;

  const activePanels: ReportPanel[] =
    view === "document" && documentData?.report
      ? DOCUMENT_CHAPTERS.map((chapter) => ({ ...chapter, content: null }))
      : panelsForView(panels, view);

  const selected = activePanels.some((panel) => panel.id === address.section)
    ? address.section
    : activePanels[0]?.id;
  useEffect(() => {
    onViewChange?.(view);
  }, [onViewChange, view]);
  const printView =
    view === "document" && new URLSearchParams(search).get("print") === "1";
  const currentSection = activePanels.some(
    (panel) => panel.id === readingSection,
  )
    ? view === "tabs"
      ? selected
      : readingSection
    : selected;

  useEffect(() => {
    if (!selected) return;
    const update = () => {
      const workspace = workspaceRef.current;
      const scroller = workspace ? reportScroller(workspace) : null;
      const scrollportTop =
        scroller &&
        scroller !== document.scrollingElement &&
        scroller !== document.documentElement
          ? scroller.getBoundingClientRect().top + scroller.clientTop
          : 0;
      const offset = workspace
        ? Number.parseFloat(
            workspace.style.getPropertyValue("--report-scroll-target-offset"),
          ) || 0
        : 0;
      // A chapter positioned below sticky chrome is the current chapter,
      // even when that clearance lies below the usual reading line.
      const readingLine = Math.max(
        Math.min(180, window.innerHeight * 0.4),
        scrollportTop + offset + 2,
      );
      let current = activePanels[0]?.id ?? "";
      let foundHeading = false;
      for (const panel of activePanels) {
        const heading = document.getElementById(`${id}-heading-${panel.id}`);
        const bounds = heading?.getBoundingClientRect();
        if (bounds && bounds.height > 0) foundHeading = true;
        if (bounds && bounds.height > 0 && bounds.top <= readingLine)
          current = panel.id;
      }
      if (!foundHeading) return;
      // At the very end the last chapters cannot reach the reading line:
      // the last one whose heading is on screen is the one being read.
      const atEnd = scroller
        ? scroller.scrollTop + scroller.clientHeight >=
          scroller.scrollHeight - 4
        : false;
      if (atEnd && scroller && scroller.scrollTop > 0) {
        const bottom =
          scroller === document.scrollingElement ||
          scroller === document.documentElement
            ? window.innerHeight
            : scroller.getBoundingClientRect().bottom;
        const visible = activePanels.filter((panel) => {
          const top = document
            .getElementById(`${id}-heading-${panel.id}`)
            ?.getBoundingClientRect().top;
          return top !== undefined && top >= scrollportTop && top < bottom - 48;
        });
        // A chapter the reader jumped to stays lit while it is on screen.
        if (visible.some((panel) => panel.id === selected)) current = selected;
        else if (visible.length) current = visible[visible.length - 1].id;
      }
      setReadingSection((previous) =>
        previous === current ? previous : current,
      );
    };
    update();
    document.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      document.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [id, activePanels, selected]);

  useEffect(() => {
    if (!linked?.section || !new URLSearchParams(search).has("section")) return;
    // Returning to a jump's origin restores that exact control instead.
    if (restoring.current) return;
    if (skipBookmarkScroll.current) {
      skipBookmarkScroll.current = false;
      return;
    }
    const frame = requestAnimationFrame(() => {
      if (restoring.current) return;
      setReadingSection(linked.section);
      document
        .getElementById(`${id}-heading-${linked.section}`)
        ?.scrollIntoView?.({ block: "start", behavior: scrollBehavior() });
    });
    return () => cancelAnimationFrame(frame);
  }, [id, linked?.section, search]);

  // The toolbar's highlight glides to the current section.
  useLayoutEffect(() => {
    const list = navRowRef.current?.querySelector<HTMLElement>(
      "[data-report-sections]",
    );
    if (!list) return;
    const place = () => {
      // A row that scrolls sideways fades at its edge, so a name at the edge
      // reads as "more this way", never as a cut word.
      list.toggleAttribute(
        "data-overflow",
        list.scrollWidth > list.clientWidth + 1,
      );
      const current = list.querySelector<HTMLElement>(
        '[aria-selected="true"], [aria-current="location"]',
      );
      if (!current) {
        list.style.removeProperty("--pill-w");
        return;
      }
      list.style.setProperty("--pill-x", `${current.offsetLeft}px`);
      list.style.setProperty("--pill-w", `${current.offsetWidth}px`);
      // On narrow screens the row scrolls sideways: keep the current one in view.
      if (list.scrollWidth > list.clientWidth + 1) {
        const left =
          current.offsetParent === list
            ? current.offsetLeft
            : current.offsetLeft - list.offsetLeft;
        if (
          left < list.scrollLeft ||
          left + current.offsetWidth > list.scrollLeft + list.clientWidth
        )
          list.scrollTo?.({
            left: Math.max(0, left - 16),
            behavior: scrollBehavior(),
          });
      }
    };
    place();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(place);
    observer.observe(list);
    for (const child of Array.from(list.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [currentSection, view, slot]);

  /** Moves to a destination with motion (unless reduced) and a brief arrival cue. */
  function arriveAt(destination: HTMLElement | null | undefined) {
    if (!destination) return;
    cancelSettle.current?.();
    cancelSettle.current = null;
    const workspace = workspaceRef.current;
    const navRow = navRowRef.current;
    // Measure now: a viewport or view change may not have reached the observer.
    if (workspace && navRow) updateReportLayerOffsets(workspace, navRow);
    // Focus must land on the real target, even a plain container.
    if (!destination.hasAttribute("tabindex") && destination.tabIndex < 0)
      destination.setAttribute("tabindex", "-1");
    destination.focus({ preventScroll: true });
    const scroller = workspace ? reportScroller(workspace) : null;
    const startTop = scroller?.scrollTop ?? 0;
    destination.scrollIntoView?.({
      block: "start",
      behavior: scrollBehavior(),
    });
    destination.setAttribute("data-arrived", "true");
    window.setTimeout(() => destination.removeAttribute("data-arrived"), 1600);
    if (workspace && navRow && scroller)
      cancelSettle.current = settleJump(destination, scroller, startTop, () =>
        updateReportLayerOffsets(workspace, navRow),
      );
  }

  function navigate(
    section: string,
    nextView: View = view,
    focus = false,
    history: "push" | "replace" = "push",
  ) {
    const destinations =
      nextView === "story"
        ? storyPanels
        : nextView === "coaching"
          ? coachingPanels
          : nextView === "prospect"
            ? prospectPanels
            : nextView === "document" && documentData?.report
              ? DOCUMENT_CHAPTERS
              : enrichedPanels;
    if (!destinations.some((panel) => panel.id === section)) return;
    if (boundCallId) {
      if (!UUID.test(boundCallId)) return;
      const current = new URL(window.location.href);
      const pathCallId = callIdFromPath(current.pathname);
      if (pathCallId !== null && pathCallId !== boundCallId) return;
      const calls = current.searchParams.getAll("call");
      if (calls.length > 1 || (calls.length === 1 && calls[0] !== boundCallId))
        return;
      // On /analysis/calls/<id> the path already names the call.
      if (callIdFromPath(current.pathname) === boundCallId)
        current.searchParams.delete("call");
      else current.searchParams.set("call", boundCallId);
      current.searchParams.delete("new");
      current.searchParams.set("view", nextView);
      current.searchParams.set("section", section);
      const target = `${current.pathname}?${current.searchParams.toString()}${current.hash}`;
      const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      const changesLocation = target !== here;
      // Section jumps and tab changes are history entries, so browser Back
      // returns to the previous section; view toggles only replace the entry.
      const sectionChanges =
        current.searchParams.get("section") !==
        new URLSearchParams(window.location.search).get("section");
      if (changesLocation && sectionChanges && history !== "replace") {
        window.history.pushState(window.history.state, "", target);
        if (returnRef.current) returnRef.current.pushes += 1;
      } else if (changesLocation)
        window.history.replaceState(window.history.state, "", target);
      skipBookmarkScroll.current = changesLocation;
      window.dispatchEvent(new Event(CHANGE));
    } else setLocal({ view: nextView, section, preferenceKey });
    setReadingSection(section);
    if (focus) {
      requestAnimationFrame(() =>
        arriveAt(document.getElementById(`${id}-heading-${section}`)),
      );
    }
  }

  /** Remembers where a jump started so the reader can return to it. */
  function rememberOrigin() {
    const origin =
      document.activeElement instanceof HTMLElement &&
      document.activeElement !== document.body
        ? document.activeElement
        : document.getElementById(`${id}-heading-${currentSection}`);
    const originSection =
      origin
        ?.closest<HTMLElement>("[data-report-mode-section]")
        ?.getAttribute("data-report-mode-section") ?? currentSection;
    const originLabel = activePanels.find(
      (panel) => panel.id === originSection,
    )?.label;
    if (origin && originLabel)
      setReturnPoint({
        label: originLabel,
        element: origin,
        href: window.location.href,
        pushes: 0,
      });
  }

  function navigateToReport(section: string, reviewPoint?: string) {
    rememberOrigin();
    navigate(section);
    requestAnimationFrame(() => {
      const target = reviewPoint
        ? Array.from(
            document.querySelectorAll<HTMLElement>("[data-review-point]"),
          ).find((element) => element.dataset.reviewPoint === reviewPoint)
        : null;
      if (target instanceof HTMLDetailsElement) target.open = true;
      arriveAt(target ?? document.getElementById(`${id}-heading-${section}`));
    });
  }

  function returnToOrigin() {
    const point = returnRef.current;
    if (!point) return;
    cancelSettle.current?.();
    cancelSettle.current = null;
    // Exactly one entry was pushed for this jump: undo it, so the origin URL
    // (even one without a section) and browser history stay truthful. The
    // popstate listener restores focus and position.
    if (
      boundCallId &&
      point.pushes === 1 &&
      window.location.href !== point.href
    ) {
      window.history.back();
      return;
    }
    setReturnPoint(null);
    if (!point.element.isConnected) return;
    restoring.current = true;
    if (boundCallId && window.location.href !== point.href) {
      window.history.replaceState(window.history.state, "", point.href);
      window.dispatchEvent(new Event(CHANGE));
    } else {
      const section = point.element
        .closest<HTMLElement>("[data-report-mode-section]")
        ?.getAttribute("data-report-mode-section");
      if (section) setLocal((previous) => ({ ...previous, section }));
    }
    restoreOrigin(point, () => {
      restoring.current = false;
    });
  }

  function changeView(nextView: View) {
    const destinations =
      nextView === "story"
        ? storyPanels
        : nextView === "coaching"
          ? coachingPanels
          : nextView === "prospect"
            ? prospectPanels
            : nextView === "document" && documentData?.report
              ? DOCUMENT_CHAPTERS
              : enrichedPanels;
    const origin = view !== "tabs" ? currentSection : selected;
    const section = destinations.some((panel) => panel.id === origin)
      ? origin
      : destinations[0]?.id;
    if (section && nextView !== view) {
      const page = (value: View) =>
        value === "story" || value === "prospect" || value === "coaching";
      if (page(nextView) && page(view)) {
        // Report, Prospect and Coaching are pages (owner, 19 Oct): a switch
        // opens the new one at its top, title in view, with no glide.
        navigate(section, nextView, false, "replace");
        requestAnimationFrame(() => {
          const workspace = workspaceRef.current;
          const scroller = workspace ? reportScroller(workspace) : null;
          scroller?.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
          const heading = document.getElementById(`${id}-heading-${section}`);
          if (
            heading &&
            heading.tabIndex < 0 &&
            !heading.hasAttribute("tabindex")
          )
            heading.setAttribute("tabindex", "-1");
          heading?.focus({ preventScroll: true });
        });
      } else navigate(section, nextView, true, "replace");
      if (preferenceKey) {
        try {
          localStorage.setItem(preferenceKey, nextView);
        } catch {}
        window.dispatchEvent(new Event(CHANGE));
      }
    }
  }

  // A pillar's "Coaching for this call" asks for the Coaching view.
  useEffect(() => {
    const open = (event: Event) => {
      const next = (event as CustomEvent<unknown>).detail;
      if (VIEWS.includes(next as View)) changeView(next as View);
    };
    window.addEventListener(OPEN_VIEW, open);
    return () => window.removeEventListener(OPEN_VIEW, open);
  });

  if (!activePanels.length) return null;

  // The Report and its Coaching are the two views people use; Document and
  // Details wait behind "More views" (the current one stays in the row).
  type ViewChoice = readonly [View, string, string, LucideIcon];
  const primaryViews: ViewChoice[] = storyPanels.length
    ? [
        ["story", VIEWS_COPY.report.text, VIEWS_COPY.report.hint, FileText],
        ...(prospectPanels.length
          ? [
              [
                "prospect",
                VIEWS_COPY.prospect.text,
                VIEWS_COPY.prospect.hint,
                UserRound,
              ] as const,
            ]
          : []),
        ...(coachingPanels.length
          ? [
              [
                "coaching",
                VIEWS_COPY.coaching.text,
                VIEWS_COPY.coaching.hint,
                Lightbulb,
              ] as const,
            ]
          : []),
        ...(fixture && view === "tabs"
          ? [
              [
                "tabs",
                VIEWS_COPY.details.text,
                VIEWS_COPY.details.hint,
                PanelsTopLeft,
              ] as const,
            ]
          : fixture && view === "document"
            ? [
                [
                  "document",
                  VIEWS_COPY.document.text,
                  VIEWS_COPY.document.hint,
                  BookOpen,
                ] as const,
              ]
            : []),
      ]
    : [
        ["reading", "Reading view", "Reading view", BookOpen],
        ["tabs", "Tabbed view", "Tabbed view", PanelsTopLeft],
        ["document", "Document view", "Document view", FileText],
      ];
  // The old Details and Document views are gone where the new Report exists
  // (review fixtures still offer them).
  const moreViews: ViewChoice[] =
    storyPanels.length && fixture
      ? (
          [
            [
              "document",
              VIEWS_COPY.document.menu,
              VIEWS_COPY.document.hint,
              BookOpen,
            ],
            [
              "tabs",
              VIEWS_COPY.details.menu,
              VIEWS_COPY.details.hint,
              PanelsTopLeft,
            ],
          ] as const
        ).filter(([value]) => value !== view)
      : [];

  // One horizontal row: section tabs (Tabbed) or section links (Reading/Document),
  // with the view choice at its trailing edge. Wide screens host it in the
  // shell's top bar; otherwise it sticks to the top of the report.
  const navigation = (
    <div
      ref={navRowRef}
      className={styles.navRow}
      data-report-nav
      data-placement={slot ? "toolbar" : undefined}
      data-report-print={printView || undefined}
    >
      {view === "tabs" && (
        <nav
          className={styles.tabNavigation}
          role="tablist"
          aria-label={label}
          data-report-sections
        >
          {activePanels.map((panel, index) => (
            <button
              key={panel.id}
              ref={(element) => {
                tabButtons.current[index] = element;
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${panel.id}`}
              aria-controls={`${id}-section-${panel.id}`}
              aria-label={panel.label}
              title={panel.label}
              aria-selected={selected === panel.id}
              tabIndex={selected === panel.id ? 0 : -1}
              onClick={() => navigate(panel.id, "tabs")}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % activePanels.length
                    : event.key === "ArrowLeft"
                      ? (index + activePanels.length - 1) % activePanels.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? activePanels.length - 1
                          : null;
                if (next === null) return;
                event.preventDefault();
                navigate(activePanels[next].id, "tabs");
                tabButtons.current[next]?.focus();
              }}
            >
              <SectionIcon id={panel.id} />
              <span>{panel.compactLabel ?? panel.label}</span>
            </button>
          ))}
        </nav>
      )}
      {(view === "reading" ||
        view === "document" ||
        view === "story" ||
        view === "coaching") && (
        <nav
          className={styles.contents}
          aria-label={label}
          data-report-sections
        >
          {activePanels.map((panel) => (
            <a
              key={panel.id}
              href={
                boundCallId
                  ? `?call=${encodeURIComponent(boundCallId)}&view=${view}&section=${encodeURIComponent(panel.id)}`
                  : `#${id}-section-${panel.id}`
              }
              aria-current={
                currentSection === panel.id ? "location" : undefined
              }
              aria-label={panel.label}
              title={panel.label}
              onClick={(event) => {
                if (
                  event.metaKey ||
                  event.ctrlKey ||
                  event.shiftKey ||
                  event.altKey
                )
                  return;
                event.preventDefault();
                navigate(panel.id, view, true);
              }}
            >
              <SectionIcon id={panel.id} pillar={view === "story"} />
              <span className={styles.fullLabel}>{panel.label}</span>
              <span className={styles.compactLabel}>
                {panel.compactLabel ?? panel.label}
              </span>
            </a>
          ))}
        </nav>
      )}
      <div
        className={styles.toolbar}
        role="group"
        aria-label={`${label} view`}
        data-labelled={storyPanels.length ? "" : undefined}
      >
        {primaryViews.map(([value, text, hint, Icon]) => (
          <button
            key={value}
            type="button"
            title={hint}
            aria-label={hint}
            aria-pressed={view === value}
            onClick={() => changeView(value)}
          >
            <Icon aria-hidden="true" />
            <span className={styles.toolbarLabel}>{text}</span>
          </button>
        ))}
        {moreViews.length ? (
          <details
            className={styles.moreViews}
            onKeyDown={(event) => {
              if (event.key !== "Escape" || !event.currentTarget.open) return;
              event.preventDefault();
              event.currentTarget.open = false;
              event.currentTarget.querySelector("summary")?.focus();
            }}
          >
            <summary aria-label={VIEWS_COPY.more} title={VIEWS_COPY.more}>
              <Ellipsis aria-hidden="true" />
            </summary>
            <div className={styles.moreViewsMenu}>
              {moreViews.map(([value, text, hint, Icon]) => (
                <button
                  key={value}
                  type="button"
                  title={hint}
                  aria-label={hint}
                  aria-pressed={false}
                  onClick={(event) => {
                    event.currentTarget
                      .closest("details")
                      ?.removeAttribute("open");
                    changeView(value);
                  }}
                >
                  <Icon aria-hidden="true" />
                  <span>{text}</span>
                </button>
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </div>
  );

  const report = (
    <div
      ref={workspaceRef}
      className={styles.workspace}
      data-report-modes
      data-report-structure={structure}
      data-lx-surface={
        lightSurface || view === "document" ? "light" : undefined
      }
      data-view={view}
      data-report-section={currentSection}
      data-text-size={textSize}
      data-report-print={printView || undefined}
    >
      {slot ? createPortal(navigation, slot) : navigation}
      <div className={styles.layout}>
        <ReportReadingProvider
          reading={view === "reading"}
          inline
          navigate={navigateToReport}
        >
          {/* Coaching is one focused page, and the Report is only its three
              parts (15 Oct doc): the header's call map waits here, hidden. */}
          {view === "coaching" ||
          view === "prospect" ||
          (view === "story" && storyPanels.length) ? (
            <div data-report-map-slot hidden />
          ) : null}
          <div data-reading-panels hidden={view === "document"}>
            {renderReportPanels(
              view === "document" ? `${id}-source` : id,
              panelsForView(panels, view === "document" ? "tabs" : view),
              view === "document" ? "tabs" : view,
              selected,
            )}
          </div>
          {view === "document" && (
            <ReportDocument
              data={documentData}
              id={id}
              textSize={textSize}
              section={selected}
              callId={boundCallId ?? null}
              onSelect={onSelectEvidence}
            />
          )}
        </ReportReadingProvider>
      </div>
      {returnPoint && (
        <div className={styles.returnBar} data-report-return>
          <button
            type="button"
            className={styles.returnButton}
            onClick={returnToOrigin}
          >
            <Undo2 aria-hidden="true" />
            {backTo(returnPoint.label)}
          </button>
          <button
            type="button"
            className={styles.returnDismiss}
            aria-label={NAV.hideBack}
            onClick={() => setReturnPoint(null)}
          >
            <X aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
  // Fixtures keep the outcome in memory; a guest preview reads none.
  const shown = (
    <ReportLookContext.Provider value={look}>
      {report}
    </ReportLookContext.Provider>
  );
  return fixture && !documentData?.report?.preview ? (
    <FixtureCallOutcomeProvider>{shown}</FixtureCallOutcomeProvider>
  ) : (
    <CallOutcomeProvider
      callId={
        documentData?.report && !documentData.report.preview && !fixture
          ? boundCallId
          : null
      }
    >
      {shown}
    </CallOutcomeProvider>
  );
}
