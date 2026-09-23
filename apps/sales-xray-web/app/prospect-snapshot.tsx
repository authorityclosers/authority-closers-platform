"use client";

import { ArrowRight, CircleHelp, LockKeyhole, Play, Quote } from "lucide-react";
import type { ReportEvidence, SalesReport } from "./report-contract";
import { formatTranscriptTime } from "./report-transcript";
import styles from "./prospect-snapshot.module.css";

export type ProspectSnapshotProps = {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
};

function sourceAction(
  evidence: ReportEvidence,
  index: number,
  onSelectEvidence: ProspectSnapshotProps["onSelectEvidence"],
) {
  const start = formatTranscriptTime(evidence.start_ms);
  const end = formatTranscriptTime(evidence.end_ms);
  return (
    <button
      type="button"
      className={styles.sourceAction}
      aria-label={`Play source moment, ${start} to ${end}`}
      onClick={() => onSelectEvidence(evidence, `Prospect signal ${index + 1}`)}
    >
      <span className={styles.play} aria-hidden="true">
        <Play size={16} />
      </span>
      <span className={styles.actionCopy}>
        <strong>Play source moment</strong>
        <small>
          {start}–{end}
        </small>
      </span>
      <ArrowRight size={17} aria-hidden="true" />
    </button>
  );
}

export function ProspectSnapshot({
  report,
  onSelectEvidence,
  onUnlock,
}: ProspectSnapshotProps) {
  const interpretations = report.overview?.prospect_interpretations ?? [];
  const preview = report.preview?.sections.prospect_interpretations;
  const hiddenCount = preview?.hidden_count ?? 0;
  const visibleCount = preview?.visible_count ?? interpretations.length;
  const totalCount = preview?.total_count ?? interpretations.length;

  return (
    <section
      className={styles.snapshot}
      aria-label="Prospect snapshot"
      data-prospect-snapshot
    >
      <header className={styles.header}>
        <div className={styles.headingCopy}>
          <p className={styles.eyebrow}>POINT-IN-TIME · THIS CALL ONLY</p>
          <h2>Prospect snapshot</h2>
          <p>
            Source-linked observations and possible meanings from this report.
            Possible concerns are hypotheses, not facts about a person.
          </p>
        </div>
        <span className={styles.headerIcon} aria-hidden="true">
          <Quote size={23} />
        </span>
      </header>

      {interpretations.length ? (
        <div className={styles.cards}>
          {interpretations.map((item, index) => (
            <article
              key={`${item.source.evidence[0]?.segment_id ?? "source"}-${index}`}
              className={styles.card}
              data-prospect-index={index}
            >
              <header className={styles.cardHeader}>
                <span className={styles.number} aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <p className={styles.eyebrow}>SOURCE-LINKED SIGNAL</p>
                  <h3>What was said and what it may mean</h3>
                </div>
              </header>

              <div className={styles.columns}>
                <section
                  className={styles.sourcePanel}
                  aria-label={`Source for prospect signal ${index + 1}`}
                  data-prospect-part="source"
                >
                  <p className={styles.sectionLabel}>Report observation</p>
                  <p className={styles.observation}>{item.source.text}</p>
                  <div
                    className={styles.verbatim}
                    data-prospect-part="verbatim"
                  >
                    <h4>Verbatim source</h4>
                    {item.source.evidence.map((evidence, evidenceIndex) => (
                      <figure
                        className={styles.excerpt}
                        key={`${evidence.segment_id}:${evidence.start_ms}:${evidenceIndex}`}
                      >
                        <blockquote>
                          <Quote size={18} aria-hidden="true" />
                          <span>{evidence.quote}</span>
                        </blockquote>
                        <figcaption>
                          {sourceAction(evidence, index, onSelectEvidence)}
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                </section>

                <section
                  className={styles.hypothesis}
                  aria-label={`Possible concern hypothesis ${index + 1}`}
                  data-prospect-part="hypothesis"
                >
                  <div className={styles.hypothesisLabel}>
                    <CircleHelp size={18} aria-hidden="true" />
                    <p className={styles.sectionLabel}>Possible concern</p>
                  </div>
                  <p className={styles.hypothesisTag}>
                    Hypothesis · not a fact
                  </p>
                  <p className={styles.hypothesisText}>
                    {item.possible_concern}
                  </p>
                  <p className={styles.hypothesisNote}>
                    This interpretation is not confirmed by the cited words.
                  </p>
                </section>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className={styles.empty} data-prospect-empty>
          <CircleHelp size={24} aria-hidden="true" />
          <div>
            <h3>No separate prospect interpretation</h3>
            <p>
              This report supplies no source-linked prospect interpretation.
              Missing information does not establish whether a concern was
              present.
            </p>
          </div>
        </div>
      )}

      <aside className={styles.boundary} aria-label="Limits of this snapshot">
        <strong>What remains unknown</strong>
        <p>
          This view reflects this report only. It does not establish an ongoing
          prospect profile or what happened after the call.
        </p>
      </aside>

      {hiddenCount > 0 && (
        <aside
          className={styles.locked}
          data-preview-section="prospect_interpretations"
          data-visible-count={visibleCount}
          data-total-count={totalCount}
          aria-label="More prospect interpretations in the full report"
        >
          <span className={styles.lockIcon} aria-hidden="true">
            <LockKeyhole size={19} />
          </span>
          <div className={styles.lockCopy}>
            <strong>
              {hiddenCount} more prospect{" "}
              {hiddenCount === 1 ? "interpretation" : "interpretations"} in your
              report
            </strong>
            <p>Unlock remaining interpretations with a free account.</p>
          </div>
          {onUnlock && (
            <button type="button" className={styles.unlock} onClick={onUnlock}>
              Continue free <ArrowRight size={16} aria-hidden="true" />
            </button>
          )}
        </aside>
      )}
    </section>
  );
}
