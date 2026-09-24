"use client";

import {
  createContext,
  useContext,
  useId,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowUpRight,
  Gem,
  LockKeyhole,
  Play,
  Target,
  TrendingUp,
} from "lucide-react";
import type {
  Finding,
  PreviewSection,
  ReportEvidence,
  SalesReport,
} from "./report-contract";
import { FindingEvidence } from "./finding-evidence";
import { SourceWaveform } from "./source-waveform";
import { ReviewDialog } from "./review-dialog";
import { OverviewDashboard } from "./overview-dashboard";
import { countReportMoments } from "./report-moments";
import {
  useReportNavigation,
  useReportReading,
} from "./report-reading-context";
import styles from "./dipak-overview.module.css";

type Props = {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
  durationMs?: number;
  showHeading?: boolean;
};

type ChapterId = "start" | "read" | "practice" | "close";
const FocusedReview = createContext<string | null>(null);

const time = (ms: number) =>
  `${Math.floor(ms / 60000)
    .toString()
    .padStart(2, "0")}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, "0")}`;

function SkillMark() {
  return (
    <svg className={styles.skillMark} viewBox="0 0 72 72" aria-hidden="true">
      <path d="M10 55.5 24 41l10 8 18-24 10 9" />
      <path d="M48 25h14v14" />
      <circle cx="10" cy="55.5" r="3" />
      <circle cx="24" cy="41" r="3" />
      <circle cx="34" cy="49" r="3" />
      <circle cx="52" cy="25" r="3" />
      <circle cx="62" cy="34" r="3" />
    </svg>
  );
}

function ReviewBlock({
  number,
  title,
  description,
  children,
  tone = "neutral",
  expanded = false,
}: {
  number: string;
  title: string;
  description?: string;
  children: ReactNode;
  tone?: "neutral" | "positive" | "priority";
  expanded?: boolean;
}) {
  const focused = useContext(FocusedReview);
  const reading = useReportReading();
  const navigateToReport = useReportNavigation();
  const header = (
    <>
      <span className={styles.number}>{number}</span>
      <div className={styles.blockHeadingCopy}>
        <h3>{title}</h3>
        {description && <p>{description}</p>}
      </div>
    </>
  );
  if (
    !expanded &&
    !reading &&
    !focused &&
    !["01", "02", "08", "11"].includes(number)
  ) {
    return (
      <details
        className={`${styles.block} ${styles.fold}`}
        data-review-fold
        data-tone={tone}
        data-review-point={number}
        tabIndex={-1}
      >
        <summary className={styles.blockHeading}>
          {header}
          <span className={styles.expand} aria-hidden="true">
            +
          </span>
        </summary>
        <div className={styles.foldContent}>{children}</div>
      </details>
    );
  }
  return (
    <section
      className={styles.block}
      data-tone={tone}
      data-review-point={number}
      hidden={focused !== null && focused !== number}
      tabIndex={-1}
    >
      <div className={styles.blockHeading}>{header}</div>
      {children}
    </section>
  );
}

function ImprovementDetailTabs({
  whatHappened,
  whyItMatters,
  tryThis,
  evidence,
  impact,
}: {
  whatHappened: ReactNode;
  whyItMatters: string;
  tryThis: string;
  evidence: ReactNode;
  impact: ReactNode;
}) {
  const reading = useReportReading();
  const prefix = useId();
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const [tab, setTab] = useState<"happened" | "matters" | "try">("happened");
  const tabs = [
    ["happened", "What happened"],
    ["matters", "Why it matters"],
    ["try", "Try this"],
  ] as const;
  return (
    <div
      className={styles.improvementTabs}
      data-improvement-tabs
      data-reading={reading || undefined}
    >
      <div
        className={styles.improvementTabList}
        role="tablist"
        aria-label="Improvement detail"
        hidden={reading}
      >
        {tabs.map(([id, label], index) => (
          <button
            key={id}
            ref={(button) => {
              tabButtons.current[index] = button;
            }}
            id={`${prefix}-tab-${id}`}
            aria-controls={`${prefix}-panel-${id}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % tabs.length
                  : event.key === "ArrowLeft"
                    ? (index + tabs.length - 1) % tabs.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? tabs.length - 1
                        : null;
              if (next === null) return;
              event.preventDefault();
              setTab(tabs[next][0]);
              tabButtons.current[next]?.focus();
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        className={styles.improvementTabPanel}
        role={reading ? "region" : "tabpanel"}
        id={`${prefix}-panel-happened`}
        aria-labelledby={reading ? undefined : `${prefix}-tab-happened`}
        aria-label={reading ? "What happened" : undefined}
        hidden={!reading && tab !== "happened"}
      >
        {reading && <h4>What happened</h4>}
        {whatHappened}
      </div>
      <div
        className={styles.improvementTabPanel}
        role={reading ? "region" : "tabpanel"}
        id={`${prefix}-panel-matters`}
        aria-labelledby={reading ? undefined : `${prefix}-tab-matters`}
        aria-label={reading ? "Why it matters" : undefined}
        hidden={!reading && tab !== "matters"}
      >
        {reading && <h4>Why it matters</h4>}
        <p>{whyItMatters}</p>
      </div>
      <div
        className={styles.improvementTabPanel}
        role={reading ? "region" : "tabpanel"}
        id={`${prefix}-panel-try`}
        aria-labelledby={reading ? undefined : `${prefix}-tab-try`}
        aria-label={reading ? "Try this" : undefined}
        hidden={!reading && tab !== "try"}
      >
        {reading && <h4>Try this</h4>}
        <p>{tryThis}</p>
      </div>
      {impact}
      {evidence}
    </div>
  );
}

/** A source-preserving presentation of Dipak's template, not a second judge. */
export function DipakOverview({
  report,
  onSelectEvidence,
  onUnlock,
  durationMs,
  showHeading = true,
}: Props) {
  const reading = useReportReading();
  const navigateToReport = useReportNavigation();
  const overview = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let previous: Map<HTMLDetailsElement, boolean> | null = null;
    const beforePrint = () => {
      if (previous) return;
      previous = new Map(
        [
          ...(overview.current?.querySelectorAll<HTMLDetailsElement>(
            "[data-review-fold], [data-source-details]",
          ) ?? []),
        ].map((detail) => [detail, detail.open]),
      );
      previous.forEach((_, detail) => {
        detail.open = true;
      });
    };
    const restore = () => {
      previous?.forEach((open, detail) => {
        detail.open = open;
      });
      previous = null;
    };
    window.addEventListener("beforeprint", beforePrint);
    window.addEventListener("afterprint", restore);
    return () => {
      window.removeEventListener("beforeprint", beforePrint);
      window.removeEventListener("afterprint", restore);
      restore();
    };
  }, []);
  const prefix = useId();
  const [activeChapter, setActiveChapter] = useState<ChapterId | null>(null);
  const [activeReviewNumber, setActiveReviewNumber] = useState<string | null>(
    null,
  );
  const [activeTakeaway, setActiveTakeaway] = useState(0);
  const lastInsightButton = useRef<HTMLButtonElement | null>(null);
  const focusId = `${prefix}-focus`;
  const fixesId = `${prefix}-fixes`;
  const rewatchId = `${prefix}-rewatch`;

  const primary = report.improvements[0];
  const detail = report.overview;
  const priorities = report.improvements.slice(0, 3);
  const supportedDimensions = report.dimensions.filter(
    (dimension) =>
      dimension.status === "observed" && Boolean(dimension.observation.trim()),
  );
  const savedStrengths = report.strengths
    .filter((finding) => finding.evidence.length > 0)
    .slice(0, 3);
  const candidates = [
    ...report.improvements.map((finding) => ({
      finding,
      label: "Practise this",
      kind: "priority",
    })),
    ...report.missed_opportunities.map((finding) => ({
      finding,
      label: "Look closer",
      kind: "watch",
    })),
    ...report.strengths.map((finding) => ({
      finding,
      label: "Learn from this",
      kind: "positive",
    })),
  ];
  // One source-backed clip from each category, retaining the saved report order.
  const seen = new Set<string>();
  const kinds = new Set<string>();
  const legacyRewatch = candidates.flatMap((candidate) => {
    if (kinds.has(candidate.kind)) return [];
    const evidence = candidate.finding.evidence.find(
      (item) => !seen.has(`${item.segment_id}:${item.start_ms}:${item.end_ms}`),
    );
    if (!evidence) return [];
    seen.add(`${evidence.segment_id}:${evidence.start_ms}:${evidence.end_ms}`);
    kinds.add(candidate.kind);
    return [{ ...candidate, evidence }];
  });
  const rewatch = detail
    ? detail.rewatch.map((moment) => ({
        finding: { title: moment.text },
        evidence: moment.evidence[0],
        label: {
          must_watch: "Must watch",
          watch: "Watch this",
          repeat: "Learn from this",
        }[moment.purpose],
        kind: { must_watch: "priority", watch: "watch", repeat: "positive" }[
          moment.purpose
        ],
      }))
    : legacyRewatch;
  const golden = detail
    ? detail.golden_moments.map((moment) => ({
        ...report.strengths[moment.strength_index],
        explanation: moment.why_effective,
        evidence: [
          report.strengths[moment.strength_index].evidence[
            moment.evidence_index
          ],
        ],
      }))
    : savedStrengths;
  const sourceMoment = rewatch[0] ?? null;
  const primaryDetail = detail?.improvement_details.find(
    (item) => item.finding_index === 0,
  );
  const insightRailItems: Array<{
    number: string;
    label: string;
    chapter: ChapterId;
  }> = [
    {
      number: "01",
      label: "What you’re already good at",
      chapter: "start",
    },
    ...priorities.map((finding, index) => ({
      number: `0${index + 2}`,
      label: finding.title,
      chapter: "start" as ChapterId,
    })),
    { number: "05", label: "Golden moments", chapter: "read" },
    { number: "06", label: "Missed opportunities", chapter: "read" },
    {
      number: "07",
      label: "What the prospect may have meant",
      chapter: "read",
    },
    { number: "08", label: "Your rewatch list", chapter: "read" },
    { number: "09", label: "Where the conversation changed", chapter: "read" },
    { number: "10", label: "Your sales skills", chapter: "practice" },
    { number: "11", label: "Your next-call focus", chapter: "practice" },
    { number: "12", label: "Personalized practice", chapter: "practice" },
    { number: "13", label: "Across-call pattern", chapter: "close" },
    { number: "14", label: "Final verdict", chapter: "close" },
  ];
  const activeReviewIndex = Math.max(
    0,
    insightRailItems.findIndex((item) => item.number === activeReviewNumber),
  );
  const activeReview =
    insightRailItems[activeReviewIndex] ?? insightRailItems[0];

  function focusInsight(number: string, chapter: ChapterId) {
    setActiveReviewNumber(number);
    setActiveChapter(chapter);
    if (!showHeading && navigateToReport) {
      navigateToReport("overview", number);
      return;
    }
    window.setTimeout(() => {
      const item = overview.current?.querySelector<HTMLElement>(
        `[data-review-point="${number}"]`,
      );
      if (!item) return;
      if (item instanceof HTMLDetailsElement) item.open = true;
      item.focus({ preventScroll: true });
      const reduceMotion =
        window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ??
        false;
      item.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "start",
      });
    }, 0);
  }

  function closeReader() {
    setActiveReviewNumber(null);
    setActiveChapter(null);
    window.setTimeout(() => {
      const fallback = overview.current?.querySelector<HTMLButtonElement>(
        "[data-insight-number]",
      );
      (lastInsightButton.current ?? fallback)?.focus();
    }, 0);
  }

  function evidence(finding: Finding) {
    return (
      <FindingEvidence count={finding.evidence.length}>
        {finding.evidence.map((item, index) => (
          <blockquote key={`${item.segment_id}-${index}`}>
            <div className={styles.evidenceControls}>
              <span className={styles.evidenceQuote}>{item.quote}</span>
              <button
                className={styles.timestamp}
                type="button"
                onClick={() => onSelectEvidence(item, finding.title)}
                aria-label={`Play source moment, ${time(item.start_ms)} to ${time(item.end_ms)}: ${item.quote}`}
              >
                <Play size={12} aria-hidden="true" />
                {time(item.start_ms)}–{time(item.end_ms)}
              </button>
              <SourceWaveform
                className={styles.evidenceWaveform}
                startMs={item.start_ms}
                endMs={item.end_ms}
              />
            </div>
          </blockquote>
        ))}
      </FindingEvidence>
    );
  }

  function findingCard(finding: Finding, index: number) {
    return (
      <article className={styles.finding} key={`${finding.title}-${index}`}>
        <h4>{finding.title}</h4>
        <p>{finding.explanation}</p>
        {evidence(finding)}
      </article>
    );
  }

  function sourceNote(
    note: { text: string; evidence: ReportEvidence[] },
    label: string,
  ) {
    return (
      <div className={styles.sourceNote}>
        <p className={styles.label}>{label}</p>
        <p>{note.text}</p>
        {evidence({
          title: label,
          explanation: note.text,
          evidence: note.evidence,
        })}
      </div>
    );
  }

  function unlock(section: PreviewSection) {
    const remaining = report.preview?.sections[section].hidden_count ?? 0;
    if (!remaining) return null;
    return (
      <aside className={styles.unlock} data-preview-section={section}>
        <span className={styles.unlockIcon} aria-hidden="true">
          <LockKeyhole size={19} />
        </span>
        <div>
          <strong>
            {remaining} more {remaining === 1 ? "insight" : "insights"} in your
            report
          </strong>
          <p>Unlock remaining insights with a free account.</p>
        </div>
        {onUnlock && (
          <button type="button" onClick={onUnlock}>
            Continue free <ArrowUpRight size={15} aria-hidden="true" />
          </button>
        )}
      </aside>
    );
  }

  return (
    <div
      ref={overview}
      className={styles.overview}
      aria-label="Dipak’s call review"
      data-report-workspace
      data-compact={!showHeading && !reading}
      data-reading={reading || undefined}
    >
      {!showHeading && (
        <OverviewDashboard
          report={report}
          durationMs={durationMs}
          momentCount={countReportMoments(report)}
          onSelectEvidence={onSelectEvidence}
          onOpenReview={(number) => {
            const item = insightRailItems.find(
              (point) => point.number === number,
            );
            if (item) {
              lastInsightButton.current =
                document.activeElement instanceof HTMLButtonElement
                  ? document.activeElement
                  : null;
              focusInsight(item.number, item.chapter);
            }
          }}
        />
      )}
      <section
        className={styles.resultLead}
        aria-label="Report summary"
        data-summary-card="summary"
      >
        <div className={styles.resultLeadCopy} hidden={!showHeading}>
          <p className={styles.eyebrow}>CALL REVIEW</p>
          <h1>Your call, clearly.</h1>
          <p className={styles.heroSubcopy}>{report.summary}</p>
          <span className={styles.visuallyHidden}>{report.verdict}</span>
        </div>
        {showHeading && (
          <div className={styles.reportMetrics} aria-label="Call metrics">
            <div className={styles.metric}>
              <span>Call duration</span>
              <strong>{durationMs ? time(durationMs) : "Not supplied"}</strong>
            </div>
            <div className={styles.metric}>
              <span>Highlights</span>
              <strong>{countReportMoments(report)}</strong>
            </div>
            <div className={`${styles.metric} ${styles.metricAction}`}>
              <span>Suggested actions</span>
              <strong>{report.improvements.length}</strong>
            </div>
          </div>
        )}
        <div className={styles.heroMeta} aria-label="Report status">
          <span className={styles.statusPill}>Draft report</span>
        </div>
        {(detail?.diagnosis || detail?.outcome) && (
          <details
            className={styles.sourceDetails}
            data-source-details
            open={reading}
          >
            <summary className={styles.sourceDetailsSummary}>
              <span>Read source context</span>
              <ArrowUpRight size={15} aria-hidden="true" />
            </summary>
            <div className={styles.sourceContext} aria-label="Source context">
              {detail.diagnosis && sourceNote(detail.diagnosis, "Diagnosis")}
              {detail.outcome &&
                sourceNote(detail.outcome, "Observed outcome · draft")}
            </div>
          </details>
        )}
      </section>

      <section className={styles.takeawayGrid} aria-label="Call takeaways">
        <article
          className={`${styles.takeawayCard} ${styles.takeawayCardLead}`}
          data-takeaway-index="0"
          data-active={activeTakeaway === 0}
        >
          <p className={styles.eyebrow}>KEY TAKEAWAY</p>
          <h2>{detail?.diagnosis?.text ?? report.verdict}</h2>
          <p>{report.summary}</p>
          <button
            className={styles.takeawayAction}
            type="button"
            onClick={() => focusInsight("14", "close")}
          >
            Open review <ArrowUpRight size={16} aria-hidden="true" />
          </button>
        </article>
        <article
          className={`${styles.takeawayCard} ${styles.takeawayCardMint}`}
          data-takeaway-index="1"
          data-active={activeTakeaway === 1}
        >
          <p className={styles.eyebrow}>KEEP DOING THIS</p>
          <h2>
            {report.strengths[0]?.title ?? "No supported strength recorded"}
          </h2>
          <p>
            {report.strengths[0]?.explanation ??
              "The saved report does not include a supported strength yet."}
          </p>
          <button
            className={styles.inlineAction}
            type="button"
            onClick={() => focusInsight("01", "start")}
          >
            Open review <ArrowUpRight size={15} aria-hidden="true" />
          </button>
        </article>
        <article
          className={`${styles.takeawayCard} ${styles.takeawayCardOrange}`}
          data-takeaway-index="2"
          data-active={activeTakeaway === 2}
        >
          <p className={styles.eyebrow}>FIRST CHANGE</p>
          <h2>{primary?.title ?? "No supported improvement recorded"}</h2>
          <p>
            {primaryDetail?.replacement_behavior ??
              primary?.explanation ??
              "No first change was supplied."}
          </p>
          {primary && (
            <button
              className={styles.inlineAction}
              type="button"
              onClick={() => focusInsight("02", "start")}
            >
              Read the evidence <ArrowUpRight size={15} aria-hidden="true" />
            </button>
          )}
        </article>
        <article
          className={`${styles.takeawayCard} ${styles.takeawayCardBlue}`}
          data-takeaway-index="3"
          data-active={activeTakeaway === 3}
        >
          <p className={styles.eyebrow}>OUTCOME</p>
          <h2>
            {detail?.outcome?.text ??
              "Outcome stays grounded in the saved evidence."}
          </h2>
          <p>
            {detail?.outcome
              ? "Observed outcome from this call."
              : "No separate outcome statement was supplied."}
          </p>
          <button
            className={styles.inlineAction}
            type="button"
            onClick={() => focusInsight("14", "close")}
          >
            Open review <ArrowUpRight size={15} aria-hidden="true" />
          </button>
        </article>
        <article
          className={`${styles.takeawayCard} ${styles.takeawayCardViolet}`}
          data-takeaway-index="4"
          data-active={activeTakeaway === 4}
        >
          <p className={styles.eyebrow}>NEXT-CALL PLAN</p>
          <h2>
            {detail?.next_call_focus?.behavior ??
              primary?.title ??
              "Choose one supported practice move."}
          </h2>
          <p>
            {detail?.practice?.instructions ??
              "Open the review points to connect the next move to its source."}
          </p>
          <button
            className={styles.inlineAction}
            type="button"
            onClick={() =>
              navigateToReport
                ? navigateToReport("next-call-plan")
                : focusInsight("11", "practice")
            }
          >
            Open plan <ArrowUpRight size={15} aria-hidden="true" />
          </button>
        </article>
        <div className={styles.takeawayControls} aria-label="Takeaway cards">
          <button
            type="button"
            aria-label="Previous takeaway"
            onClick={() => setActiveTakeaway((index) => (index + 4) % 5)}
          >
            ←
          </button>
          <div className={styles.takeawayDots} aria-hidden="true">
            {[0, 1, 2, 3, 4].map((index) => (
              <span key={index} data-active={activeTakeaway === index} />
            ))}
          </div>
          <button
            type="button"
            aria-label="Next takeaway"
            onClick={() => setActiveTakeaway((index) => (index + 1) % 5)}
          >
            →
          </button>
        </div>
        <div
          className={styles.takeawayPills}
          role="tablist"
          aria-label="Takeaway categories"
        >
          {["Takeaway", "Keep", "Change", "Outcome", "Practice"].map(
            (label, index) => (
              <button
                key={label}
                type="button"
                role="tab"
                aria-selected={activeTakeaway === index}
                onClick={() => setActiveTakeaway(index)}
              >
                {label}
              </button>
            ),
          )}
        </div>
      </section>

      <div className={styles.workspaceLayout}>
        <div className={styles.aboveFold}>
          <section className={styles.sourceMoment} aria-label="Source moment">
            <span className={styles.sourcePlay} aria-hidden="true">
              <Play size={18} />
            </span>
            <div className={styles.sourceMomentCopy}>
              {sourceMoment ? (
                <>
                  <strong>{sourceMoment.finding.title}</strong>
                  <span>
                    {sourceMoment.label} ·{" "}
                    {time(sourceMoment.evidence.start_ms)}–
                    {time(sourceMoment.evidence.end_ms)}
                  </span>
                </>
              ) : (
                <span>No source-linked moment is available to replay yet.</span>
              )}
            </div>
            {sourceMoment && (
              <button
                className={styles.sourceMomentButton}
                type="button"
                data-source-moment
                onClick={() =>
                  onSelectEvidence(
                    sourceMoment.evidence,
                    sourceMoment.finding.title,
                  )
                }
                aria-label={`Play source moment, ${time(sourceMoment.evidence.start_ms)} to ${time(sourceMoment.evidence.end_ms)}: ${sourceMoment.finding.title}`}
              >
                Play source moment <Play size={14} aria-hidden="true" />
              </button>
            )}
          </section>
        </div>

        <aside className={styles.insightRail} aria-label="Review points">
          <div className={styles.insightRailHeading}>
            <div>
              <p className={styles.eyebrow}>REVIEW MAP</p>
              <h3>Review points</h3>
            </div>
            <span>Open a point to read its evidence.</span>
          </div>
          <ol>
            {insightRailItems.map((item) => (
              <li key={item.number}>
                <button
                  type="button"
                  data-insight-number={item.number}
                  aria-controls={`${prefix}-chapter-panel-${item.chapter}`}
                  aria-current={
                    activeReviewNumber === item.number ? "true" : undefined
                  }
                  onClick={(event) => {
                    lastInsightButton.current = event.currentTarget;
                    focusInsight(item.number, item.chapter);
                  }}
                >
                  <span className={styles.insightNumber}>{item.number}</span>
                  <span>{item.label}</span>
                  <ArrowUpRight size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ol>
        </aside>

        <div className={styles.detailArea}>
          <ReviewDialog
            open={!reading && Boolean(activeChapter)}
            icon={<Target />}
            tone={
              ["02", "03", "04"].includes(activeReviewNumber ?? "")
                ? "orange"
                : "mint"
            }
            eyebrow="Draft coaching · grounded in this call"
            title={activeReview?.label ?? "Review point"}
            position={`Review point ${activeReviewIndex + 1} of ${insightRailItems.length}`}
            onClose={closeReader}
            onPrevious={() => {
              const previous = insightRailItems[activeReviewIndex - 1];
              if (previous) focusInsight(previous.number, previous.chapter);
            }}
            onNext={() => {
              const next = insightRailItems[activeReviewIndex + 1];
              if (next) focusInsight(next.number, next.chapter);
            }}
            previousDisabled={activeReviewIndex === 0}
            nextDisabled={activeReviewIndex === insightRailItems.length - 1}
          >
            {activeChapter && !reading && (
              <button
                className={styles.backToOverview}
                type="button"
                data-back-to-overview
                onClick={closeReader}
              >
                <ArrowUpRight size={15} aria-hidden="true" />
                Back to review points
              </button>
            )}
            <FocusedReview.Provider
              value={!reading && !showHeading ? activeReviewNumber : null}
            >
              <div
                className={styles.chapterStack}
                data-focused={!reading && !showHeading && !!activeChapter}
                hidden={!reading && !activeChapter}
              >
                <section
                  className={styles.chapter}
                  data-chapter="start"
                  id={`${prefix}-chapter-panel-start`}
                  role="region"
                  aria-label="Start here"
                  tabIndex={0}
                  hidden={!reading && activeChapter !== "start"}
                >
                  <div className={styles.chapterHeading}>
                    <span className={styles.chapterRange}>01—04</span>
                    <div>
                      <p className={styles.eyebrow}>START HERE</p>
                      <h3>Keep the useful. Pick one change.</h3>
                    </div>
                    <span className={styles.chapterNote}>
                      The shortest path through this report
                    </span>
                  </div>

                  <ReviewBlock
                    number="01"
                    title="What you’re already good at"
                    description="Keep these useful behaviours in your next call."
                    tone="positive"
                  >
                    {report.strengths.length ? (
                      <div className={styles.strengths}>
                        {report.strengths.map((finding, index) => (
                          <div key={index}>
                            {findingCard(finding, index)}
                            {detail?.strength_details.find(
                              (item) => item.finding_index === index,
                            ) && (
                              <p className={styles.why}>
                                <strong>Why it matters:</strong>{" "}
                                {
                                  detail.strength_details.find(
                                    (item) => item.finding_index === index,
                                  )!.why_it_matters
                                }
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className={styles.empty}>
                        This report did not identify a supported strength.
                      </p>
                    )}
                    {unlock("strengths")}
                  </ReviewBlock>

                  <div id={fixesId} className={styles.anchor}>
                    <div className={styles.groupHeading}>
                      <Target size={19} aria-hidden="true" />
                      <h3>Your priority fixes</h3>
                      <span>Start with the first</span>
                    </div>
                    {priorities.length ? (
                      priorities.map((finding, index) => (
                        <ReviewBlock
                          key={index}
                          number={`0${index + 2}`}
                          title={finding.title}
                          tone="priority"
                        >
                          {(() => {
                            const fix = detail?.improvement_details.find(
                              (item) => item.finding_index === index,
                            );
                            return fix ? (
                              <ImprovementDetailTabs
                                whatHappened={sourceNote(
                                  fix.what_happened,
                                  "What happened",
                                )}
                                whyItMatters={fix.why_it_matters}
                                tryThis={fix.replacement_behavior}
                                evidence={evidence(finding)}
                                impact={
                                  <div className={styles.impact}>
                                    <TrendingUp size={16} aria-hidden="true" />
                                    <div>
                                      <strong>Business impact</strong>
                                      <p>
                                        Insufficient data for a reliable
                                        estimate.
                                      </p>
                                      <small>
                                        {fix.business_impact.missing_inputs.join(
                                          " · ",
                                        ) ||
                                          "Lead volume, conversion history and time or revenue data are needed to calculate this."}
                                      </small>
                                    </div>
                                  </div>
                                }
                              />
                            ) : (
                              <>
                                <p className={styles.label}>
                                  What to do differently
                                </p>
                                <p>{finding.explanation}</p>
                                {evidence(finding)}
                                <div className={styles.impact}>
                                  <TrendingUp size={16} aria-hidden="true" />
                                  <div>
                                    <strong>Business impact</strong>
                                    <p>
                                      Insufficient data for a reliable estimate.
                                    </p>
                                    <small>
                                      Lead volume, conversion history and time
                                      or revenue data are needed to calculate
                                      this.
                                    </small>
                                  </div>
                                </div>
                              </>
                            );
                          })()}
                        </ReviewBlock>
                      ))
                    ) : (
                      <p className={styles.empty}>
                        This report has no supported improvement to prioritise
                        yet.
                      </p>
                    )}
                    {unlock("improvements")}
                  </div>
                </section>

                <section
                  className={styles.chapter}
                  data-chapter="read"
                  id={`${prefix}-chapter-panel-read`}
                  role="region"
                  aria-label="Read the conversation"
                  tabIndex={0}
                  hidden={!reading && activeChapter !== "read"}
                >
                  <div className={styles.chapterHeading}>
                    <span className={styles.chapterRange}>05—09</span>
                    <div>
                      <p className={styles.eyebrow}>READ THE CONVERSATION</p>
                      <h3>See where the call opened up or narrowed.</h3>
                    </div>
                    <span className={styles.chapterNote}>
                      Moments stay linked to the source
                    </span>
                  </div>

                  <ReviewBlock
                    number="05"
                    title="Golden moments"
                    description={
                      detail
                        ? "Selected moments worth repeating."
                        : "From your saved strengths; no separate golden-moment assessment yet."
                    }
                    tone="positive"
                  >
                    {golden.length ? (
                      <div className={styles.golden}>
                        {golden.map((finding, index) => (
                          <div key={index}>
                            <Gem size={17} aria-hidden="true" />
                            <div>
                              <h4>{finding.title}</h4>
                              {detail && <p>{finding.explanation}</p>}
                              {evidence(finding)}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className={styles.empty}>
                        {report.preview?.sections.golden_moments.hidden_count
                          ? "More selected moments are available in your full report."
                          : "No source-linked strength is available to replay yet."}
                      </p>
                    )}
                    {unlock("golden_moments")}
                  </ReviewBlock>

                  <ReviewBlock
                    number="06"
                    title="Missed opportunities"
                    description="Places where the conversation could have gone further."
                  >
                    {report.missed_opportunities.length ? (
                      report.missed_opportunities.map((finding, index) => {
                        const missed = detail?.missed_details.find(
                          (item) => item.finding_index === index,
                        );
                        return missed ? (
                          <article className={styles.finding} key={index}>
                            <h4>{finding.title}</h4>
                            {sourceNote(
                              missed.prospect_signal,
                              "What the prospect said",
                            )}
                            {sourceNote(
                              missed.closer_response,
                              "How you responded",
                            )}
                            <p>
                              <strong>Explore next:</strong> {missed.follow_up}
                            </p>
                            <p>
                              <strong>Possible value:</strong>{" "}
                              {missed.potential_impact}
                            </p>
                          </article>
                        ) : (
                          findingCard(finding, index)
                        );
                      })
                    ) : (
                      <p className={styles.empty}>
                        No missed opportunity was identified in this report.
                      </p>
                    )}
                    {unlock("missed_opportunities")}
                  </ReviewBlock>

                  <ReviewBlock
                    number="07"
                    title="What the prospect may have meant"
                  >
                    {detail?.prospect_interpretations.length ? (
                      <>
                        <p className={styles.empty}>
                          Possible interpretations to check, not facts about the
                          person.
                        </p>
                        {detail.prospect_interpretations.map((item, index) => (
                          <div className={styles.interpretation} key={index}>
                            {sourceNote(item.source, "What was said")}
                            <div>
                              <p className={styles.label}>
                                Possible concern · inference
                              </p>
                              <p>{item.possible_concern}</p>
                            </div>
                          </div>
                        ))}
                      </>
                    ) : (
                      <p className={styles.empty}>
                        No separate interpretation is recorded in this report.
                        The transcript preserves what was said; an underlying
                        concern needs supporting evidence.
                      </p>
                    )}
                    {unlock("prospect_interpretations")}
                  </ReviewBlock>

                  <div id={rewatchId} className={styles.anchor}>
                    <ReviewBlock
                      number="08"
                      title="Your rewatch list"
                      description="Start with these moments instead of replaying the whole call."
                    >
                      {rewatch.length ? (
                        <div className={styles.rewatch}>
                          {rewatch.map(
                            ({ finding, evidence: item, label, kind }) => (
                              <button
                                type="button"
                                key={`${item.segment_id}:${item.start_ms}:${item.end_ms}`}
                                data-kind={kind}
                                onClick={() =>
                                  onSelectEvidence(item, finding.title)
                                }
                              >
                                <span className={styles.play}>
                                  <Play size={17} aria-hidden="true" />
                                </span>
                                <span className={styles.clipCopy}>
                                  <small>{label}</small>
                                  <strong>{finding.title}</strong>
                                </span>
                                <span className={styles.clipTime}>
                                  {time(item.start_ms)}–{time(item.end_ms)}
                                </span>
                              </button>
                            ),
                          )}
                        </div>
                      ) : (
                        <p className={styles.empty}>
                          No source-linked moments were produced for this
                          report.
                        </p>
                      )}
                      {unlock("rewatch")}
                    </ReviewBlock>
                  </div>

                  <ReviewBlock
                    number="09"
                    title="Where the conversation changed"
                  >
                    {detail?.conversation_change ? (
                      <>
                        <div className={styles.sequence}>
                          {sourceNote(
                            detail.conversation_change.before,
                            "Before",
                          )}
                          {sourceNote(
                            detail.conversation_change.change,
                            "The change",
                          )}
                          {sourceNote(
                            detail.conversation_change.after,
                            "After",
                          )}
                        </div>
                        <p className={styles.why}>
                          <strong>Possible effect · inference:</strong>{" "}
                          {detail.conversation_change.possible_effect}
                        </p>
                      </>
                    ) : (
                      <p className={styles.empty}>
                        A first breakpoint and its cause-and-effect sequence
                        have not been established in this report.
                      </p>
                    )}
                  </ReviewBlock>
                </section>

                <section
                  className={styles.chapter}
                  data-chapter="practice"
                  id={`${prefix}-chapter-panel-practice`}
                  role="region"
                  aria-label="Practice and reflect"
                  tabIndex={0}
                  hidden={!reading && activeChapter !== "practice"}
                >
                  <div className={styles.chapterHeading}>
                    <span className={styles.chapterRange}>10—12</span>
                    <div>
                      <p className={styles.eyebrow}>PRACTICE AND REFLECT</p>
                      <h3>Turn the observation into a next-call move.</h3>
                    </div>
                    <span className={styles.chapterNote}>
                      Based on this call
                    </span>
                  </div>

                  <ReviewBlock
                    number="10"
                    title="Your sales skills"
                    description="What this call shows, based on the evidence."
                    tone="positive"
                    expanded
                  >
                    {supportedDimensions.length > 0 ? (
                      <div className={styles.skillLead} data-skill-summary>
                        <div className={styles.skillLeadIntro}>
                          <span
                            className={styles.skillMarkWrap}
                            aria-hidden="true"
                          >
                            <SkillMark />
                          </span>
                          <div>
                            <p className={styles.eyebrow}>
                              WHAT THIS CALL SHOWED
                            </p>
                            <p>
                              A small set of supported observations to carry
                              into your next conversation. Use them as a
                              starting point for practice.
                            </p>
                          </div>
                        </div>
                        <div className={styles.skillGrid}>
                          {supportedDimensions.map((dimension) => (
                            <article key={dimension.dimension_id}>
                              <strong>{dimension.label}</strong>
                              <p>{dimension.observation}</p>
                            </article>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className={styles.empty}>
                        No clear skill takeaway was recorded for this call.
                      </p>
                    )}
                  </ReviewBlock>

                  {detail?.ethics_notes.length ? (
                    <section
                      className={styles.ethicsBlock}
                      aria-label="Ethics observations"
                      hidden={
                        !reading && !showHeading && activeReviewNumber !== "10"
                      }
                    >
                      <div className={styles.ethicsHeading}>
                        <p className={styles.eyebrow}>HUMAN REVIEW NOTE</p>
                        <h3>Ethics observations</h3>
                        <p>
                          Source-linked notes for a human reviewer; no verdict
                          is assigned.
                        </p>
                      </div>
                      {detail.ethics_notes.map((note, index) => (
                        <div key={index}>
                          {sourceNote(
                            note,
                            "Ethics observation · for human review",
                          )}
                        </div>
                      ))}
                      {unlock("ethics_notes")}
                    </section>
                  ) : null}

                  <div id={focusId} className={styles.anchor}>
                    <ReviewBlock
                      number="11"
                      title="Your next-call focus"
                      description="One behaviour to take into your next conversation."
                      tone="priority"
                    >
                      {primary ? (
                        <div className={styles.focus}>
                          <Target size={24} aria-hidden="true" />
                          <div>
                            <h4>{primary.title}</h4>
                            <p>
                              {detail?.next_call_focus?.behavior ??
                                primary.explanation}
                            </p>
                            {detail?.next_call_focus && (
                              <p className={styles.target}>
                                <strong>Your target:</strong>{" "}
                                {detail.next_call_focus.target}
                              </p>
                            )}
                          </div>
                        </div>
                      ) : (
                        <p className={styles.empty}>
                          A next-call focus has not been identified yet.
                        </p>
                      )}
                    </ReviewBlock>
                  </div>

                  <ReviewBlock
                    number="12"
                    title="Personalized practice"
                    description="Rehearse the first improvement before your next call."
                  >
                    {detail?.practice && primary ? (
                      <div className={styles.practice}>
                        <h4>{primary.title}</h4>
                        <p>{detail.practice.instructions}</p>
                        <p>
                          <strong>You’ve done it when:</strong>{" "}
                          {detail.practice.success_condition}
                        </p>
                        {evidence(primary)}
                      </div>
                    ) : (
                      <p className={styles.empty}>
                        This saved report has no separately assessed drill or
                        success target yet.
                      </p>
                    )}
                  </ReviewBlock>
                </section>

                <section
                  className={styles.chapter}
                  data-chapter="close"
                  id={`${prefix}-chapter-panel-close`}
                  role="region"
                  aria-label="Close the loop"
                  tabIndex={0}
                  hidden={!reading && activeChapter !== "close"}
                >
                  <div className={styles.chapterHeading}>
                    <span className={styles.chapterRange}>13—14</span>
                    <div>
                      <p className={styles.eyebrow}>CLOSE THE LOOP</p>
                      <h3>Leave with a grounded takeaway.</h3>
                    </div>
                    <span className={styles.chapterNote}>
                      A single call cannot show a trend
                    </span>
                  </div>

                  <ReviewBlock number="13" title="Across-call pattern">
                    <p className={styles.empty}>
                      Comparable multi-call history is not supplied for this
                      report, so no trend or improvement claim is inferred.
                    </p>
                  </ReviewBlock>

                  <ReviewBlock number="14" title="Final verdict">
                    {!showHeading && (
                      <div className={styles.compactSourceContext}>
                        <h4>Call summary</h4>
                        <p>{report.summary}</p>
                        <p>{report.verdict}</p>
                        {detail?.diagnosis &&
                          sourceNote(detail.diagnosis, "Diagnosis")}
                        {detail?.outcome &&
                          sourceNote(
                            detail.outcome,
                            "Observed outcome · draft",
                          )}
                      </div>
                    )}
                    <p className={styles.verdict}>
                      {detail?.final_assessment.assessment ?? report.verdict}
                    </p>
                    {detail ? (
                      <div className={styles.sequence}>
                        <p>
                          <strong>Keep doing:</strong>{" "}
                          {detail.final_assessment.repeat}
                        </p>
                        <p>
                          <strong>Fix first:</strong>{" "}
                          {detail.final_assessment.fix_first}
                        </p>
                        <p>
                          <strong>One focus:</strong>{" "}
                          {detail.final_assessment.next_focus}
                        </p>
                      </div>
                    ) : (
                      primary && (
                        <p className={styles.finalFocus}>
                          <strong>Fix first:</strong> {primary.title}
                        </p>
                      )
                    )}
                  </ReviewBlock>
                  {(
                    [
                      ["objection_analysis", "Objections in your call"],
                      ["closing_analysis", "Closing and next steps"],
                    ] as const
                  ).map(
                    ([section, title]) =>
                      report[section].length > 0 && (
                        <section
                          key={section}
                          className={styles.block}
                          aria-label={title}
                          hidden={
                            !reading &&
                            !showHeading &&
                            activeReviewNumber !== "14"
                          }
                        >
                          <div className={styles.blockHeading}>
                            <h3>{title}</h3>
                          </div>
                          {report[section].map(findingCard)}
                          {unlock(section)}
                        </section>
                      ),
                  )}
                </section>
              </div>
            </FocusedReview.Provider>
          </ReviewDialog>
        </div>
      </div>
    </div>
  );
}
