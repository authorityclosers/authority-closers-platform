"use client";

import { useState, type RefObject } from "react";
import { Music2, Pause, Play, Volume2, VolumeX } from "lucide-react";
import { SourceWaveform } from "./source-waveform";
import styles from "./call-audio-dock.module.css";

const time = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
const rates = [1, 1.25, 1.5, 2, 0.75];

export function CallAudioDock({
  audioRef,
  src,
  durationMs,
  title = "Your saved sales call",
  embedded = false,
  onTimeUpdate,
  onSeek,
  onError,
}: {
  audioRef: RefObject<HTMLAudioElement | null>;
  src: string;
  durationMs: number;
  title?: string;
  embedded?: boolean;
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
  async function togglePlay() {
    const player = audioRef.current;
    if (!player) return;
    if (!player.paused) {
      player.pause();
      return;
    }
    try {
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
        onError={() => {
          setMessage("Audio is unavailable. You can still read your report.");
          onError?.();
        }}
      />
      <div className={styles.identity}>
        <span className={styles.fileIcon}>
          <Music2 size={22} aria-hidden="true" />
        </span>
        <div>
          <strong title={title}>{title}</strong>
          {message ? (
            <span className={styles.message} role="status">
              {message}
            </span>
          ) : (
            <span>
              {time(current)} / {time(total)}
            </span>
          )}
        </div>
      </div>
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
      <div className={styles.timeline}>
        <SourceWaveform />
        <input
          type="range"
          min={0}
          max={total || 1}
          step={0.1}
          value={current}
          aria-label="Seek recording"
          aria-valuetext={`${time(current)} of ${time(total)}`}
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
      <output className={styles.clock}>
        {time(current)} / {time(total)}
      </output>
      <button
        type="button"
        className={styles.tool}
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
          <VolumeX size={21} aria-hidden="true" />
        ) : (
          <Volume2 size={21} aria-hidden="true" />
        )}
      </button>
      <button
        type="button"
        className={styles.tool}
        aria-label={`Playback speed ${rate} times`}
        onClick={() => {
          const next = rates[(rates.indexOf(rate) + 1) % rates.length];
          if (audioRef.current) audioRef.current.playbackRate = next;
          setRate(next);
        }}
      >
        {rate}×
      </button>
    </section>
  );
}
