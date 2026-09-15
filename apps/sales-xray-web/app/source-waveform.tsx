"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
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

type SourceState = { envelope: WaveformEnvelope | null; currentTimeMs: number };
const SourceContext = createContext<SourceState>({
  envelope: null,
  currentTimeMs: 0,
});

/** A read-only view of saved local measurements. Failure never prevents report reading. */
export function SourceWaveformProvider({
  submissionId,
  audioRef,
  children,
}: {
  submissionId?: string;
  audioRef: RefObject<HTMLAudioElement | null>;
  children: ReactNode;
}) {
  const [source, setSource] = useState<{
    id: string;
    envelope: WaveformEnvelope;
  } | null>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
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
    player.addEventListener("timeupdate", update);
    player.addEventListener("seeked", update);
    player.addEventListener("loadedmetadata", update);
    return () => {
      player.removeEventListener("timeupdate", update);
      player.removeEventListener("seeked", update);
      player.removeEventListener("loadedmetadata", update);
    };
  }, [audioRef, submissionId]);
  return (
    <SourceContext.Provider
      value={{
        envelope: source && source.id === submissionId ? source.envelope : null,
        currentTimeMs,
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
