"use client";

import { useId, useEffect, useRef, useState, type ReactNode } from "react";
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
import styles from "./dipak-overview.module.css";

type Props = {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
};

const chapterNavigation = [
  {
    id: "start",
    range: "01—04",
    label: "Start here",
    hint: "Takeaway and first change",
  },
  {
    id: "read",
    range: "05—09",
    label: "Read the call",
    hint: "Moments and missed turns",
  },
  {
    id: "practice",
    range: "10—12",
    label: "Practice",
    hint: "Skills and next move",
  },
  {
    id: "close",
    range: "13—14",
    label: "Close the loop",
    hint: "Takeaway and limits",
  },
] as const;
type ChapterId = (typeof chapterNavigation)[number]["id"];

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
  const header = (
    <>
      <span className={styles.number}>{number}</span>
      <div className={styles.blockHeadingCopy}>
        <h3>{title}</h3>
        {description && <p>{description}</p>}
      </div>
    </>
  );
  if (!expanded && !["01", "02", "08", "11"].includes(number)) {
    return (
      <details
        className={`${styles.block} ${styles.fold}`}
        data-review-fold
        data-tone={tone}
        data-review-point={number}
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
    >
      <div className={styles.blockHeading}>{header}</div>
      {children}
    </section>
  );
}

/** A source-preserving presentation of Dipak's template, not a second judge. */
export function DipakOverview({ report, onSelectEvidence, onUnlock }: Props) {
  const overview = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let previous: Map<HTMLDetailsElement, boolean> | null = null;
    const beforePrint = () => {
      if (previous) return;
      previous = new Map(
        [
          ...(overview.current?.querySelectorAll<HTMLDetailsElement>(
            "[data-review-fold]",
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
  const [activeChapter, setActiveChapter] = useState<ChapterId>("start");
  const focusId = `${prefix}-focus`;
  const fixesId = `${prefix}-fixes`;
  const rewatchId = `${prefix}-rewatch`;

  function selectChapter(index: number) {
    const chapter = chapterNavigation[index];
    if (chapter) setActiveChapter(chapter.id);
  }
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

  function evidence(finding: Finding) {
    return (
      <FindingEvidence count={finding.evidence.length}>
        {finding.evidence.map((item, index) => (
          <blockquote key={`${item.segment_id}-${index}`}>
            <button
              className={styles.timestamp}
              type="button"
              onClick={() => onSelectEvidence(item, finding.title)}
              aria-label={`Play source moment, ${time(item.start_ms)} to ${time(item.end_ms)}: ${item.quote}`}
            >
              <Play size={12} aria-hidden="true" />
              {time(item.start_ms)}–{time(item.end_ms)}
            </button>{" "}
            <span>{item.quote}</span>
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
    >
      <div className={styles.intro}>
        <div>
          <p className={styles.eyebrow}>CALL REVIEW</p>
          <h2>A clear next step</h2>
          <p className={styles.heroSubcopy}>
            Start with the takeaway, then open the source moment behind it.
          </p>
        </div>
        <nav className={styles.shortcuts} aria-label="Jump within the overview">
          <a href={`#${fixesId}`} onClick={() => setActiveChapter("start")}>
            Priority fixes <ArrowUpRight size={14} aria-hidden="true" />
          </a>
          <a href={`#${rewatchId}`} onClick={() => setActiveChapter("read")}>
            Rewatch list <ArrowUpRight size={14} aria-hidden="true" />
          </a>
          <a href={`#${focusId}`} onClick={() => setActiveChapter("practice")}>
            Next-call focus <ArrowUpRight size={14} aria-hidden="true" />
          </a>
        </nav>
        <div className={styles.heroMeta} aria-label="Report status">
          <span className={styles.statusPill}>Draft report</span>
          <span>{report.source_label}</span>
        </div>
      </div>

      <section className={styles.summaryDeck} aria-label="Report at a glance">
        <article
          className={`${styles.summaryCard} ${styles.summaryCardLead}`}
          data-summary-card="summary"
        >
          <p className={styles.eyebrow}>TAKEAWAY FOR THIS CALL</p>
          <p className={styles.summaryText}>
            {detail?.final_assessment.assessment ?? report.verdict}
          </p>
          <span className={styles.summaryMeta}>
            {report.review_status === "draft_not_dipak_adjudicated"
              ? "Draft · Dipak review pending"
              : "Review status is recorded in the report"}
          </span>
        </article>
        <article className={styles.summaryCard} data-summary-card="keep">
          <p className={styles.eyebrow}>KEEP IN THE NEXT CALL</p>
          {report.strengths.length ? (
            <ul className={styles.summaryList}>
              {report.strengths.slice(0, 2).map((finding, index) => (
                <li key={`${finding.title}-${index}`}>
                  <span aria-hidden="true">+</span>
                  <strong>{finding.title}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.summaryEmpty}>
              No supported strength recorded.
            </p>
          )}
        </article>
        <article className={styles.summaryCard} data-summary-card="change">
          <p className={styles.eyebrow}>CHANGE FIRST</p>
          {primary ? (
            <>
              <strong className={styles.summaryPriority}>
                {primary.title}
              </strong>
              <span className={styles.summaryMeta}>
                Start with one behaviour.
              </span>
            </>
          ) : (
            <p className={styles.summaryEmpty}>
              No supported improvement recorded.
            </p>
          )}
        </article>
      </section>

      {(detail?.diagnosis || detail?.outcome) && (
        <div className={styles.callBrief}>
          {detail.diagnosis &&
            sourceNote(detail.diagnosis, "One-line diagnosis")}
          {detail.outcome &&
            sourceNote(detail.outcome, "Observed call outcome · draft")}
        </div>
      )}

      <nav
        className={styles.chapterNav}
        aria-label="Report sections"
        role="tablist"
      >
        {chapterNavigation.map((chapter, index) => {
          const tabId = `${prefix}-chapter-tab-${chapter.id}`;
          const panelId = `${prefix}-chapter-panel-${chapter.id}`;
          const selected = activeChapter === chapter.id;
          return (
            <button
              key={chapter.id}
              type="button"
              role="tab"
              id={tabId}
              aria-controls={panelId}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActiveChapter(chapter.id)}
              onKeyDown={(event) => {
                let next: number;
                if (event.key === "ArrowRight")
                  next = (index + 1) % chapterNavigation.length;
                else if (event.key === "ArrowLeft")
                  next =
                    (index + chapterNavigation.length - 1) %
                    chapterNavigation.length;
                else if (event.key === "Home") next = 0;
                else if (event.key === "End")
                  next = chapterNavigation.length - 1;
                else return;
                event.preventDefault();
                selectChapter(next);
                document
                  .getElementById(
                    `${prefix}-chapter-tab-${chapterNavigation[next].id}`,
                  )
                  ?.focus();
              }}
            >
              <span className={styles.chapterRange}>{chapter.range}</span>
              <span>
                <strong>{chapter.label}</strong>
                <small>{chapter.hint}</small>
              </span>
            </button>
          );
        })}
      </nav>

      <section
        className={styles.chapter}
        data-chapter="start"
        id={`${prefix}-chapter-panel-start`}
        role="tabpanel"
        aria-labelledby={`${prefix}-chapter-tab-start`}
        tabIndex={0}
        hidden={activeChapter !== "start"}
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
                    <>
                      {sourceNote(fix.what_happened, "What happened")}
                      <p className={styles.label}>Why it matters</p>
                      <p>{fix.why_it_matters}</p>
                      <p className={styles.label}>Do this instead</p>
                      <p>{fix.replacement_behavior}</p>
                    </>
                  ) : (
                    <>
                      <p className={styles.label}>What to do differently</p>
                      <p>{finding.explanation}</p>
                      {evidence(finding)}
                    </>
                  );
                })()}
                <div className={styles.impact}>
                  <TrendingUp size={16} aria-hidden="true" />
                  <div>
                    <strong>Business impact</strong>
                    <p>Insufficient data for a reliable estimate.</p>
                    <small>
                      {detail?.improvement_details
                        .find((item) => item.finding_index === index)
                        ?.business_impact.missing_inputs.join(" · ") ??
                        "Lead volume, conversion history and time or revenue data are needed to calculate this."}
                    </small>
                  </div>
                </div>
              </ReviewBlock>
            ))
          ) : (
            <p className={styles.empty}>
              This report has no supported improvement to prioritise yet.
            </p>
          )}
          {unlock("improvements")}
        </div>
      </section>

      <section
        className={styles.chapter}
        data-chapter="read"
        id={`${prefix}-chapter-panel-read`}
        role="tabpanel"
        aria-labelledby={`${prefix}-chapter-tab-read`}
        tabIndex={0}
        hidden={activeChapter !== "read"}
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
                  {sourceNote(missed.prospect_signal, "What the prospect said")}
                  {sourceNote(missed.closer_response, "How you responded")}
                  <p>
                    <strong>Explore next:</strong> {missed.follow_up}
                  </p>
                  <p>
                    <strong>Possible value:</strong> {missed.potential_impact}
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

        <ReviewBlock number="07" title="What the prospect may have meant">
          {detail?.prospect_interpretations.length ? (
            <>
              <p className={styles.empty}>
                Possible interpretations to check, not facts about the person.
              </p>
              {detail.prospect_interpretations.map((item, index) => (
                <div className={styles.interpretation} key={index}>
                  {sourceNote(item.source, "What was said")}
                  <div>
                    <p className={styles.label}>Possible concern · inference</p>
                    <p>{item.possible_concern}</p>
                  </div>
                </div>
              ))}
            </>
          ) : (
            <p className={styles.empty}>
              No separate interpretation is recorded in this report. The
              transcript preserves what was said; an underlying concern needs
              supporting evidence.
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
                {rewatch.map(({ finding, evidence: item, label, kind }) => (
                  <button
                    type="button"
                    key={`${item.segment_id}:${item.start_ms}:${item.end_ms}`}
                    data-kind={kind}
                    onClick={() => onSelectEvidence(item, finding.title)}
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
                ))}
              </div>
            ) : (
              <p className={styles.empty}>
                No source-linked moments were produced for this report.
              </p>
            )}
            {unlock("rewatch")}
          </ReviewBlock>
        </div>

        <ReviewBlock number="09" title="Where the conversation changed">
          {detail?.conversation_change ? (
            <>
              <div className={styles.sequence}>
                {sourceNote(detail.conversation_change.before, "Before")}
                {sourceNote(detail.conversation_change.change, "The change")}
                {sourceNote(detail.conversation_change.after, "After")}
              </div>
              <p className={styles.why}>
                <strong>Possible effect · inference:</strong>{" "}
                {detail.conversation_change.possible_effect}
              </p>
            </>
          ) : (
            <p className={styles.empty}>
              A first breakpoint and its cause-and-effect sequence have not been
              established in this report.
            </p>
          )}
        </ReviewBlock>
      </section>

      <section
        className={styles.chapter}
        data-chapter="practice"
        id={`${prefix}-chapter-panel-practice`}
        role="tabpanel"
        aria-labelledby={`${prefix}-chapter-tab-practice`}
        tabIndex={0}
        hidden={activeChapter !== "practice"}
      >
        <div className={styles.chapterHeading}>
          <span className={styles.chapterRange}>10—12</span>
          <div>
            <p className={styles.eyebrow}>PRACTICE AND REFLECT</p>
            <h3>Turn the observation into a next-call move.</h3>
          </div>
          <span className={styles.chapterNote}>Based on this call</span>
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
                <span className={styles.skillMarkWrap} aria-hidden="true">
                  <SkillMark />
                </span>
                <div>
                  <p className={styles.eyebrow}>WHAT THIS CALL SHOWED</p>
                  <p>
                    A small set of supported observations to carry into your
                    next conversation. Use them as a starting point for
                    practice.
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
          >
            <div className={styles.ethicsHeading}>
              <p className={styles.eyebrow}>HUMAN REVIEW NOTE</p>
              <h3>Ethics observations</h3>
              <p>
                Source-linked notes for a human reviewer; no verdict is
                assigned.
              </p>
            </div>
            {detail.ethics_notes.map((note, index) => (
              <div key={index}>
                {sourceNote(note, "Ethics observation · for human review")}
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
                    {detail?.next_call_focus?.behavior ?? primary.explanation}
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
              This saved report has no separately assessed drill or success
              target yet.
            </p>
          )}
        </ReviewBlock>
      </section>

      <section
        className={styles.chapter}
        data-chapter="close"
        id={`${prefix}-chapter-panel-close`}
        role="tabpanel"
        aria-labelledby={`${prefix}-chapter-tab-close`}
        tabIndex={0}
        hidden={activeChapter !== "close"}
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
            Comparable multi-call history is not supplied for this report, so no
            trend or improvement claim is inferred.
          </p>
        </ReviewBlock>

        <ReviewBlock number="14" title="Final verdict">
          <p className={styles.verdict}>
            {detail?.final_assessment.assessment ?? report.verdict}
          </p>
          {detail ? (
            <div className={styles.sequence}>
              <p>
                <strong>Keep doing:</strong> {detail.final_assessment.repeat}
              </p>
              <p>
                <strong>Fix first:</strong> {detail.final_assessment.fix_first}
              </p>
              <p>
                <strong>One focus:</strong> {detail.final_assessment.next_focus}
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
  );
}
