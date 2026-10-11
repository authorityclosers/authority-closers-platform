"use client";

/**
 * The transcript with speakers. Clicking a line (or Enter on it) plays from
 * there; the line being heard is highlighted and followed until the reviewer
 * scrolls away, then "Follow audio" brings it back.
 */
import { LocateFixed } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { clock, type Segment } from "./call-data";
import styles from "./review.module.css";

export const DEVANAGARI = /[\u0900-\u097F]/;

export function TranscriptPane({
  segments,
  names,
  active,
  focused,
  onSeek,
}: {
  segments: Segment[];
  names: Record<string, string>;
  active: number;
  /** A line an evidence quote pointed at; it is outlined until the next jump. */
  focused: string | null;
  onSeek: (ms: number) => void;
}) {
  const list = useRef<HTMLOListElement>(null);
  const [follow, setFollow] = useState(true);
  const programmatic = useRef(false);

  useEffect(() => {
    if (!follow || active < 0) return;
    const row = list.current?.querySelector<HTMLElement>(
      `[data-index="${active}"]`,
    );
    if (!row) return;
    programmatic.current = true;
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    const release = window.setTimeout(
      () => (programmatic.current = false),
      600,
    );
    return () => window.clearTimeout(release);
  }, [active, follow]);

  useEffect(() => {
    if (!focused) return;
    const row = list.current?.querySelector<HTMLElement>(
      `[data-segment="${CSS.escape(focused)}"]`,
    );
    row?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focused]);

  if (!segments.length)
    return (
      <p className={styles.empty}>This run has no transcript lines to show.</p>
    );
  return (
    <div className={styles.transcript}>
      <ol
        ref={list}
        className={styles.lines}
        aria-label="Transcript"
        onScroll={() => {
          if (!programmatic.current && follow) setFollow(false);
        }}
      >
        {segments.map((segment, index) => {
          const speaker = segment.speakerId
            ? (names[segment.speakerId] ?? segment.speakerId)
            : "Unknown";
          return (
            <li
              key={segment.id}
              data-index={index}
              data-segment={segment.id}
              data-active={index === active ? "" : undefined}
              data-focused={segment.id === focused ? "" : undefined}
              data-role={
                speaker.startsWith("Rep")
                  ? "rep"
                  : speaker.startsWith("Prospect")
                    ? "prospect"
                    : "other"
              }
            >
              <button
                type="button"
                className={styles.line}
                onClick={() => onSeek(segment.startMs)}
                aria-label={`${speaker} at ${clock(segment.startMs)}. Play from here`}
              >
                <span className={styles.lineMeta}>
                  <span className={styles.speaker}>{speaker}</span>
                  <time>{clock(segment.startMs)}</time>
                </span>
                {/* Devanagari and code-mixed lines keep their own script's leading. */}
                <span
                  className={styles.lineText}
                  data-script={
                    DEVANAGARI.test(segment.text) ? "deva" : undefined
                  }
                >
                  {segment.text}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {!follow ? (
        <button
          type="button"
          className={styles.follow}
          onClick={() => setFollow(true)}
        >
          <LocateFixed size={14} aria-hidden="true" />
          Follow audio
        </button>
      ) : null}
    </div>
  );
}
