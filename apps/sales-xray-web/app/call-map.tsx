"use client";

import type { CSSProperties } from "react";

import { formatClock } from "./lightbox/time";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { useSourceWaveform, waveformBins } from "./source-waveform";
import styles from "./call-map.module.css";

const BIN_COUNT = 160;
// A switch within this gap still counts as the same person holding the floor.
const SAME_TURN_GAP_MS = 1500;

const KINDS = [
  { key: "strengths", label: "Strength", tone: "strength" },
  { key: "objection_analysis", label: "Objection", tone: "objection" },
  { key: "missed_opportunities", label: "Missed", tone: "missed" },
  { key: "closing_analysis", label: "Closing", tone: "closing" },
  { key: "improvements", label: "To improve", tone: "improve" },
] as const;

type Tone = (typeof KINDS)[number]["tone"];
type Marker = {
  key: string;
  tone: Tone;
  kind: string;
  title: string;
  evidence: ReportEvidence;
  x: number;
};

function callFacts(transcript: Transcript, total: number) {
  const voices: string[] = [];
  const talk = new Map<string, number>();
  let longest = { ms: 0, voice: -1 };
  let run: { voice: string; start: number; end: number } | null = null;
  let switches = 0;
  let previous: string | null = null;
  for (const segment of transcript.segments) {
    const voice = segment.speaker_id ?? "unknown";
    if (!voices.includes(voice)) voices.push(voice);
    talk.set(
      voice,
      (talk.get(voice) ?? 0) + Math.max(0, segment.end_ms - segment.start_ms),
    );
    if (previous !== null && previous !== voice) switches += 1;
    previous = voice;
    if (
      run &&
      run.voice === voice &&
      segment.start_ms - run.end <= SAME_TURN_GAP_MS
    ) {
      run.end = Math.max(run.end, segment.end_ms);
    } else {
      run = { voice, start: segment.start_ms, end: segment.end_ms };
    }
    if (run.end - run.start > longest.ms)
      longest = { ms: run.end - run.start, voice: voices.indexOf(voice) };
  }
  const talkTotal = [...talk.values()].reduce((sum, value) => sum + value, 0);
  const shares = voices.slice(0, 2).map((voice) =>
    talkTotal > 0 ? (talk.get(voice) ?? 0) / talkTotal : 0,
  );
  const minutes = Math.max(1 / 60, total / 60000);
  return {
    voices,
    shares,
    longest,
    switchesPerMinute: switches / minutes,
  };
}

/** A zigzag with more peaks for more back-and-forth (2 to 8 segments). */
function zigzagPath(switchesPerMinute: number) {
  const steps = Math.max(2, Math.min(8, Math.round(switchesPerMinute * 1.5)));
  const points = Array.from(
    { length: steps },
    (_, index) => `L${3 + ((index + 1) * 30) / steps} ${index % 2 ? 24 : 12}`,
  );
  return `M3 18 ${points.join(" ")}`;
}

/**
 * The whole call at a glance: the measured audio envelope (played part lit),
 * a speaker lane from transcript timings, a pin for every report finding that
 * cites a moment, and four facts drawn from the transcript and report. Speaker
 * labels are unverified, so voices are numbered, not named.
 */
export function CallMap({
  transcript,
  report,
  durationMs,
  onSelectEvidence,
}: {
  transcript: Transcript;
  report: SalesReport;
  durationMs: number;
  onSelectEvidence: (evidence: ReportEvidence) => void;
}) {
  const { envelope, currentTimeMs } = useSourceWaveform();
  const total = Math.max(1, durationMs);
  const facts = callFacts(transcript, total);
  const levels = envelope
    ? waveformBins(envelope, 0, envelope.duration_ms, BIN_COUNT)
    : null;
  const progress = Math.min(1, Math.max(0, currentTimeMs / total));

  const markers: Marker[] = KINDS.flatMap((kind) =>
    ((report[kind.key] as Finding[] | undefined) ?? []).flatMap(
      (finding, index) => {
        const evidence = finding.evidence[0];
        if (!evidence) return [];
        return [
          {
            key: `${kind.key}-${index}`,
            tone: kind.tone,
            kind: kind.label,
            title: finding.title,
            evidence,
            x: Math.min(100, Math.max(0, (evidence.start_ms / total) * 100)),
          },
        ];
      },
    ),
  );
  const wins = report.strengths.length;
  const toWorkOn =
    report.missed_opportunities.length + report.improvements.length;
  const lead = facts.shares[0] ?? 0;

  return (
    <figure className={styles.map} aria-label="Call map">
      <div className={styles.lane}>
        <div className={styles.pins}>
          {markers.map((marker) => (
            <button
              key={marker.key}
              type="button"
              className={styles.pin}
              data-tone={marker.tone}
              data-edge={
                marker.x < 18 ? "start" : marker.x > 82 ? "end" : undefined
              }
              style={{ left: `${marker.x}%` } as CSSProperties}
              aria-label={`${marker.kind}: ${marker.title}, at ${formatClock(marker.evidence.start_ms)}. Play this moment.`}
              onClick={() => onSelectEvidence(marker.evidence)}
            >
              <span className={styles.tip} aria-hidden="true">
                <em>
                  {marker.kind} · {formatClock(marker.evidence.start_ms)}
                </em>
                {marker.title}
              </span>
            </button>
          ))}
        </div>
        <div className={styles.track}>
        {levels ? (
          <svg
            className={styles.wave}
            viewBox={`0 0 ${BIN_COUNT * 4} 60`}
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {levels.map((level, index) => {
              const height = Math.max(
                2.5,
                Math.pow(level ?? 0, 0.5) * 27,
              );
              return (
                <line
                  key={index}
                  x1={index * 4 + 2}
                  x2={index * 4 + 2}
                  y1={30 - height}
                  y2={30 + height}
                  className={
                    (index + 0.5) / BIN_COUNT <= progress
                      ? styles.played
                      : styles.pending
                  }
                />
              );
            })}
          </svg>
        ) : null}
        <div className={styles.speakers} aria-hidden="true">
          {transcript.segments.map((segment) => (
            <span
              key={segment.id}
              data-voice={Math.min(
                facts.voices.indexOf(segment.speaker_id ?? "unknown"),
                2,
              )}
              style={
                {
                  left: `${(segment.start_ms / total) * 100}%`,
                  width: `${Math.max(0.25, ((segment.end_ms - segment.start_ms) / total) * 100)}%`,
                } as CSSProperties
              }
            />
          ))}
        </div>
        <span
          className={styles.playhead}
          style={{ left: `${progress * 100}%` } as CSSProperties}
          aria-hidden="true"
        />
        </div>
        <div className={styles.axis} aria-hidden="true">
          <span>0:00</span>
          <span>{formatClock(total / 2)}</span>
          <span>{formatClock(total)}</span>
        </div>
      </div>

      <figcaption className={styles.facts}>
        <div className={styles.fact}>
          <svg className={styles.ring} viewBox="0 0 36 36" aria-hidden="true">
            <circle className={styles.ringTrack} cx="18" cy="18" r="14" />
            <circle
              className={styles.ringLead}
              cx="18"
              cy="18"
              r="14"
              pathLength={100}
              strokeDasharray={`${lead * 100} 100`}
            />
          </svg>
          <span>
            <b>
              {Math.round(lead * 100)}
              <small>%</small>
            </b>
            <small>Speaker 1 talk share</small>
          </span>
        </div>
        <div className={styles.fact}>
          <svg className={styles.stretch} viewBox="0 0 36 36" aria-hidden="true">
            <rect x="4" y="16" width="28" height="4" rx="2" />
            <rect
              className={styles.stretchRun}
              x="4"
              y="16"
              width={Math.max(3, Math.min(28, (facts.longest.ms / total) * 28 * 4))}
              height="4"
              rx="2"
            />
            <path d="M4 10v16M32 10v16" />
          </svg>
          <span>
            <b>{formatClock(facts.longest.ms)}</b>
            <small>
              Longest stretch
              {facts.longest.voice >= 0
                ? ` · Speaker ${facts.longest.voice + 1}`
                : ""}
            </small>
          </span>
        </div>
        <div className={styles.fact}>
          <svg className={styles.zigzag} viewBox="0 0 36 36" aria-hidden="true">
            <path
              pathLength={100}
              d={zigzagPath(facts.switchesPerMinute)}
            />
          </svg>
          <span>
            <b>
              {facts.switchesPerMinute.toFixed(1)}
              <small>/min</small>
            </b>
            <small>Back-and-forth</small>
          </span>
        </div>
        <div className={styles.fact}>
          <svg className={styles.balance} viewBox="0 0 36 36" aria-hidden="true">
            {Array.from({ length: Math.min(wins, 4) }, (_, index) => (
              <rect
                key={`w${index}`}
                className={styles.win}
                x={6 + index * 5}
                y="9"
                width="6"
                height="6"
                rx="1.2"
                transform={`rotate(45 ${9 + index * 5} 12)`}
                style={{ "--i": index } as CSSProperties}
              />
            ))}
            {Array.from({ length: Math.min(toWorkOn, 4) }, (_, index) => (
              <rect
                key={`f${index}`}
                className={styles.fix}
                x={6 + index * 5}
                y="21"
                width="6"
                height="6"
                rx="1.2"
                transform={`rotate(45 ${9 + index * 5} 24)`}
                style={{ "--i": index + 4 } as CSSProperties}
              />
            ))}
          </svg>
          <span>
            <b>
              {wins}
              <small> · </small>
              {toWorkOn}
            </b>
            <small>Wins · to work on</small>
          </span>
        </div>
      </figcaption>
    </figure>
  );
}
