"use client";

import { useState, type CSSProperties, type RefObject } from "react";
import { Pause, Play, Volume2, VolumeX } from "lucide-react";
import { formatClock } from "./lightbox/time";
import { SourceWaveform } from "./source-waveform";
import styles from "./call-audio-dock.module.css";

const clock = (seconds: number) => formatClock(seconds * 1000);
const rates = [1, 1.25, 1.5, 2, 0.75];

export function CallAudioDock({
  audioRef,
  src,
  durationMs,
  title = "Your saved sales call",
  embedded = false,
  onPlay,
  onTimeUpdate,
  onSeek,
  onError,
}: {
  audioRef: RefObject<HTMLAudioElement | null>;
  src: string;
  durationMs: number;
  title?: string;
  embedded?: boolean;
  /** Called only when the full-player Play control starts the recording. */
  onPlay?: () => void;
  onTimeUpdate?: () => void;
  onSeek?: () => void;
  onError?: () => void;
}) {
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(durationMs / 1000);
  const [rate, setRate] = useState(1);
  const [muted, setMuted] = useState(false);
  const [message, setMessage] = useState("");
  const total =
    Number.isFinite(duration) && duration > 0 ? duration : durationMs / 1000;
  const current = Math.max(0, Math.min(position, total));
  // The playhead follows the element's own currentTime, with or without a waveform.
  const progress = total > 0 ? current / total : 0;
  async function togglePlay() {
    const player = audioRef.current;
    if (!player) return;
    if (!player.paused) {
      player.pause();
      return;
    }
    try {
      onPlay?.();
      await player.play();
      setMessage("");
    } catch {
      setMessage("Audio could not start. Try play again.");
    }
  }
  return (
    <section
      className={styles.dock}
      data-embedded={embedded}
      data-playing={playing}
      aria-label="Call audio player"
    >
      <audio
        ref={audioRef}
        src={src || undefined}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onLoadedMetadata={() => {
          const measured = audioRef.current?.duration;
          if (measured && Number.isFinite(measured)) setDuration(measured);
        }}
        onTimeUpdate={() => {
          setPosition(audioRef.current?.currentTime ?? 0);
          onTimeUpdate?.();
        }}
        onSeeked={() => setPosition(audioRef.current?.currentTime ?? 0)}
        onError={() => {
          setMessage("Audio is unavailable. You can still read your report.");
          onError?.();
        }}
      />
      <button
        type="button"
        className={styles.play}
        aria-label={playing ? "Pause recording" : "Play recording"}
        onClick={() => void togglePlay()}
      >
        {playing ? (
          <Pause size={20} fill="currentColor" aria-hidden="true" />
        ) : (
          <Play size={20} fill="currentColor" aria-hidden="true" />
        )}
      </button>
      <div className={styles.identity}>
        <strong title={title}>{title}</strong>
        {message && (
          <span className={styles.message} role="status">
            {message}
          </span>
        )}
      </div>
      <div
        className={styles.timeline}
        style={{ "--progress": progress } as CSSProperties}
      >
        <SourceWaveform />
        <span className={styles.track} aria-hidden="true">
          <span className={styles.fill} />
        </span>
        <span className={styles.playhead} aria-hidden="true" />
        <input
          type="range"
          min={0}
          max={total || 1}
          step={1}
          value={current}
          aria-label="Seek recording"
          aria-valuetext={`${clock(current)} of ${clock(total)}`}
          onChange={(event) => {
            const player = audioRef.current;
            if (player) {
              onSeek?.();
              player.currentTime = Number(event.currentTarget.value);
              setPosition(player.currentTime);
            }
          }}
        />
      </div>
      {/* Plain text, not a live region: the seek control announces the time on demand. */}
      <span className={styles.clock}>
        {clock(current)} <span aria-hidden="true">/</span>{" "}
        <span className={styles.total}>{clock(total)}</span>
      </span>
      <button
        type="button"
        className={`${styles.tool} ${styles.speed}`}
        aria-label={`Playback speed ${rate} times`}
        onClick={() => {
          const next = rates[(rates.indexOf(rate) + 1) % rates.length];
          if (audioRef.current) audioRef.current.playbackRate = next;
          setRate(next);
        }}
      >
        {rate}×
      </button>
      <button
        type="button"
        className={`${styles.tool} ${styles.mute}`}
        aria-label={muted ? "Unmute recording" : "Mute recording"}
        onClick={() => {
          const player = audioRef.current;
          if (player) {
            player.muted = !player.muted;
            setMuted(player.muted);
          }
        }}
      >
        {muted ? (
          <VolumeX size={20} aria-hidden="true" />
        ) : (
          <Volume2 size={20} aria-hidden="true" />
        )}
      </button>
    </section>
  );
}
