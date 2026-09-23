"use client";

import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  AudioLines,
  BookOpen,
  Filter,
  GraduationCap,
  Handshake,
  Lightbulb,
  MessagesSquare,
  Play,
  Presentation,
  ShieldCheck,
  Target,
  Users,
} from "lucide-react";
import type { ReportDimension, ReportEvidence } from "./report-contract";
import { formatTranscriptTime } from "./report-transcript";
import { getReportUiCopy } from "./report-ui-copy";
import { ReviewDialog } from "./review-dialog";
import styles from "./sales-skills.module.css";

// Colour identifies a topic, never its performance. Labels and observations
// remain the server's eight dimensions; citations are not timed audio evidence.
const topics = {
  human_connection_trust: { icon: Users, tone: "blue" },
  discovery_deep_understanding: { icon: MessagesSquare, tone: "mint" },
  qualification: { icon: Filter, tone: "violet" },
  problem_impact_desire: { icon: Target, tone: "orange" },
  solution_relevance_presentation: { icon: Presentation, tone: "rose" },
  certainty_objection_intelligence: { icon: ShieldCheck, tone: "cyan" },
  closing_decision_management: { icon: Handshake, tone: "orange" },
  communication_tonality: { icon: AudioLines, tone: "violet" },
} as const;

type SkillDimension = ReportDimension & { evidence?: ReportEvidence[] };

export function SalesSkills({
  dimensions,
  onSelectEvidence,
}: {
  dimensions: SkillDimension[];
  onSelectEvidence?: (evidence: ReportEvidence) => void;
}) {
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedIndex = dimensions.findIndex(
    (item) => item.dimension_id === selectedId,
  );
  const selected = dimensions[selectedIndex];
  const excerpts = selected?.evidence ?? [];
  const pageCount = Math.max(1, Math.ceil(dimensions.length / 4));
  const activePage = Math.min(page, pageCount - 1);
  const copy = getReportUiCopy();
  return (
    <section className={styles.skills} aria-label="Sales skills">
      <header className={styles.banner}>
        <span className={styles.bannerIcon}>
          <GraduationCap aria-hidden="true" />
        </span>
        <div>
          <h2>Build your sales skills</h2>
          <p>
            Read the observations from this call. Choose one skill to focus on
            next.
          </p>
          <small>Draft observations, not scores.</small>
        </div>
        <span className={styles.tip}>
          <Lightbulb aria-hidden="true" /> One skill at a time.
        </span>
      </header>
      {!dimensions.length ? (
        <p className={styles.empty}>
          No skill observations were supplied for this call.
        </p>
      ) : (
        <>
          <div className={styles.grid}>
            {dimensions.map((dimension, index) => {
              const topic = topics[
                dimension.dimension_id as keyof typeof topics
              ] ?? { icon: BookOpen, tone: "blue" };
              const Icon = topic.icon;
              return (
                <article
                  key={dimension.dimension_id}
                  className={styles.card}
                  data-tone={topic.tone}
                  data-page-visible={Math.floor(index / 4) === activePage}
                >
                  <div className={styles.cardHeading}>
                    <span className={styles.icon}>
                      <Icon aria-hidden="true" />
                    </span>
                    <h3>{dimension.label}</h3>
                  </div>
                  <span className={styles.status}>
                    {copy.factorStatus[dimension.status] ??
                      copy.factorStatus.unknown}
                  </span>
                  <p className={styles.observation}>{dimension.observation}</p>
                  <button
                    type="button"
                    className={styles.open}
                    onClick={() => setSelectedId(dimension.dimension_id)}
                    aria-label={`Open notes: ${dimension.label}`}
                  >
                    Open notes <ArrowRight size={16} aria-hidden="true" />
                  </button>
                </article>
              );
            })}
          </div>
          <nav className={styles.pagination} aria-label="Skill pages">
            <span aria-live="polite">
              Skills {activePage * 4 + 1}–
              {Math.min((activePage + 1) * 4, dimensions.length)} of{" "}
              {dimensions.length}
            </span>
            <button
              type="button"
              aria-label="Previous skills"
              disabled={activePage === 0}
              onClick={() => setPage(activePage - 1)}
            >
              <ArrowLeft size={19} />
            </button>
            <button
              type="button"
              aria-label="Next skills"
              disabled={activePage === pageCount - 1}
              onClick={() => setPage(activePage + 1)}
            >
              <ArrowRight size={19} />
            </button>
          </nav>
        </>
      )}
      {selected && (
        <ReviewDialog
          open
          title={selected.label}
          position={`Skill ${selectedIndex + 1} of ${dimensions.length}`}
          eyebrow="Draft observation · not a performance score"
          onClose={() => setSelectedId(null)}
          onPrevious={() =>
            setSelectedId(dimensions[selectedIndex - 1].dimension_id)
          }
          onNext={() =>
            setSelectedId(dimensions[selectedIndex + 1].dimension_id)
          }
          previousDisabled={selectedIndex === 0}
          nextDisabled={selectedIndex === dimensions.length - 1}
          previousLabel="Previous skill"
          nextLabel="Next skill"
          closeLabel="Close skill notes"
        >
          <div className={styles.notes}>
            <span className={styles.status}>
              {copy.factorStatus[selected.status] ?? copy.factorStatus.unknown}
            </span>
            <h3>Report observation</h3>
            <p>{selected.observation}</p>
            <section className={styles.source} aria-label="Recording excerpts">
              <h3>From the recording</h3>
              {excerpts.length ? (
                <ol className={styles.excerpts}>
                  {excerpts.map((evidence, index) => (
                    <li key={`${evidence.segment_id}-${index}`}>
                      <span className={styles.sourceTime}>
                        {formatTranscriptTime(evidence.start_ms)}–
                        {formatTranscriptTime(evidence.end_ms)} · Source segment{" "}
                        {evidence.segment_id}
                      </span>
                      <blockquote>{evidence.quote}</blockquote>
                      {onSelectEvidence && (
                        <button
                          type="button"
                          className={styles.listen}
                          onClick={() => {
                            setSelectedId(null);
                            onSelectEvidence(evidence);
                          }}
                          aria-label={`Listen to ${selected.label} excerpt at ${formatTranscriptTime(evidence.start_ms)}`}
                        >
                          <Play size={15} fill="currentColor" aria-hidden="true" />
                          Listen to this excerpt
                        </button>
                      )}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className={styles.noSource}>
                  No recording excerpt was supplied for this skill.
                </p>
              )}
            </section>
            {!!selected.citations.length && (
              <aside className={styles.references}>
                <h3>
                  <BookOpen size={18} aria-hidden="true" /> Coaching references
                </h3>
                <p>
                  Document references supplied with this observation; not
                  recording timestamps.
                </p>
                <ul>
                  {selected.citations.map((citation, index) => (
                    <li key={`${citation.doc}-${index}`}>
                      <strong>{citation.doc}</strong> ·{" "}
                      {citation.sections.join(", ")}
                    </li>
                  ))}
                </ul>
              </aside>
            )}
          </div>
        </ReviewDialog>
      )}
    </section>
  );
}
