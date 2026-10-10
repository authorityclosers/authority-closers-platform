"use client";

import Link from "next/link";
import type { DocumentReportData } from "./report-document-data";
import type { ReportEvidence, SalesReport } from "./report-contract";
import { REPORT_SKILLS } from "./report-pillars";
import { RichText } from "./report-entities";
import { Clip } from "./report-kit";
import { formatClock } from "./lightbox/time";
import {
  buildContextualSourcePlayback,
  type ContextualSourcePlayback,
} from "./source-playback-context";
import styles from "./report-call-coaching.module.css";

/** A retained finding supplies a suggestion, never a new diagnosis or score. */
export function callCoachingFocus(report: SalesReport) {
  if (report.preview) return null;
  const proposed = report.overview?.next_call_focus;
  const proposedFinding = proposed
    ? report.improvements[proposed.improvement_index]
    : undefined;
  const index = proposedFinding?.evidence.length
    ? proposed!.improvement_index
    : report.improvements.findIndex((finding) => finding.evidence.length);
  const improvement = index >= 0;
  const finding = improvement
    ? report.improvements[index]
    : report.strengths.find((item) => item.evidence.length);
  if (!finding) return null;
  const linkedFocus =
    improvement && proposed?.improvement_index === index ? proposed : null;
  const detail = improvement
    ? report.overview?.improvement_details.find(
        (item) => item.finding_index === index,
      )
    : null;
  const matchingSkills = report.dimensions.filter(
    (dimension) =>
      REPORT_SKILLS.some(([id]) => id === dimension.dimension_id) &&
      ["observed", "partial"].includes(dimension.status) &&
      dimension.evidence?.some((source) =>
        finding.evidence.some(
          (ref) =>
            ref.segment_id === source.segment_id &&
            ref.start_ms === source.start_ms &&
            ref.end_ms === source.end_ms &&
            ref.quote === source.quote,
        ),
      ),
  );
  return {
    finding,
    improvement,
    behavior: linkedFocus?.behavior ?? finding.title,
    target: linkedFocus?.target ?? null,
    replacement: detail?.replacement_behavior ?? null,
    why: detail?.why_it_matters ?? null,
    practice:
      improvement && report.overview?.practice?.improvement_index === index
        ? report.overview.practice
        : null,
    // Shared words alone cannot disambiguate two assessed skills.
    skillId:
      matchingSkills.length === 1 ? matchingSkills[0].dimension_id : null,
  };
}

export function ReportCallCoaching({
  data,
  onSelectEvidence,
  onSelectContextualPlayback,
}: {
  data: DocumentReportData;
  onSelectEvidence?: (source: ReportEvidence, title: string) => void;
  onSelectContextualPlayback?: (
    source: ContextualSourcePlayback,
    title: string,
  ) => void;
}) {
  const report = data.report;
  if (!report || report.preview) return null;
  const focus = callCoachingFocus(report);
  return (
    <div className={styles.coaching} data-call-coaching>
      <p className={styles.context}>
        A suggestion from this call’s report. One call does not establish a
        recurring pattern.
      </p>
      {focus ? (
        <>
          <section aria-label="Focus for this call">
            <h3>{focus.improvement ? "One focus" : "Keep doing"}</h3>
            <p className={styles.focus}>
              <RichText text={focus.behavior} />
            </p>
          </section>
          <section aria-label="Why this focus">
            <h3>What happened on this call</h3>
            <p>
              <RichText text={focus.finding.explanation} />
            </p>
            {focus.why && (
              <p>
                <span className={styles.label}>Why it may matter · </span>
                <RichText text={focus.why} />
              </p>
            )}
            <div className={styles.sources}>
              {focus.finding.evidence.map((source, index) => {
                const playback =
                  data.transcript && onSelectContextualPlayback
                    ? buildContextualSourcePlayback(
                        report,
                        data.transcript,
                        source,
                      )
                    : null;
                return onSelectEvidence ? (
                  <Clip
                    key={index}
                    evidence={source}
                    title="Coaching for this call"
                    onPlay={onSelectEvidence}
                    context={
                      playback && onSelectContextualPlayback
                        ? { playback, onPlay: onSelectContextualPlayback }
                        : null
                    }
                  />
                ) : (
                  <figure key={index}>
                    <figcaption>
                      {formatClock(source.start_ms)}–
                      {formatClock(source.end_ms)}
                    </figcaption>
                    <blockquote>
                      <RichText text={source.quote} />
                    </blockquote>
                  </figure>
                );
              })}
            </div>
          </section>
          <section aria-label="What to try">
            <h3>
              {focus.improvement
                ? "Try this next time"
                : "Carry this into the next call"}
            </h3>
            <p>
              <RichText text={focus.replacement ?? focus.behavior} />
            </p>
            {focus.replacement && (
              <small>
                Suggested wording or behavior from the report; not a quote from
                the call.
              </small>
            )}
          </section>
          <section aria-label="Next-call mission">
            <h3>Your next-call mission</h3>
            <p>
              <RichText text={focus.behavior} />
            </p>
            {focus.target ? (
              <p>
                <span className={styles.label}>Done when · </span>
                <RichText text={focus.target} />
              </p>
            ) : (
              <p className={styles.context}>
                This report did not supply a success check. Decide what you will
                look for before your next call.
              </p>
            )}
            {focus.practice && (
              <div className={styles.practice}>
                <h4>Practise once</h4>
                <p>
                  <RichText text={focus.practice.instructions} />
                </p>
                <p>
                  <span className={styles.label}>Done when · </span>
                  <RichText text={focus.practice.success_condition} />
                </p>
              </div>
            )}
          </section>
        </>
      ) : (
        <p>
          No source-backed focus was supplied for this call. Choose a skill to
          work on below.
        </p>
      )}
      <div className={styles.links}>
        <Link
          prefetch={false}
          href={
            focus?.skillId ? `/coaching?focus=${focus.skillId}` : "/coaching"
          }
        >
          My coaching across calls
        </Link>
        {!focus &&
          REPORT_SKILLS.map(([id, label]) => (
            <Link key={id} prefetch={false} href={`/coaching?focus=${id}`}>
              {label}
            </Link>
          ))}
      </div>
    </div>
  );
}
