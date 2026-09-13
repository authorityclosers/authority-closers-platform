"use client";

import { useId, useEffect, useRef, type ReactNode } from "react";
import { ArrowUpRight, Gem, Play, Target, TrendingUp } from "lucide-react";
import type { Finding, ReportEvidence, SalesReport } from "./report-contract";
import { FindingEvidence } from "./finding-evidence";
import { getReportUiCopy } from "./report-ui-copy";
import styles from "./dipak-overview.module.css";

type Props = {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
};

const time = (ms: number) =>
  `${Math.floor(ms / 60000)
    .toString()
    .padStart(2, "0")}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, "0")}`;

function ReviewBlock({
  number,
  title,
  description,
  children,
  tone = "neutral",
}: {
  number: string;
  title: string;
  description?: string;
  children: ReactNode;
  tone?: "neutral" | "positive" | "priority";
}) {
  const header = (
    <>
      <span className={styles.number}>{number}</span>
      <div>
        <h3>{title}</h3>
        {description && <p>{description}</p>}
      </div>
    </>
  );
  if (!["01", "02", "08", "11"].includes(number)) {
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
export function DipakOverview({ report, onSelectEvidence }: Props) {
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
  const focusId = `${prefix}-focus`;
  const fixesId = `${prefix}-fixes`;
  const rewatchId = `${prefix}-rewatch`;
  const primary = report.improvements[0];
  const detail = report.overview;
  const priorities = report.improvements.slice(0, 3);
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

  return (
    <div
      ref={overview}
      className={styles.overview}
      aria-label="Dipak’s call review"
    >
      <div className={styles.intro}>
        <div>
          <p className={styles.eyebrow}>YOUR COACHING OVERVIEW</p>
          <h2>
            Know what to repeat.
            <br />
            Know what to change.
          </h2>
        </div>
        <nav className={styles.shortcuts} aria-label="Jump within the overview">
          <a href={`#${fixesId}`}>
            Priority fixes <ArrowUpRight size={14} aria-hidden="true" />
          </a>
          <a href={`#${rewatchId}`}>
            Rewatch list <ArrowUpRight size={14} aria-hidden="true" />
          </a>
          <a href={`#${focusId}`}>
            Next-call focus <ArrowUpRight size={14} aria-hidden="true" />
          </a>
        </nav>
      </div>

      {(detail?.diagnosis || detail?.outcome) && (
        <div className={styles.callBrief}>
          {detail.diagnosis &&
            sourceNote(detail.diagnosis, "One-line diagnosis")}
          {detail.outcome &&
            sourceNote(detail.outcome, "Observed call outcome · draft")}
        </div>
      )}

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
            No source-linked strength is available to replay yet.
          </p>
        )}
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
                {sourceNote(missed.closer_response, "How the closer responded")}
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

      <ReviewBlock
        number="10"
        title="Authority Closers skill review"
        description="Evidence-based observations across the sales skills."
      >
        <div className={styles.skillGrid}>
          {report.dimensions.map((dimension) => (
            <div key={dimension.dimension_id}>
              <strong>{dimension.label}</strong>
              <span>
                {getReportUiCopy("en").factorStatus[dimension.status] ??
                  "Not assessed"}
              </span>
              <p>{dimension.observation}</p>
            </div>
          ))}
        </div>
        {detail?.ethics_notes.map((note, index) => (
          <div key={index}>
            {sourceNote(note, "Ethics observation · for human review")}
          </div>
        ))}
        <p className={styles.empty}>
          An overall score, closer level and ethics verdict are not approved for
          this draft.
        </p>
      </ReviewBlock>

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
            This saved report has no separately assessed drill or success target
            yet.
          </p>
        )}
      </ReviewBlock>

      {/* Template point 13 requires a comparable multi-call history; none is supplied by this contract. */}
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
    </div>
  );
}
