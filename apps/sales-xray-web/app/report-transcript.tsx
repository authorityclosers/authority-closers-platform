"use client";

import { useMemo, useState } from "react";
import type { Transcript, TranscriptSegment } from "./report-contract";
import styles from "./report-transcript.module.css";

const PAGE_SIZE = 50;
const ALL_SPEAKERS = "all";

function speakerKey(speakerId: string | null): string {
  return speakerId === null ? "unlabelled" : `speaker:${speakerId}`;
}

function speakerLabel(speakerId: string | null): string {
  return speakerId ?? "Unlabelled speaker";
}

export function formatTranscriptTime(milliseconds: number): string {
  const minutes = Math.floor(milliseconds / 60_000);
  const seconds = Math.floor(milliseconds / 1_000) % 60;
  const millis = milliseconds % 1_000;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

export type ReportTranscriptProps = {
  transcript: Transcript;
  onSelect: (segment: TranscriptSegment) => void;
};

export function ReportTranscript({
  transcript,
  onSelect,
}: ReportTranscriptProps) {
  const [query, setQuery] = useState("");
  const [selectedSpeaker, setSelectedSpeaker] = useState(ALL_SPEAKERS);
  const [pagination, setPagination] = useState({ key: "", count: PAGE_SIZE });
  const paginationKey = `${transcript.source_sha256}\u0000${transcript.revision}\u0000${selectedSpeaker}\u0000${query}`;

  const speakerOptions = useMemo(() => {
    const options = new Map<string, string>();
    transcript.segments.forEach((segment) => {
      options.set(
        speakerKey(segment.speaker_id),
        speakerLabel(segment.speaker_id),
      );
    });
    return [...options.entries()];
  }, [transcript]);

  const filteredSegments = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return transcript.segments.filter((segment) => {
      const matchesSpeaker =
        selectedSpeaker === ALL_SPEAKERS ||
        speakerKey(segment.speaker_id) === selectedSpeaker;
      const matchesPhrase =
        !normalizedQuery ||
        segment.text.toLowerCase().includes(normalizedQuery);
      return matchesSpeaker && matchesPhrase;
    });
  }, [query, selectedSpeaker, transcript]);

  const visibleCount =
    pagination.key === paginationKey ? pagination.count : PAGE_SIZE;
  const visibleSegments = filteredSegments.slice(0, visibleCount);
  const remainingCount = filteredSegments.length - visibleSegments.length;
  const resultLabel =
    query.trim() || selectedSpeaker !== ALL_SPEAKERS
      ? `${filteredSegments.length} matching segments`
      : `${filteredSegments.length} segments`;

  return (
    <details className={styles.root}>
      <summary className={styles.summary}>
        <span>Read full transcript</span>
        <span className={styles.summaryMeta}>
          {transcript.segments.length} segments
        </span>
      </summary>
      <div className={styles.body}>
        <div className={styles.controls} role="search">
          <label className={styles.field}>
            <span>Search transcript</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find a phrase"
              aria-label="Search transcript phrases"
            />
          </label>
          {speakerOptions.length > 0 && (
            <label className={styles.field}>
              <span>Speaker</span>
              <select
                value={selectedSpeaker}
                onChange={(event) => setSelectedSpeaker(event.target.value)}
                aria-label="Filter transcript by speaker"
              >
                <option value={ALL_SPEAKERS}>All speakers</option>
                {speakerOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <p className={styles.note}>
          Speaker labels come from the source and are unverified. Filter labels
          may be IDs rather than names.
        </p>
        <p className={styles.count} role="status" aria-live="polite">
          {resultLabel} · showing {visibleSegments.length}
        </p>
        {visibleSegments.length > 0 ? (
          <div className={styles.list}>
            {visibleSegments.map((segment) => {
              const start = formatTranscriptTime(segment.start_ms);
              const end = formatTranscriptTime(segment.end_ms);
              return (
                <button
                  className={styles.segment}
                  key={segment.id}
                  type="button"
                  data-segment-id={segment.id}
                  data-start-ms={segment.start_ms}
                  data-end-ms={segment.end_ms}
                  aria-label={`${start} to ${end}: ${segment.text}`}
                  onClick={() => onSelect(segment)}
                >
                  <span className={styles.timestamp}>
                    {start}–{end}
                  </span>
                  <span className={styles.speaker}>
                    {speakerLabel(segment.speaker_id)}
                  </span>
                  <span className={styles.text}>{segment.text}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className={styles.empty}>No transcript segments match.</p>
        )}
        {remainingCount > 0 && (
          <button
            className={styles.loadMore}
            type="button"
            onClick={() =>
              setPagination({
                key: paginationKey,
                count: Math.min(
                  visibleCount + PAGE_SIZE,
                  filteredSegments.length,
                ),
              })
            }
          >
            Load {Math.min(PAGE_SIZE, remainingCount)} more
          </button>
        )}
      </div>
    </details>
  );
}
