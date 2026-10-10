"use client";

import Link from "next/link";

import { formatClock } from "./lightbox/time";
import type { DocumentReportData } from "./report-document-data";
import type { ReportEvidence } from "./report-contract";
import type { ReportPanel } from "./report-modes";
import {
  reportPillars,
  type PillarEntry,
  type ReportPillar,
} from "./report-pillars";
import { RichText } from "./report-entities";
import styles from "./report-pillar-screen.module.css";

type Select = (evidence: ReportEvidence, title: string) => void;
const SUBTITLES = [
  "Understand the call in seconds.",
  "See how the conversation moved.",
  "See what helped the conversation and what made it harder.",
  "Replay the moments that changed the conversation.",
  "See how your sales skills showed up in this conversation.",
  "Know what happens next.",
];

function Evidence({
  entries,
  onSelect,
  title,
}: {
  entries: ReportEvidence[];
  onSelect?: Select;
  title: string;
}) {
  return (
    <div className={styles.evidence}>
      {entries.map((source, i) => (
        <figure key={`${source.segment_id}-${i}`}>
          <figcaption>
            {onSelect ? (
              <button
                type="button"
                onClick={() => onSelect(source, title)}
                aria-label={`Play ${title}, ${formatClock(source.start_ms)}`}
              >
                Play · {formatClock(source.start_ms)}–
                {formatClock(source.end_ms)}
              </button>
            ) : (
              <span>
                {formatClock(source.start_ms)}–{formatClock(source.end_ms)}
              </span>
            )}
          </figcaption>
          <blockquote>
            <RichText text={source.quote} />
          </blockquote>
        </figure>
      ))}
    </div>
  );
}

function Entry({ entry, onSelect }: { entry: PillarEntry; onSelect?: Select }) {
  return (
    <div className={styles.entry} data-gap={entry.gap || undefined}>
      <h3>
        {entry.label}
        {entry.hypothesis && <small>Interpretation</small>}
        {entry.gap && <small>Unknown</small>}
      </h3>
      <p>
        <RichText text={entry.text} />
      </p>
      {entry.evidence.length > 0 && (
        <details className={styles.sources}>
          <summary>
            Source ·{" "}
            {entry.evidence.map((e) => formatClock(e.start_ms)).join(" · ")}
          </summary>
          <Evidence
            entries={entry.evidence}
            title={entry.label}
            onSelect={onSelect}
          />
        </details>
      )}
    </div>
  );
}

function Measurements({ data }: { data: DocumentReportData }) {
  const numbers = data.callRecord?.numbers;
  return (
    <div className={styles.measurements}>
      <dl className={styles.metrics}>
        <div>
          <dt>Call length</dt>
          <dd>
            {data.transcript
              ? formatClock(data.transcript.duration_ms)
              : numbers
                ? formatClock(numbers.duration_ms)
                : (data.callLength ?? "Unknown")}
          </dd>
        </div>
        <div>
          <dt>Talk-overs</dt>
          <dd>{numbers?.overlaps ?? "Unknown"}</dd>
        </div>
        {numbers?.speakers.map((speaker, i) => (
          <div key={speaker.speaker_id}>
            <dt>
              {data.speakerNames?.[speaker.speaker_id] ?? `Speaker ${i + 1}`}
            </dt>
            <dd>
              {Math.round(speaker.talk_share * 100)}% talk · {speaker.questions}{" "}
              questions
            </dd>
            <small>
              Longest turn {formatClock(speaker.longest_monologue_ms)}
            </small>
          </div>
        ))}
      </dl>
      <p>
        Measurements describe the call; context determines what they mean.
        {!numbers && " Speaker measurements were not supplied."}
      </p>
    </div>
  );
}

function PillarScreen({
  pillar,
  index,
  data,
  onSelect,
}: {
  pillar: ReportPillar;
  index: number;
  data: DocumentReportData;
  onSelect?: Select;
}) {
  return (
    <div className={styles.pillar} data-report-pillar={pillar.id}>
      <p className={styles.subtitle}>{SUBTITLES[index]}</p>
      {index === 1 && <Measurements data={data} />}
      {pillar.timeline && (
        <ol className={styles.timeline} aria-label="Conversation timeline">
          {pillar.timeline.map((phase, i) => (
            <li key={i} style={{ flexGrow: phase.end_ms - phase.start_ms }}>
              <strong>{phase.label}</strong>
              <span>
                {formatClock(phase.start_ms)}–{formatClock(phase.end_ms)}
              </span>
            </li>
          ))}
        </ol>
      )}
      {index === 4
        ? pillar.entries.map((entry, i) => (
            <details key={i} className={styles.skill}>
              <summary>
                <span>{entry.label.split(" · ")[0]}</span>
                <small>
                  {entry.gap
                    ? "Not Enough Evidence"
                    : entry.label.split(" · ").at(-1)}
                </small>
              </summary>
              <p>{entry.text}</p>
              <Evidence
                entries={entry.evidence}
                title={entry.label}
                onSelect={onSelect}
              />
            </details>
          ))
        : pillar.entries.map((entry, i) => (
            <Entry key={i} entry={entry} onSelect={onSelect} />
          ))}
      {index === 4 && (
        <details className={styles.sources}>
          <summary>Explore deeper analysis</summary>
          {[
            ...(data.report?.objection_analysis ?? []),
            ...(data.report?.closing_analysis ?? []),
          ].map((finding, i) => (
            <Entry
              key={i}
              entry={{
                label: finding.title,
                text: finding.explanation,
                evidence: finding.evidence,
                hypothesis: true,
              }}
              onSelect={onSelect}
            />
          ))}
          {!data.report?.objection_analysis.length &&
            !data.report?.closing_analysis.length && (
              <p>No deeper analysis was supplied for this call.</p>
            )}
        </details>
      )}
      {index === 5 && (
        <Link className={styles.destination} href="/prospects">
          View Prospect&apos;s Information
        </Link>
      )}
    </div>
  );
}

/** One source of pillar content for Reading, Sections and Word. */
export function reportScreenPanels(
  data: DocumentReportData,
  onSelect?: Select,
): ReportPanel[] {
  if (!data.report) return [];
  return reportPillars(data.report, data.transcript?.duration_ms).map(
    (pillar, index) => ({
      id: pillar.id,
      label: pillar.label,
      compactLabel: [
        "Big Picture",
        "Call Flow",
        "Worked / Didn't",
        "Moments",
        "Skills",
        "Deal",
      ][index],
      summary: SUBTITLES[index],
      content: (
        <PillarScreen
          pillar={pillar}
          index={index}
          data={data}
          onSelect={onSelect}
        />
      ),
    }),
  );
}
