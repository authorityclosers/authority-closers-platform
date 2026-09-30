"use client";

import type { ReportEvidence } from "./report-contract";
import { formatClock } from "./lightbox/time";
import { ClipListenButton } from "./source-waveform";
import type {
  CallRecord,
  CallRecordEvidence,
  CallRecordFact,
  CallRecordSpeaker,
} from "./call-record-contract";
import styles from "./call-record.module.css";

export const CANONICAL_TAG_GROUPS = [
  "People",
  "Business details",
  "Next steps and commitments",
  "Concerns",
] as const;

export type CallRecordProps = {
  callRecord: CallRecord | null;
  onSelectEvidence?: (evidence: ReportEvidence, title: string) => void;
};

function formatSpeakerName(id: string): string {
  const normalized = id.trim().toLowerCase();
  if (normalized === "rep") return "Rep";
  if (normalized === "buyer") return "Buyer";
  if (normalized === "closer") return "Closer";
  if (normalized === "prospect") return "Prospect";
  return id.charAt(0).toUpperCase() + id.slice(1);
}

function NumbersCard({ record }: { record: CallRecord }) {
  const { duration_ms, speakers, overlaps } = record.numbers;

  // Determine who talked most
  const sortedByShare = [...speakers].sort(
    (a, b) => b.talk_share - a.talk_share,
  );
  const highestSpeaker = sortedByShare[0];
  const isTied =
    sortedByShare.length > 1 &&
    sortedByShare[0].talk_share === sortedByShare[1].talk_share;

  const whoTalkedMostLabel = isTied
    ? "Both speakers had equal talk share."
    : highestSpeaker
      ? `Who talked most: ${formatSpeakerName(highestSpeaker.speaker_id)} (${Math.round(highestSpeaker.talk_share * 100)}%)`
      : "Talk share not available.";

  // Questions summary
  const questionsLabel = speakers.length
    ? `Questions asked: ${speakers
        .map((s) => `${formatSpeakerName(s.speaker_id)} asked ${s.questions}`)
        .join(", ")}`
    : "Questions asked: none recorded";

  // Longest monologue
  const sortedByMonologue = [...speakers].sort(
    (a, b) => b.longest_monologue_ms - a.longest_monologue_ms,
  );
  const longestSpeaker = sortedByMonologue[0];
  const longestMonologueLabel = longestSpeaker
    ? `Longest monologue: ${formatSpeakerName(longestSpeaker.speaker_id)} (${formatClock(longestSpeaker.longest_monologue_ms)})`
    : "Longest monologue: none recorded";

  const overlapsLabel = `Times speakers talked at once: ${overlaps}`;
  const durationLabel = `Total call duration: ${formatClock(duration_ms)}`;

  return (
    <article className={styles.numbersCard} aria-label="Call numbers">
      <header className={styles.cardHeader}>
        <h3 className={styles.cardTitle}>Call numbers</h3>
        <span className={styles.durationBadge}>{formatClock(duration_ms)}</span>
      </header>

      {/* Talk share bar */}
      <div className={styles.talkShareWrapper}>
        <div
          className={styles.talkShareBar}
          role="img"
          aria-label={whoTalkedMostLabel}
        >
          {speakers.map((spk, idx) => {
            const widthPct = Math.max(0, Math.min(100, spk.talk_share * 100));
            if (widthPct === 0) return null;
            const isRep =
              spk.speaker_id.toLowerCase() === "rep" ||
              spk.speaker_id.toLowerCase() === "closer";
            return (
              <div
                key={spk.speaker_id}
                className={`${styles.talkShareSegment} ${isRep ? styles.repSegment : styles.buyerSegment}`}
                style={{ width: `${widthPct}%` }}
                title={`${formatSpeakerName(spk.speaker_id)}: ${Math.round(widthPct)}%`}
              >
                {widthPct >= 15 ? `${Math.round(widthPct)}%` : ""}
              </div>
            );
          })}
        </div>

        <div className={styles.talkShareLegend}>
          {speakers.map((spk) => {
            const isRep =
              spk.speaker_id.toLowerCase() === "rep" ||
              spk.speaker_id.toLowerCase() === "closer";
            return (
              <span key={spk.speaker_id} className={styles.legendItem}>
                <span
                  className={`${styles.legendDot} ${isRep ? styles.repSegment : styles.buyerSegment}`}
                  aria-hidden="true"
                />
                <strong>{formatSpeakerName(spk.speaker_id)}</strong>:{" "}
                {Math.round(spk.talk_share * 100)}%
              </span>
            );
          })}
        </div>
        <p className={styles.metricPlainLabel}>{whoTalkedMostLabel}</p>
      </div>

      <div className={styles.numbersGrid}>
        <div className={styles.metricBlock}>
          <span className={styles.metricTitle}>Call duration</span>
          <span className={styles.metricValue}>{formatClock(duration_ms)}</span>
          <p className={styles.metricPlainLabel}>{durationLabel}</p>
        </div>

        <div className={styles.metricBlock}>
          <span className={styles.metricTitle}>Questions</span>
          <span className={styles.metricValue}>
            {speakers.map((s) => s.questions).reduce((a, b) => a + b, 0)}
          </span>
          <p className={styles.metricPlainLabel}>{questionsLabel}</p>
        </div>

        <div className={styles.metricBlock}>
          <span className={styles.metricTitle}>Longest turn</span>
          <span className={styles.metricValue}>
            {longestSpeaker ? formatClock(longestSpeaker.longest_monologue_ms) : "0:00"}
          </span>
          <p className={styles.metricPlainLabel}>{longestMonologueLabel}</p>
        </div>

        <div className={styles.metricBlock}>
          <span className={styles.metricTitle}>Overlaps</span>
          <span className={styles.metricValue}>{overlaps}</span>
          <p className={styles.metricPlainLabel}>{overlapsLabel}</p>
        </div>
      </div>
    </article>
  );
}

function FactRow({
  fact,
  onSelectEvidence,
}: {
  fact: CallRecordFact;
  onSelectEvidence?: (evidence: ReportEvidence, title: string) => void;
}) {
  return (
    <li className={styles.factItem}>
      <p className={styles.statement}>{fact.statement}</p>
      {fact.evidence.map((ev, idx) => {
        const time = formatClock(ev.start_ms);
        return (
          <div key={`${ev.segment_id}-${idx}`} className={styles.quoteWrapper}>
            <blockquote className={styles.quoteText}>{ev.quote}</blockquote>
            <div className={styles.evidenceControls}>
              <ClipListenButton
                className={styles.listen}
                startMs={ev.start_ms}
                endMs={ev.end_ms}
                iconSize={12}
                onClick={() =>
                  onSelectEvidence?.(
                    {
                      segment_id: ev.segment_id,
                      quote: ev.quote,
                      start_ms: ev.start_ms,
                      end_ms: ev.end_ms,
                    },
                    fact.statement,
                  )
                }
                label={`Play clip at ${time}: ${ev.quote}`}
              >
                <span className={styles.clock}>{time}</span>
              </ClipListenButton>
            </div>
          </div>
        );
      })}
    </li>
  );
}

export function CallRecordView({
  callRecord,
  onSelectEvidence,
}: CallRecordProps) {
  // Check 4: Loading and errors fallback
  if (!callRecord) {
    return (
      <aside
        className={styles.unavailable}
        data-testid="call-details-unavailable"
      >
        Call details unavailable
      </aside>
    );
  }

  // Check 2: Facts without a quote never render
  const validFacts = callRecord.facts.filter(
    (f) => f.evidence && f.evidence.some((e) => e.quote && e.quote.trim().length > 0),
  );

  const hasTags = callRecord.tags !== null;

  return (
    <section className={styles.callRecordSection} aria-label="Call Record">
      <header className={styles.sectionHeader}>
        <p className={styles.sectionEyebrow}>Call record</p>
        <h2 className={styles.sectionTitle}>Numbers and facts</h2>
        <p className={styles.sectionSubtitle}>
          Verified statements and source numbers from this call.
        </p>
      </header>

      {/* Check 1: Numbers card */}
      <NumbersCard record={callRecord} />

      {/* Check 3: Tag grouped cards or flat list */}
      {hasTags ? (
        CANONICAL_TAG_GROUPS.map((group) => {
          const groupFacts = validFacts.filter(
            (f) => f.tag && f.tag.trim().toLowerCase() === group.toLowerCase(),
          );
          // Check 3: when null or empty, show nothing extra (no empty cards)
          if (groupFacts.length === 0) return null;
          return (
            <article key={group} className={styles.tagGroupCard}>
              <h3 className={styles.tagGroupHeading}>{group}</h3>
              <ul className={styles.factsList}>
                {groupFacts.map((fact, idx) => (
                  <FactRow
                    key={`${fact.statement}-${idx}`}
                    fact={fact}
                    onSelectEvidence={onSelectEvidence}
                  />
                ))}
              </ul>
            </article>
          );
        })
      ) : validFacts.length > 0 ? (
        <article className={styles.factsCard}>
          <h3 className={styles.factsHeading}>Facts</h3>
          <ul className={styles.factsList}>
            {validFacts.map((fact, idx) => (
              <FactRow
                key={`${fact.statement}-${idx}`}
                fact={fact}
                onSelectEvidence={onSelectEvidence}
              />
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  );
}
