"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { Pause, Play } from "lucide-react";
import styles from "./source-waveform.module.css";

export type WaveformEnvelope = {
  schema: "ac.sales-xray.waveform/1";
  kind: "rms_envelope";
  duration_ms: number;
  points: { start_ms: number; level: number | null }[];
};

export function parseWaveform(value: unknown): WaveformEnvelope | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<WaveformEnvelope>;
  if (
    candidate.schema !== "ac.sales-xray.waveform/1" ||
    candidate.kind !== "rms_envelope" ||
    typeof candidate.duration_ms !== "number" ||
    !Number.isFinite(candidate.duration_ms) ||
    candidate.duration_ms <= 0 ||
    !Array.isArray(candidate.points) ||
    candidate.points.length > 1200
  )
    return null;
  let previous = -1;
  for (const point of candidate.points) {
    if (
      !point ||
      typeof point !== "object" ||
      typeof point.start_ms !== "number" ||
      !Number.isFinite(point.start_ms) ||
      point.start_ms < 0 ||
      point.start_ms <= previous ||
      point.start_ms > candidate.duration_ms ||
      (point.level !== null &&
        (typeof point.level !== "number" ||
          !Number.isFinite(point.level) ||
          point.level < 0 ||
          point.level > 1))
    )
      return null;
    previous = point.start_ms;
  }
  return candidate as WaveformEnvelope;
}

export type ClipRange = { start_ms: number; end_ms: number };

type SourceState = {
  envelope: WaveformEnvelope | null;
  currentTimeMs: number;
  playing: boolean;
  /** The clip the studio started; null during full-recording playback. */
  activeRange: ClipRange | null;
};
const SourceContext = createContext<SourceState>({
  envelope: null,
  currentTimeMs: 0,
  playing: false,
  activeRange: null,
});

function sameRange(a: ClipRange | null | undefined, b: ClipRange) {
  return Boolean(a && a.start_ms === b.start_ms && a.end_ms === b.end_ms);
}

/**
 * A clip reads as playing only when it started the current playback and the
 * playhead is inside it. Full-recording playback from the dock clears the
 * active clip, so overlapping clips never all claim "Pause".
 */
export function clipIsPlaying(
  range: ClipRange,
  state: Pick<SourceState, "playing" | "currentTimeMs" | "activeRange">,
): boolean {
  return (
    state.playing &&
    sameRange(state.activeRange, range) &&
    state.currentTimeMs >= range.start_ms &&
    state.currentTimeMs < range.end_ms
  );
}

/** What pressing a clip control does to the one shared player. */
export function clipPressAction(
  range: ClipRange,
  state: {
    paused: boolean;
    currentTimeMs: number;
    activeRange: ClipRange | null;
  },
): "pause" | "resume" | "start" {
  const active = sameRange(state.activeRange, range);
  const inside =
    state.currentTimeMs >= range.start_ms && state.currentTimeMs < range.end_ms;
  if (active && inside && !state.paused) return "pause";
  if (active && inside && state.currentTimeMs > range.start_ms) return "resume";
  return "start";
}

/** True only while the one report audio element is actually playing this clip. */
export function useClipPlaying(startMs: number, endMs: number): boolean {
  const state = useContext(SourceContext);
  return clipIsPlaying({ start_ms: startMs, end_ms: endMs }, state);
}

/** Render-prop form for existing markup that swaps only its icon and verb. */
export function ClipPlayState({
  startMs,
  endMs,
  children,
}: {
  startMs: number;
  endMs: number;
  children: (playing: boolean) => ReactNode;
}) {
  return <>{children(useClipPlaying(startMs, endMs))}</>;
}

export function ClipPlayIcon({
  playing,
  size,
}: {
  playing: boolean;
  size: number;
}) {
  const Icon = playing ? Pause : Play;
  return <Icon size={size} fill="currentColor" aria-hidden="true" />;
}

/**
 * A Listen control that becomes Pause while its own clip is audibly playing.
 * The click handler stays the caller's; the studio toggles the shared player.
 */
export function ClipListenButton({
  startMs,
  endMs,
  label,
  className,
  iconSize = 13,
  onClick,
  children,
  data,
}: {
  startMs: number;
  endMs: number;
  /** Accessible clip description, announced after "Listen" or "Pause". */
  label: string;
  className?: string;
  iconSize?: number;
  onClick: () => void;
  children?: ReactNode;
  /** Caller hooks such as `{ "data-source-moment": "" }`. */
  data?: Record<`data-${string}`, string>;
}) {
  const playing = useClipPlaying(startMs, endMs);
  return (
    <button
      {...data}
      className={className}
      type="button"
      onClick={onClick}
      aria-label={`${playing ? "Pause" : "Listen"} ${label}`}
      aria-pressed={playing}
      data-clip-playing={playing || undefined}
    >
      <ClipPlayIcon playing={playing} size={iconSize} />
      {playing ? "Pause" : "Listen"}
      {children}
    </button>
  );
}

/** A read-only view of saved local measurements. Failure never prevents report reading. */
export function SourceWaveformProvider({
  submissionId,
  audioRef,
  activeRange = null,
  mediaKey = null,
  children,
}: {
  /** Acquisition submission whose measured waveform may be read; omit for other owners. */
  submissionId?: string;
  audioRef: RefObject<HTMLAudioElement | null>;
  /** The clip range the studio is currently playing, if any. */
  activeRange?: ClipRange | null;
  /**
   * Changes whenever the owner may have replaced its audio element or source
   * (for example its object URL), so playback state is re-subscribed.
   */
  mediaKey?: string | null;
  children: ReactNode;
}) {
  const [source, setSource] = useState<{
    id: string;
    envelope: WaveformEnvelope;
  } | null>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!submissionId) return;
    const controller = new AbortController();
    void fetch(
      `/v1/conversation/acquisition/submissions/${encodeURIComponent(submissionId)}/waveform`,
      {
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      },
    )
      .then(async (response) =>
        response.ok ? parseWaveform(await response.json()) : null,
      )
      .then((envelope) => {
        if (envelope && !controller.signal.aborted)
          setSource({ id: submissionId, envelope });
      })
      .catch(() => {
        /* Keep the audio controls available without a measured envelope. */
      });
    return () => controller.abort();
  }, [submissionId]);
  useEffect(() => {
    const player = audioRef.current;
    if (!player) return;
    const update = () =>
      setCurrentTimeMs(
        Number.isFinite(player.currentTime) ? player.currentTime * 1000 : 0,
      );
    const syncPlaying = () => {
      update();
      setPlaying(!player.paused && !player.ended);
    };
    // Read the element's real state on (re)subscription: it may already be
    // playing, or a source change may have reset it without a pause event.
    syncPlaying();
    const events = ["play", "pause", "ended", "emptied", "loadstart"] as const;
    player.addEventListener("timeupdate", update);
    player.addEventListener("seeked", update);
    player.addEventListener("loadedmetadata", update);
    for (const name of events) player.addEventListener(name, syncPlaying);
    return () => {
      player.removeEventListener("timeupdate", update);
      player.removeEventListener("seeked", update);
      player.removeEventListener("loadedmetadata", update);
      for (const name of events) player.removeEventListener(name, syncPlaying);
    };
  }, [audioRef, submissionId, mediaKey]);
  return (
    <SourceContext.Provider
      value={{
        envelope: source && source.id === submissionId ? source.envelope : null,
        currentTimeMs,
        playing,
        activeRange,
      }}
    >
      {children}
    </SourceContext.Provider>
  );
}

export function waveformBins(
  envelope: WaveformEnvelope,
  startMs = 0,
  endMs = envelope.duration_ms,
  count = 96,
) {
  const start = Math.max(0, startMs),
    end = Math.min(envelope.duration_ms, endMs);
  const levels: (number | null)[] = Array.from({ length: count }, () => null);
  if (end <= start) return levels;
  for (const point of envelope.points) {
    if (point.start_ms < start || point.start_ms >= end || point.level === null)
      continue;
    const index = Math.min(
      count - 1,
      Math.floor(((point.start_ms - start) / (end - start)) * count),
    );
    levels[index] = Math.max(levels[index] ?? 0, point.level);
  }
  return levels;
}

/** A measured RMS envelope, never a synthetic claim about the conversation. */
export function SourceWaveform({
  startMs = 0,
  endMs,
  className = "",
}: {
  startMs?: number;
  endMs?: number;
  className?: string;
}) {
  const { envelope, currentTimeMs } = useContext(SourceContext);
  if (!envelope)
    return (
      <span
        className={`${styles.unavailable} ${className}`}
        aria-label="Audio level preview unavailable"
      />
    );
  const end = Math.min(endMs ?? envelope.duration_ms, envelope.duration_ms);
  const levels = waveformBins(envelope, startMs, end);
  const progress = Math.max(
    0,
    Math.min(1, (currentTimeMs - startMs) / Math.max(1, end - startMs)),
  );
  return (
    <svg
      className={`${styles.waveform} ${className}`}
      viewBox="0 0 480 52"
      preserveAspectRatio="none"
      role="img"
      aria-label="Recorded audio level"
    >
      {levels.map((level, index) =>
        level === null ? null : (
          <line
            key={index}
            x1={index * 5 + 2.5}
            x2={index * 5 + 2.5}
            y1={26 - Math.max(1, Math.pow(level, 0.4) * 24)}
            y2={26 + Math.max(1, Math.pow(level, 0.4) * 24)}
            className={
              index / levels.length <= progress ? styles.played : styles.pending
            }
          />
        ),
      )}
    </svg>
  );
}
