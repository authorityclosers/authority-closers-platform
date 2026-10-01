"use client";

import { callIdFromPath } from "./analysis-routes";
import {
  Radar,
  AudioLines,
  BookOpen,
  ChartNoAxesColumnIncreasing,
  FileText,
  Lightbulb,
  PanelsTopLeft,
  TableProperties,
  Undo2,
  UserRound,
  X,
  Printer,
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
import { ReportReadingProvider } from "./report-reading-context";
import styles from "./report-modes.module.css";

export type ReportPanel = {
  id: string;
  label: string;
  compactLabel?: string;
  content: ReactNode;
  summary?: string;
};

export type DocumentReportData = {
  title?: string;
  workspaceName?: string;
  repName?: string;
  prospectName?: string;
  callType?: string;
  callDate?: string;
  callLength?: string;
  analysedDate?: string;
  analysisBasis?: {
    recordingLength?: string;
    transcriptSource?: string;
    analysisVersion?: string;
  };
};

type View = "reading" | "tabs" | "document";
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
};

function SectionIcon({ id }: { id: string }) {
  const Icon = sectionIcons[id] ?? FileText;
  return <Icon className={styles.sectionIcon} aria-hidden="true" />;
}

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  window.addEventListener(CHANGE, notify);
  return () => {
    window.removeEventListener("popstate", notify);
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
    views.length === 1 &&
    (views[0] === "reading" || views[0] === "tabs" || views[0] === "document")
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

const defaultSummaries: Record<string, string> = {
  overview:
    "High-level diagnostic summary, key observations and critical conversation shift.",
  scorecard: "Capability observations and supporting source evidence.",
  skills: "Capability observations and supporting source evidence.",
  strengths:
    "Observed strengths demonstrated during the conversation with supporting evidence.",
  prospect:
    "Prospect profile, buyer readiness, business context and stakeholder dynamics.",
  improvements:
    "High-priority development areas, coaching interventions and transcript quotes.",
  signals:
    "Buyer engagement markers, pacing indicators and interaction dynamics.",
  "strength-gap": "Key competitive edge contrasted with the primary skill gap.",
  moments:
    "Key conversational turning points, buyer signals, and coaching moments.",
  "next-call-plan":
    "Concrete action items, coaching focus and talking tracks for the next call.",
  transcript:
    "Complete timestamped dialogue transcript with speaker diarization.",
  "raw-data":
    "Structured analysis payload, telemetry data and technical audit trace.",
};

function renderDocumentView(
  id: string,
  panels: ReportPanel[],
  docData?: DocumentReportData,
) {
  const title =
    docData?.title ??
    ([docData?.repName, docData?.prospectName].filter(Boolean).join(" — ") ||
      "Sales Xray call") + " report";
  const basis = docData?.analysisBasis;
  const printRep = JSON.stringify((docData?.repName ?? "").replace(/\s/g, " "))
    .replaceAll("<", "\\3c ")
    .replaceAll(">", "\\3e ");

  return (
    <div className={styles.documentContainer}>
      <style>{`@page { @top-right { content: ${printRep}; font: 8pt sans-serif; } }
        @page :first { @top-right { content: none; } }`}</style>
      <div className={styles.documentActions}>
        <button
          type="button"
          className={styles.docBtnPrimary}
          onClick={() => window.print()}
        >
          <Printer aria-hidden="true" />
          <span>Print / Save PDF</span>
        </button>
        <span className={styles.documentActionsNote}>
          A4 portrait · 210×297 mm
        </span>
      </div>
      <div className={styles.documentPages}>
        {panels.map((panel, index) => (
          <article
            className={styles.documentPage}
            data-document-page
            key={panel.id}
          >
            {index === 0 ? (
              <>
                {docData?.workspaceName && (
                  <div className={styles.docKicker}>
                    {docData.workspaceName}
                  </div>
                )}
                {(docData?.callType || docData?.callDate) && (
                  <div className={styles.docSubtitle}>
                    {[docData.callType, docData.callDate]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
                <h1 className={styles.docTitle}>{title}</h1>
                {(docData?.callLength || docData?.analysedDate) && (
                  <div className={styles.docMetaLine}>
                    {[
                      docData.callLength && `Call length ${docData.callLength}`,
                      docData.analysedDate &&
                        `Analysed ${docData.analysedDate}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
                {basis && (
                  <aside
                    className={styles.docBasisCallout}
                    aria-label="Analysis basis"
                  >
                    <div className={styles.docBasisLabel}>Analysis basis</div>
                    {basis.recordingLength && (
                      <p className={styles.docBasisText}>
                        Recording length: {basis.recordingLength}
                      </p>
                    )}
                    {basis.transcriptSource && (
                      <p className={styles.docBasisText}>
                        Transcript: {basis.transcriptSource}
                      </p>
                    )}
                    {basis.analysisVersion && (
                      <p className={styles.docBasisText}>
                        Analysis version: {basis.analysisVersion}
                      </p>
                    )}
                  </aside>
                )}
              </>
            ) : (
              <div className={styles.docRunningHeader}>
                <span>Authority Closers — Sales Xray call report</span>
                {docData?.repName && <span>{docData.repName}</span>}
              </div>
            )}
            <section
              className={styles.docSection}
              data-report-mode-section={panel.id}
              aria-labelledby={`${id}-heading-${panel.id}`}
            >
              <div className={styles.docSectionHeader}>
                <span className={styles.docSectionNumber}>{index + 1}.</span>
                <h2
                  id={`${id}-heading-${panel.id}`}
                  tabIndex={-1}
                  className={styles.docSectionTitle}
                >
                  {panel.label}
                </h2>
              </div>
              <div className={styles.chapterRule} aria-hidden="true" />
              <div className={styles.docContent}>{panel.content}</div>
            </section>
            <div className={styles.docFooter}>
              Page {index + 1} of {panels.length}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

/** Keeps all real report sections available in a bookmarkable reading, tabbed or document view. */

export function ReportModes({
  label = "Report sections",
  panels,
  boundCallId,
  lightSurface = true,
  documentData,
}: {
  label?: string;
  panels: ReportPanel[];
  /** Keeps the report on the light surface; false follows a dark app theme. */
  lightSurface?: boolean;
  /** Enables view and section bookmarks for this already-bound report. */
  boundCallId?: string;
  /** Optional custom document report data */
  documentData?: DocumentReportData;
}) {
  const id = useId();
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const navRowRef = useRef<HTMLDivElement | null>(null);
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const skipBookmarkScroll = useRef(false);
  // Cancels a pending jump correction; set while an origin restore owns scrolling.
  const cancelSettle = useRef<(() => void) | null>(null);
  const restoring = useRef(false);
  const [local, setLocal] = useState<Address>({
    view: null,
    section: panels[0]?.id ?? "",
  });

  const savedTextSize = useSyncExternalStore(
    subscribeTextSize,
    savedTextSizeSnapshot,
    serverTextSizeSnapshot,
  );
  const [localTextSize, setLocalTextSize] = useState<TextSize | null>(null);
  const textSize = localTextSize ?? savedTextSize;
  const changeTextSize = (nextSize: TextSize) => {
    setLocalTextSize(nextSize);
    try {
      localStorage.setItem(TEXT_SIZE_KEY, nextSize);
      window.dispatchEvent(new Event(TEXT_SIZE_CHANGE));
    } catch {
      // Private browsing can deny storage; sizing still works in this view.
    }
  };

  // Server render and hydration read "reading"; a desktop viewport then
  // prefers Tabbed unless the URL or the reader already chose a view.
  const desktop = useSyncExternalStore(
    subscribeViewport,
    desktopSnapshot,
    serverDesktopSnapshot,
  );
  const preferredView: View = desktop ? "tabs" : "reading";
  const slot = useSyncExternalStore(
    subscribeToolbar,
    toolbarSlot,
    serverToolbarSlot,
  );
  const [readingSection, setReadingSection] = useState(panels[0]?.id ?? "");
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
    ? addressFromSearch(search, boundCallId, panels, pathname)
    : null;
  const address = linked ?? local;
  const selected = panels.some((panel) => panel.id === address.section)
    ? address.section
    : panels[0]?.id;
  const view: View = linked
    ? (linked.view ?? preferredView)
    : (local.view ?? preferredView);
  const currentSection = panels.some((panel) => panel.id === readingSection)
    ? view === "tabs"
      ? selected
      : readingSection
    : selected;

  useEffect(() => {
    if (!selected) return;
    const update = () => {
      const readingLine = Math.min(180, window.innerHeight * 0.4);
      let current = panels[0]?.id ?? "";
      let foundHeading = false;
      for (const panel of panels) {
        const heading = document.getElementById(`${id}-heading-${panel.id}`);
        const bounds = heading?.getBoundingClientRect();
        if (bounds && bounds.height > 0) foundHeading = true;
        if (bounds && bounds.height > 0 && bounds.top <= readingLine)
          current = panel.id;
      }
      if (!foundHeading) return;
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
  }, [id, panels, selected]);

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
      const current = list.querySelector<HTMLElement>(
        '[aria-selected="true"], [aria-current="location"]',
      );
      if (!current) {
        list.style.removeProperty("--pill-w");
        return;
      }
      list.style.setProperty("--pill-x", `${current.offsetLeft}px`);
      list.style.setProperty("--pill-w", `${current.offsetWidth}px`);
    };
    place();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(place);
    observer.observe(list);
    for (const child of Array.from(list.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [currentSection, view, slot]);

  if (!panels.length) return null;

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

  function navigate(section: string, nextView: View = view, focus = false) {
    if (!panels.some((panel) => panel.id === section)) return;
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
      if (changesLocation && sectionChanges) {
        window.history.pushState(window.history.state, "", target);
        if (returnRef.current) returnRef.current.pushes += 1;
      } else if (changesLocation)
        window.history.replaceState(window.history.state, "", target);
      skipBookmarkScroll.current = changesLocation;
      window.dispatchEvent(new Event(CHANGE));
    } else setLocal({ view: nextView, section });
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
    const originLabel = panels.find(
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
    const section =
      view !== "tabs" ? currentSection : (selected ?? panels[0]?.id);
    if (section) navigate(section, nextView);
  }

  // One horizontal row: section tabs (Tabbed) or section links (Reading/Document),
  // with the view choice at its trailing edge. Wide screens host it in the
  // shell's top bar; otherwise it sticks to the top of the report.
  const navigation = (
    <div
      ref={navRowRef}
      className={styles.navRow}
      data-report-nav
      data-placement={slot ? "toolbar" : undefined}
    >
      {view === "tabs" && (
        <nav
          className={styles.tabNavigation}
          role="tablist"
          aria-label={label}
          data-report-sections
        >
          {panels.map((panel, index) => (
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
                    ? (index + 1) % panels.length
                    : event.key === "ArrowLeft"
                      ? (index + panels.length - 1) % panels.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? panels.length - 1
                          : null;
                if (next === null) return;
                event.preventDefault();
                navigate(panels[next].id, "tabs");
                tabButtons.current[next]?.focus();
              }}
            >
              <SectionIcon id={panel.id} />
              <span>{panel.compactLabel ?? panel.label}</span>
            </button>
          ))}
        </nav>
      )}
      {(view === "reading" || view === "document") && (
        <nav
          className={styles.contents}
          aria-label={label}
          data-report-sections
        >
          {panels.map((panel) => (
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
              <SectionIcon id={panel.id} />
              <span className={styles.fullLabel}>{panel.label}</span>
              <span className={styles.compactLabel}>
                {panel.compactLabel ?? panel.label}
              </span>
            </a>
          ))}
        </nav>
      )}
      <div className={styles.toolbar} role="group" aria-label={`${label} view`}>
        <button
          type="button"
          title="Reading view"
          aria-pressed={view === "reading"}
          onClick={() => changeView("reading")}
        >
          <BookOpen aria-hidden="true" />
          <span className={styles.toolbarLabel}>Reading view</span>
        </button>
        <button
          type="button"
          title="Tabbed view"
          aria-pressed={view === "tabs"}
          onClick={() => changeView("tabs")}
        >
          <PanelsTopLeft aria-hidden="true" />
          <span className={styles.toolbarLabel}>Tabbed view</span>
        </button>
        <button
          type="button"
          title="Document view"
          aria-pressed={view === "document"}
          onClick={() => changeView("document")}
        >
          <FileText aria-hidden="true" />
          <span className={styles.toolbarLabel}>Document view</span>
        </button>
      </div>
      <div className={styles.textSizeGroup} role="group" aria-label="Text size">
        <button
          type="button"
          title="Default text size (100%)"
          aria-label="Text size 100%"
          aria-pressed={textSize === "100"}
          onClick={() => changeTextSize("100")}
        >
          A−
        </button>
        <button
          type="button"
          title="Medium text size (112.5%)"
          aria-label="Text size 112.5%"
          aria-pressed={textSize === "112.5"}
          onClick={() => changeTextSize("112.5")}
        >
          A
        </button>
        <button
          type="button"
          title="Large text size (125%)"
          aria-label="Text size 125%"
          aria-pressed={textSize === "125"}
          onClick={() => changeTextSize("125")}
        >
          A+
        </button>
      </div>
    </div>
  );

  return (
    <div
      ref={workspaceRef}
      className={styles.workspace}
      data-report-modes
      data-lx-surface={
        lightSurface || view === "document" ? "light" : undefined
      }
      data-view={view}
      data-report-section={currentSection}
      data-text-size={textSize}
      data-report-print={
        new URLSearchParams(search).get("print") === "1" || undefined
      }
    >
      {slot ? createPortal(navigation, slot) : navigation}
      <div className={styles.layout}>
        {view === "document" ? (
          <ReportReadingProvider reading inline navigate={navigateToReport}>
            {renderDocumentView(id, panels, documentData)}
          </ReportReadingProvider>
        ) : (
          <ReportReadingProvider
            reading={view === "reading"}
            inline
            navigate={navigateToReport}
          >
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
                  {/* In Tabbed view the selected tab already names the section;
                      the heading stays for assistive tech and focus targets. */}
                  {view === "tabs" ? (
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
                        <span className={styles.chapterNumber}>
                          {index + 1}.
                        </span>
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
                        {panel.summary ??
                          defaultSummaries[panel.id] ??
                          `${panel.label} analysis and observations.`}
                      </p>
                    </div>
                  )}
                  {panel.content}
                </section>
              ))}
            </div>
          </ReportReadingProvider>
        )}
      </div>
      {returnPoint && (
        <div className={styles.returnBar} data-report-return>
          <button
            type="button"
            className={styles.returnButton}
            onClick={returnToOrigin}
          >
            <Undo2 aria-hidden="true" />
            Back to {returnPoint.label}
          </button>
          <button
            type="button"
            className={styles.returnDismiss}
            aria-label="Dismiss return shortcut"
            onClick={() => setReturnPoint(null)}
          >
            <X aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
