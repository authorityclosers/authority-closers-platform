"use client";

/**
 * The call player on the film band: play, ±5 s, speed, and the loudness
 * waveform (C1 measurements) with the conversation's phases. Clicking or
 * using arrow keys on the waveform seeks. Audio streams from the admin source
 * route one byte range at a time.
 */
import { Pause, Play, RotateCcw, RotateCw } from "lucide-react";
import type { KeyboardEvent, MouseEvent, RefObject } from "react";

import { clock, type Story } from "./call-data";
import styles from "./review.module.css";

const PHASE_LABEL: Record<string, string> = {
  opening: "Opening",
  discovery: "Discovery",
  pitch: "Offer",
  objection: "Concerns",
  close: "Decision",
};

export function Player({
  audio,
  src,
  bars,
  durationMs,
  currentMs,
  playing,
  speed,
  failed,
  phases,
  onToggle,
  onSeek,
  onSpeed,
  onTime,
  onPlaying,
  onFailed,
}: {
  audio: RefObject<HTMLAudioElement | null>;
  src: string;
  bars: number[];
  durationMs: number | null;
  currentMs: number;
  playing: boolean;
  speed: number;
  failed: boolean;
  phases: Story["phases"];
  onToggle: () => void;
  onSeek: (ms: number) => void;
  onSpeed: (step: 1 | -1) => void;
  onTime: (ms: number) => void;
  onPlaying: (playing: boolean) => void;
  onFailed: () => void;
}) {
  const total = durationMs ?? 0;
  const progress = total > 0 ? Math.min(1, currentMs / total) : 0;
  const seekAt = (event: MouseEvent<HTMLDivElement>) => {
    if (!total) return;
    const box = event.currentTarget.getBoundingClientRect();
    onSeek(Math.round(((event.clientX - box.left) / box.width) * total));
  };
  const seekKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      event.stopPropagation();
      onSeek(
        currentMs +
          (event.key === "ArrowLeft" ? -5000 : 5000) * (event.shiftKey ? 3 : 1),
      );
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      onSeek(event.key === "Home" ? 0 : total);
    }
  };
  return (
    <section className={styles.player} aria-label="Call audio">
      <audio
        ref={audio}
        src={src || undefined}
        preload="metadata"
        onTimeUpdate={(event) =>
          onTime(Math.round(event.currentTarget.currentTime * 1000))
        }
        onPlay={() => onPlaying(true)}
        onPause={() => onPlaying(false)}
        onEnded={() => onPlaying(false)}
        onError={onFailed}
      />
      <div className={styles.controls}>
        <button
          type="button"
          className={styles.playButton}
          onClick={onToggle}
          disabled={failed || !src}
          aria-label={playing ? "Pause" : "Play"}
          aria-keyshortcuts="Space"
        >
          {playing ? (
            <Pause size={18} aria-hidden="true" />
          ) : (
            <Play size={18} aria-hidden="true" />
          )}
        </button>
        <button
          type="button"
          className={styles.filmButton}
          onClick={() => onSeek(currentMs - 5000)}
          disabled={failed}
          aria-label="Back 5 seconds"
          title="Back 5 s (←)"
        >
          <RotateCcw size={15} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={styles.filmButton}
          onClick={() => onSeek(currentMs + 5000)}
          disabled={failed}
          aria-label="Forward 5 seconds"
          title="Forward 5 s (→)"
        >
          <RotateCw size={15} aria-hidden="true" />
        </button>
        <span className={styles.time} aria-live="off">
          {clock(currentMs)} <span>/ {clock(durationMs)}</span>
        </span>
        <button
          type="button"
          className={styles.speed}
          onClick={() => onSpeed(1)}
          onContextMenu={(event) => {
            event.preventDefault();
            onSpeed(-1);
          }}
          aria-label={`Playback speed ${speed} times. Change speed`}
          title="Speed (, and .)"
        >
          {speed}×
        </button>
      </div>
      <div
        className={styles.wave}
        role="slider"
        tabIndex={0}
        aria-label="Position in the call"
        aria-valuemin={0}
        aria-valuemax={Math.round(total / 1000)}
        aria-valuenow={Math.round(currentMs / 1000)}
        aria-valuetext={`${clock(currentMs)} of ${clock(durationMs)}`}
        onClick={seekAt}
        onKeyDown={seekKey}
      >
        {bars.length ? (
          <svg
            viewBox={`0 0 ${bars.length} 40`}
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {bars.map((level, index) => (
              <rect
                key={index}
                x={index + 0.15}
                width={0.7}
                y={20 - Math.max(1, level * 19)}
                height={Math.max(2, level * 38)}
                data-played={index / bars.length < progress ? "" : undefined}
              />
            ))}
          </svg>
        ) : (
          <span className={styles.track} aria-hidden="true">
            <i style={{ width: `${progress * 100}%` }} />
          </span>
        )}
        <span
          className={styles.playhead}
          style={{ left: `${progress * 100}%` }}
          aria-hidden="true"
        />
        {total
          ? phases.map((phase, index) => (
              <span
                key={`${phase.name}-${index}`}
                className={styles.phase}
                style={{
                  left: `${Math.min(100, (phase.startMs / total) * 100)}%`,
                }}
                title={`${PHASE_LABEL[phase.name] ?? phase.name} · ${clock(phase.startMs)}`}
              >
                {PHASE_LABEL[phase.name] ?? phase.name}
              </span>
            ))
          : null}
      </div>
      {failed ? (
        <p className={styles.filmNote} role="status">
          The recording can&rsquo;t be played here. It may be past its retention
          date or still being prepared; the transcript and report are
          unaffected.
        </p>
      ) : null}
    </section>
  );
}
