"use client";

import { useId, type CSSProperties } from "react";

import { formatClock, isPlayableRange } from "./lightbox/time";
import type { ReportEvidence } from "./report-contract";
import { formatClipTime, type ReplayClip } from "./report-moments";
import { ClipPlayIcon, ClipPlayState } from "./source-waveform";
import styles from "./replay-strip.module.css";

/**
 * Where the report's replay clips sit in the recording. Position and width
 * come only from each clip's own milliseconds and the transcript duration.
 * It is not a score, a sales stage or a measure of coverage.
 *
 * The strip is a pointer shortcut; the chronological list below it is the
 * complete, comfortably sized control set for keyboard, touch and screen
 * readers, so tiny or overlapping clips never depend on an 8px target.
 */
export function ReplayStrip({
  clips,
  durationMs,
  onSelect,
}: {
  clips: ReplayClip[];
  durationMs?: number;
  onSelect: (evidence: ReportEvidence, title: string) => void;
}) {
  const titleId = useId();
  if (!clips.length) return null;
  const total =
    typeof durationMs === "number" && Number.isFinite(durationMs)
      ? durationMs
      : 0;
  // Three distinct truths: the interval itself is invalid; the recording
  // length is unknown (nothing to check against); or a valid range extends
  // beyond the known length. Only intervals inside a known length, or any
  // valid interval when no length is known, are offered as playback controls.
  const lengthKnown = total > 0;
  const valid = clips.filter(({ evidence }) =>
    isPlayableRange(evidence.start_ms, evidence.end_ms),
  );
  const placed = lengthKnown
    ? valid.filter(({ evidence }) => evidence.end_ms <= total)
    : [];
  const beyond = lengthKnown
    ? valid.filter(({ evidence }) => evidence.end_ms > total)
    : [];
  const offered = new Set(lengthKnown ? placed : valid);
  const invalid = clips.length - valid.length;
  const state = placed.length ? "placed" : lengthKnown ? "beyond" : "unknown";

  return (
    <section
      className={styles.strip}
      aria-labelledby={titleId}
      data-replay-strip={state}
    >
      <div className={styles.heading}>
        <h3 id={titleId}>Where the replay clips are</h3>
        <p>
          {total > 0
            ? `${placed.length} of ${clips.length} supplied clips fit fully within the ${formatClock(total)} recording · positions only, not a score`
            : `${clips.length} ${clips.length === 1 ? "clip" : "clips"} · recording length unavailable`}
        </p>
      </div>
      {placed.length ? (
        <>
          <div className={styles.track} aria-hidden="true">
            <span className={styles.rail} />
            {placed.map(({ evidence, titles }) => (
              <ClipPlayState
                key={`${evidence.segment_id}:${evidence.start_ms}:${evidence.end_ms}`}
                startMs={evidence.start_ms}
                endMs={evidence.end_ms}
              >
                {(playing) => (
                  <button
                    type="button"
                    tabIndex={-1}
                    className={styles.marker}
                    style={
                      {
                        "--left": `${(evidence.start_ms / total) * 100}%`,
                        "--width": `${((evidence.end_ms - evidence.start_ms) / total) * 100}%`,
                      } as CSSProperties
                    }
                    data-clip-playing={playing || undefined}
                    title={`${formatClipTime(evidence)} · ${titles.join("; ")}`}
                    onClick={() => onSelect(evidence, titles[0])}
                  />
                )}
              </ClipPlayState>
            ))}
          </div>
          <div className={styles.scale} aria-hidden="true">
            <span>00:00</span>
            <span>{formatClock(total)}</span>
          </div>
        </>
      ) : state === "unknown" ? (
        <p className={styles.unavailable} role="note">
          Replay timeline unavailable: the recording length is not known, so
          clip positions cannot be drawn.
        </p>
      ) : null}
      {beyond.length ? (
        <p className={styles.unavailable} role="note">
          {state === "beyond"
            ? `None of the ${beyond.length} clip ranges fit fully within the ${formatClock(total)} recording, so they are not drawn or playable.`
            : `${beyond.length} ${beyond.length === 1 ? "clip range extends" : "clip ranges extend"} past the ${formatClock(total)} recording and ${beyond.length === 1 ? "is" : "are"} listed below, but not drawn or playable.`}
        </p>
      ) : null}
      {invalid ? (
        <p className={styles.unavailable} role="note">
          {invalid} {invalid === 1 ? "excerpt has" : "excerpts have"} no
          playable time range and {invalid === 1 ? "is" : "are"} not listed.
        </p>
      ) : null}
      <ol className={styles.list} aria-label="Replay clips in time order">
        {valid.map((row) => {
          const { evidence, titles } = row;
          const clip = formatClipTime(evidence);
          const key = `${evidence.segment_id}:${evidence.start_ms}:${evidence.end_ms}`;
          // Ranges extending past a known recording length are readable only.
          if (!offered.has(row))
            return (
              <li key={key}>
                <span className={styles.item} data-replay-beyond>
                  <span className={styles.itemTime}>{clip}</span>
                  <span className={styles.itemTitle}>
                    {titles.join(" · ")} · extends past the {formatClock(total)}{" "}
                    recording
                  </span>
                </span>
              </li>
            );
          return (
            <li key={key}>
              <ClipPlayState
                startMs={evidence.start_ms}
                endMs={evidence.end_ms}
              >
                {(playing) => (
                  <button
                    type="button"
                    className={styles.item}
                    aria-pressed={playing}
                    aria-label={`${playing ? "Pause" : "Listen"} ${clip}: ${titles.join("; ")}`}
                    data-clip-playing={playing || undefined}
                    onClick={() => onSelect(evidence, titles[0])}
                  >
                    <ClipPlayIcon playing={playing} size={13} />
                    <span className={styles.itemTime}>{clip}</span>
                    <span className={styles.itemTitle}>
                      {titles.join(" · ")}
                    </span>
                  </button>
                )}
              </ClipPlayState>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
