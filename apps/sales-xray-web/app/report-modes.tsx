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
  FileDown,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
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
  scorecard:
    "Core capability ratings, evaluation breakdown and overall competency level.",
  skills:
    "Capability dimensions, behavioral scoring and consultative competency assessment.",
  strengths:
    "Observed strengths demonstrated during the conversation with supporting evidence.",
  prospect:
    "Prospect profile, buyer readiness, business context and stakeholder dynamics.",
  improvements:
    "High-priority development areas, coaching interventions and transcript quotes.",
  signals:
    "Buyer engagement markers, pacing indicators and interaction dynamics.",
  "strength-gap":
    "Key competitive edge contrasted with the primary skill gap.",
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
  const repName = docData?.repName ?? "Aarav Sharma";
  const prospectName = docData?.prospectName ?? "Priya Patel — Nexa Retail";
  const workspaceName =
    docData?.workspaceName ?? "AUTHORITY CLOSERS · GROWTH WORKSPACE";
  const callType = docData?.callType ?? "Enterprise Discovery & Demo";
  const callDate = docData?.callDate ?? "2 October 2026";
  const callLength = docData?.callLength ?? "34:12";
  const analysedDate = docData?.analysedDate ?? "2 October 2026";

  const totalPages = 7;

  return (
    <div className={styles.documentContainer}>
      <div className={styles.documentActions}>
        <div className={styles.documentActionsGroup}>
          <button
            type="button"
            className={styles.docBtnPrimary}
            onClick={() => {
              if (typeof window !== "undefined") {
                window.print();
              }
            }}
          >
            <Printer aria-hidden="true" />
            <span>Download PDF</span>
          </button>
          <button
            type="button"
            className={styles.docBtnSecondary}
            title="Word export (editable format)"
            onClick={() => {
              if (typeof window !== "undefined") {
                window.alert(
                  "Word export (.docx) will download editable format when server pipeline completes.",
                );
              }
            }}
          >
            <FileDown aria-hidden="true" />
            <span>Download Word</span>
          </button>
        </div>
        <span className={styles.documentActionsNote}>
          A4 Portrait (210×297 mm) · 7 Pages · Pixel-perfect export
        </span>
      </div>

      <div className={styles.documentPages}>
        {/* Page 1: Cover / Overall Assessment */}
        <div className={styles.documentPage}>
          <div className={styles.docKicker}>{workspaceName}</div>
          <div className={styles.docSubtitle}>
            {callType} · {callDate}
          </div>
          <h1 className={styles.docTitle}>
            {repName} — {prospectName} call report
          </h1>
          <div className={styles.docMetaLine}>
            Prepared: {callDate} · Call length {callLength} · Analysed{" "}
            {analysedDate}
          </div>

          <div className={styles.docBasisCallout}>
            <div className={styles.docBasisLabel}>ANALYSIS BASIS</div>
            <p className={styles.docBasisText}>
              Assessment based on full {callLength} dual-channel audio recording
              and transcript.
            </p>
            <p className={styles.docBasisText}>
              Evaluated against Sales Xray v0.2 competency framework for
              commercial coaching.
            </p>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="overview"
          >
            <div className={styles.docSectionHeader}>
              <span className={styles.docSectionNumber}>1.</span>
              <h2
                id={`${id}-heading-overview`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Overall assessment
              </h2>
              <span className={`${styles.docBadge} ${styles.docBadgeNavy}`}>
                LEVEL 3 — DEVELOPING CLOSER
              </span>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />
            <p>
              Aarav establishes immediate conversational rapport and demonstrates
              genuine active listening during the discovery phase. However, when
              technical objections arose around migration, the presentation
              shifted into defensive feature validation rather than exploring
              commercial impact.
            </p>
            <ul className={styles.docBullets}>
              <li>
                <strong>Strong opening empathy:</strong> acknowledged prospect
                pain points around manual reporting without interrupting.
              </li>
              <li>
                <strong>Premature demo transition:</strong> launched screen
                sharing before uncovering the procurement timeline or decision
                criteria.
              </li>
              <li>
                <strong>Weak commercial tension:</strong> conceded pricing
                options too early when prospect raised hesitation.
              </li>
            </ul>
            <div className={styles.docQuoteBlock}>
              <div className={styles.docQuoteShift}>
                <div className={styles.docQuoteOriginal}>
                  <em>Rep quote:</em> &quot;We have several plans, maybe you want
                  to start with the standard one?&quot;
                </div>
                <div className={styles.docQuoteBetter}>
                  <em>Coaching shift:</em> &quot;Based on your team size and Q4
                  goals, the Growth tier gives you the governance controls you
                  mentioned earlier.&quot;
                </div>
              </div>
            </div>
          </div>

          <div className={styles.docFooter}>Page 1 of {totalPages}</div>
        </div>

        {/* Page 2: Scorecard & Strengths */}
        <div className={styles.documentPage}>
          <div className={styles.docRunningHeader}>
            <span>Authority Closers — Sales Xray call report</span>
            <span>{repName}</span>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="skills"
          >
            <div className={styles.docSectionHeader}>
              <span className={styles.docSectionNumber}>2.</span>
              <h2
                id={`${id}-heading-skills`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Scorecard
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />
            <div className={styles.docTableWrapper}>
              <table className={styles.docTable}>
                <thead>
                  <tr>
                    <th>Capability</th>
                    <th>Score</th>
                    <th>Assessment</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Discovery &amp; Diagnosis</td>
                    <td className={styles.docScoreGood}>4.2 / 5</td>
                    <td>
                      Thorough exploration of current operational bottlenecks and
                      reporting pain.
                    </td>
                  </tr>
                  <tr>
                    <td>Value Articulation</td>
                    <td className={styles.docScoreGood}>4.0 / 5</td>
                    <td>
                      Effectively connects workflow automation to reduced sprint
                      overhead.
                    </td>
                  </tr>
                  <tr>
                    <td>Objection Handling</td>
                    <td className={styles.docScoreWatch}>3.7 / 5</td>
                    <td>
                      Addresses security requirements well; concessions on
                      pricing came too quickly.
                    </td>
                  </tr>
                  <tr>
                    <td>Deal Qualification</td>
                    <td className={styles.docScoreRisk}>3.4 / 5</td>
                    <td>
                      Did not identify final budget sign-off authority or
                      procurement constraints.
                    </td>
                  </tr>
                  <tr>
                    <td>Closing &amp; Next Steps</td>
                    <td className={styles.docScoreRisk}>3.5 / 5</td>
                    <td>
                      Missed calendar lock for technical review; defaulted to
                      email follow-up.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className={styles.docScorecardSummary}>
              <span className={styles.docScoreOverall}>
                Overall: 3.8 / 5.0 (~76%)
              </span>
              <span className={styles.docScoreLevel}>
                Current level: Developing Closer
              </span>
            </div>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="prospect"
          >
            <div className={styles.docSectionHeader}>
              <span className={styles.docSectionNumber}>3.</span>
              <h2
                id={`${id}-heading-prospect`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                What the rep already does well
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />
            <div className={styles.docSubSectionTitle}>
              <span>A. Active Listening &amp; Rapport Building</span>
              <span className={`${styles.docBadge} ${styles.docBadgeGood}`}>
                STRONG
              </span>
            </div>
            <ul className={styles.docBullets}>
              <li>
                Validated the prospect&apos;s migration frustration at [04:15]
                with genuine empathy.
              </li>
              <li>
                Reflected prospect&apos;s exact terminology regarding
                &quot;workflow fragmentation&quot;.
              </li>
            </ul>

            <div className={styles.docSubSectionTitle}>
              <span>B. Solution Framing &amp; Value Alignment</span>
              <span className={`${styles.docBadge} ${styles.docBadgeGood}`}>
                STRONG
              </span>
            </div>
            <ul className={styles.docBullets}>
              <li>
                Connected automated routing directly to prospect&apos;s stated
                goal of cutting manual triage.
              </li>
              <li>
                Maintained natural conversational cadence without sounding
                scripted.
              </li>
            </ul>

            <div className={styles.docSubSectionTitle}>
              <span>C. Security &amp; Compliance Confidence</span>
              <span className={`${styles.docBadge} ${styles.docBadgeGood}`}>
                STRONG
              </span>
            </div>
            <ul className={styles.docBullets}>
              <li>
                Answered data residency questions accurately without hesitation
                at [19:40].
              </li>
            </ul>
          </div>

          <div className={styles.docFooter}>Page 2 of {totalPages}</div>
        </div>

        {/* Page 3: Main Development Areas */}
        <div className={styles.documentPage}>
          <div className={styles.docRunningHeader}>
            <span>Authority Closers — Sales Xray call report</span>
            <span>{repName}</span>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="signals"
          >
            <div className={styles.docSectionHeader}>
              <span className={styles.docSectionNumber}>4.</span>
              <h2
                id={`${id}-heading-signals`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Main development areas
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />

            <div className={styles.docSubSectionTitleRed}>
              <span>4.1 Qualification Depth</span>
              <span className={`${styles.docBadge} ${styles.docBadgeRisk}`}>
                HIGH PRIORITY
              </span>
            </div>
            <div className={styles.docQuoteBlock}>
              &quot;Prospect: We might need IT signoff, not sure when they
              meet. Rep: Okay, no problem, just let me know when they do.&quot;
            </div>
            <ul className={styles.docBullets}>
              <li>
                Never asked who owns final signature authority or what budget
                was earmarked for Q4.
              </li>
              <li>
                Left the timeline open-ended rather than proposing a structured
                vendor assessment call with IT.
              </li>
            </ul>

            <div className={styles.docSubSectionTitleRed}>
              <span>4.2 Commercial Urgency &amp; Price Anchoring</span>
              <span className={`${styles.docBadge} ${styles.docBadgeRisk}`}>
                HIGH PRIORITY
              </span>
            </div>
            <div className={styles.docQuoteBlock}>
              &quot;Prospect: Your enterprise tier seems steep compared to what
              we pay now. Rep: Yeah, we can discount that if you need.&quot;
            </div>
            <ul className={styles.docBullets}>
              <li>
                Discounted immediately before re-anchoring on the cost of the
                customer&apos;s daily lost productivity.
              </li>
              <li>
                Conceded margins without securing reciprocal commitment on
                contract duration.
              </li>
            </ul>

            <div className={styles.docSubSectionTitleRed}>
              <span>4.3 Controlled Closing Sequence</span>
              <span className={`${styles.docBadge} ${styles.docBadgeWatch}`}>
                MEDIUM
              </span>
            </div>
            <div className={styles.docQuoteBlock}>
              &quot;Rep: I&apos;ll send an email with some details and you can
              review whenever you have time.&quot;
            </div>
            <ul className={styles.docBullets}>
              <li>
                Missed scheduling a hard calendar date before hanging up the
                call.
              </li>
              <li>Put the burden of next action entirely on the prospect.</li>
            </ul>
          </div>

          <div className={styles.docFooter}>Page 3 of {totalPages}</div>
        </div>

        {/* Page 4: Biggest Strength & Gap Cards */}
        <div className={styles.documentPage}>
          <div className={styles.docRunningHeader}>
            <span>Authority Closers — Sales Xray call report</span>
            <span>{repName}</span>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="strength-gap"
          >
            <div className={styles.docSectionHeader}>
              <span className={styles.docSectionNumber}>5.</span>
              <h2
                id={`${id}-heading-strength-gap`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Biggest strength and biggest gap
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />

            <div className={styles.docCardsRow}>
              <div className={styles.docStrengthCard}>
                <div className={styles.docCardHeader}>
                  <CheckCircle2 size={16} aria-hidden="true" />
                  <span>BIGGEST STRENGTH</span>
                </div>
                <p>
                  Aarav excels at building trust and creating an open dialogue.
                  The prospect felt heard and praised the clarity of the product
                  demonstration. Maintaining this conversational warmth gives
                  Aarav a strong foundation for enterprise sales.
                </p>
                <div className={styles.docArrowChain}>
                  <span className={styles.docArrowItem}>Diagnose</span>
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className={styles.docArrowItem}>Prioritise</span>
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className={styles.docArrowItem}>Recommend</span>
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className={styles.docArrowItem}>Influence</span>
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className={styles.docArrowItem}>Close</span>
                </div>
              </div>

              <div className={styles.docGapCard}>
                <div className={styles.docCardHeader}>
                  <AlertTriangle size={16} aria-hidden="true" />
                  <span>BIGGEST GAP</span>
                </div>
                <p>
                  Aarav avoids direct commercial tension when objections arise.
                  Instead of reframing budget concerns around business ROI, he
                  defaults to discounting and passive scheduling. Establishing
                  deal mechanics early will prevent stalled proposals.
                </p>
                <div className={styles.docArrowChain}>
                  <span className={styles.docArrowItem}>Uncover Risk</span>
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className={styles.docArrowItem}>Anchor Value</span>
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className={styles.docArrowItem}>Trade Terms</span>
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className={styles.docArrowItem}>Lock Date</span>
                </div>
              </div>
            </div>
          </div>

          <div className={styles.docFooter}>Page 4 of {totalPages}</div>
        </div>

        {/* Page 5: Moments & Next-Call Plan */}
        <div className={styles.documentPage}>
          <div className={styles.docRunningHeader}>
            <span>Authority Closers — Sales Xray call report</span>
            <span>{repName}</span>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="moments"
          >
            <div className={styles.docSectionHeader}>
              <span className={styles.docSectionNumber}>6.</span>
              <h2
                id={`${id}-heading-moments`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Moment-by-moment snapshot
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />
            <div className={styles.docTableWrapper}>
              <table className={styles.docTable}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Moment</th>
                    <th>Score</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>1</td>
                    <td>Discovery: Pain Point Identification</td>
                    <td className={styles.docScoreGood}>4.2 / 5</td>
                    <td>
                      Uncovered core operational delay in multi-tier approvals.
                    </td>
                  </tr>
                  <tr>
                    <td>2</td>
                    <td>Product Framing: Workflow Demo</td>
                    <td className={styles.docScoreGood}>4.0 / 5</td>
                    <td>
                      Smooth walkthrough of automated task reassignment.
                    </td>
                  </tr>
                  <tr>
                    <td>3</td>
                    <td>Security Inquiry: Compliance Check</td>
                    <td className={styles.docScoreWatch}>3.8 / 5</td>
                    <td>
                      Satisfied GDPR query, missed SOC2 follow-up opportunity.
                    </td>
                  </tr>
                  <tr>
                    <td>4</td>
                    <td>Budget Discussion: Enterprise Pricing</td>
                    <td className={styles.docScoreRisk}>3.3 / 5</td>
                    <td>
                      Offered early price concession without value exchange.
                    </td>
                  </tr>
                  <tr>
                    <td>5</td>
                    <td>Decision Process: Stakeholder Mapping</td>
                    <td className={styles.docScoreRisk}>3.2 / 5</td>
                    <td>
                      Did not identify economic buyer or procurement timeline.
                    </td>
                  </tr>
                  <tr>
                    <td>6</td>
                    <td>Call Wrap: Next Step Scheduling</td>
                    <td className={styles.docScoreRisk}>3.4 / 5</td>
                    <td>
                      Allowed open-ended email follow-up instead of confirmed demo.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="next-call-plan"
          >
            <div className={styles.docSectionHeader}>
              <span className={styles.docSectionNumber}>7.</span>
              <h2
                id={`${id}-heading-next-call-plan`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Next-call plan and coaching priority
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />
            <ol className={styles.docNumberedList}>
              <li>
                <strong>Lead with multi-stakeholder qualification:</strong> Inquire
                about IT compliance and procurement requirements before resuming
                product details.
              </li>
              <li>
                <strong>Value re-anchoring before quote revision:</strong> When
                prospect brings up pricing, quantify their current lost
                engineering hours before discussing tiers.
              </li>
              <li>
                <strong>Calendar lock for technical demo:</strong> Insist on
                booking a 20-minute slot with the technical lead before sending
                materials.
              </li>
              <li>
                <strong>Prepared talking track for IT objections:</strong> Have data
                privacy architecture slide ready to share during the first 5
                minutes.
              </li>
            </ol>
            <div className={styles.docClosingBox}>
              <div className={styles.docClosingLine}>
                <span className={styles.docClosingLabel}>Current position:</span>{" "}
                Solid rapport builder with clear vocal authority; needs structured
                objection reframing.
              </div>
              <div className={styles.docClosingLine}>
                <span className={styles.docClosingLabel}>
                  Primary coaching focus:
                </span>{" "}
                Shift from feature validation to discovery-driven commercial
                urgency.
              </div>
              <div className={styles.docClosingLine}>
                <span className={styles.docClosingLabel}>Potential:</span> High
                conversion upside on enterprise tier deals with disciplined
                discovery.
              </div>
            </div>
          </div>

          <div className={styles.docFooter}>Page 5 of {totalPages}</div>
        </div>

        {/* Page 6: Appendix Transcript Part 1 */}
        <div className={styles.documentPage}>
          <div className={styles.docRunningHeader}>
            <span>Authority Closers — Sales Xray call report</span>
            <span>{repName}</span>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="transcript"
          >
            <div className={styles.docSectionHeader}>
              <h2
                id={`${id}-heading-transcript`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Appendix: Transcript (00:00 – 16:30)
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />
            <div className={styles.docAppendix}>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[00:04]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                Hi Priya, thanks for joining today. How has your week been so far?
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[00:18]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                Good morning Aarav. Pretty busy! We are evaluating replacements
                for our legacy workflow tools.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[00:35]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                Glad to connect. What is creating the biggest bottleneck in your
                current setup?
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[01:10]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                Permissions take up to three days when cross-functional teams spin
                up new projects.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[01:45]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                That is a significant delay across sprint cycles. Let us walk
                through how our automated governance resolves that in seconds.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[04:15]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                Our team was skeptical about migration overhead because last
                year&apos;s transition took two months.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[04:40]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                I completely understand that caution. Nobody wants downtime
                during active quarterly releases.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[08:42]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                This looks intuitive, but what about data isolation between
                regional teams?
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[09:15]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                Every workspace has full cryptographic tenant isolation and
                regional residency options.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[15:20]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                Your enterprise tier feels expensive compared to our current
                provider.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[15:45]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                We can definitely adjust the pricing to fit within your current
                allocation.
              </div>
            </div>
          </div>

          <div className={styles.docFooter}>Page 6 of {totalPages}</div>
        </div>

        {/* Page 7: Appendix Transcript Part 2 */}
        <div className={styles.documentPage}>
          <div className={styles.docRunningHeader}>
            <span>Authority Closers — Sales Xray call report</span>
            <span>{repName}</span>
          </div>

          <div
            className={styles.docSection}
            data-report-mode-section="raw-data"
          >
            <div className={styles.docSectionHeader}>
              <h2
                id={`${id}-heading-raw-data`}
                tabIndex={-1}
                className={styles.docSectionTitle}
              >
                Appendix: Transcript continued (16:31 – 34:12)
              </h2>
            </div>
            <div className={styles.docDivider} aria-hidden="true" />
            <div className={styles.docAppendix}>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[18:10]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                If we roll this out, we need SSO and custom role delegation
                enabled from day one.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[18:35]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                Both are built into the admin console with Okta and Azure AD SCIM
                provisioning.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[22:10]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                We will need our security lead to review the SOC2 report before
                any commitment.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[22:30]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                Absolutely. I will email the SOC2 package and you can circle back
                when convenient.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[27:50]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                Sounds good. Send that over and I will check with our IT
                committee.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[28:15]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                Perfect, I&apos;ll send an email with some details and you can
                review whenever you have time.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[32:00]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  Priya Patel (Prospect):
                </span>{" "}
                Great, thanks for the walkthrough Aarav. Have a good rest of your
                week.
              </div>
              <div className={styles.docTranscriptLine}>
                <span className={styles.docTranscriptTime}>[32:15]</span>{" "}
                <span className={styles.docTranscriptSpeaker}>
                  {repName} (Rep):
                </span>{" "}
                Thanks Priya, talk soon!
              </div>
            </div>

            {/* Hidden fallback anchors for any custom panels not listed above */}
            {panels
              .filter(
                (p) =>
                  ![
                    "overview",
                    "skills",
                    "prospect",
                    "signals",
                    "moments",
                    "next-call-plan",
                    "transcript",
                    "raw-data",
                  ].includes(p.id),
              )
              .map((panel) => (
                <div
                  key={panel.id}
                  id={`${id}-heading-${panel.id}`}
                  data-report-mode-section={panel.id}
                  style={{ display: "none" }}
                  aria-hidden="true"
                />
              ))}
          </div>

          <div className={styles.docFooter}>Page 7 of {totalPages}</div>
        </div>
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

  const [textSize, setTextSize] = useState<TextSize>(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem(TEXT_SIZE_KEY);
        if (saved === "100" || saved === "112.5" || saved === "125") {
          return saved;
        }
      } catch {}
    }
    return "100";
  });

  const changeTextSize = (nextSize: TextSize) => {
    setTextSize(nextSize);
    if (typeof window !== "undefined") {
      try {
        localStorage.setItem(TEXT_SIZE_KEY, nextSize);
      } catch {}
    }
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("view") === "document" && params.get("print") === "1") {
        const timer = window.setTimeout(() => {
          window.print();
        }, 350);
        return () => window.clearTimeout(timer);
      }
    }
  }, []);

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
      (view === "reading" || view === "document") && nextView === "tabs"
        ? currentSection
        : (selected ?? panels[0]?.id);
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
      data-lx-surface={lightSurface ? "light" : undefined}
      data-view={view}
      data-report-section={currentSection}
      data-text-size={textSize}
    >
      {slot ? createPortal(navigation, slot) : navigation}
      <div className={styles.layout}>
        {view === "document" ? (
          renderDocumentView(id, panels, documentData)
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
