"use client";

/*
 * The call itself while it is analysed (owner, 11 Oct: "this wave loading is
 * a nice one"; 16:00: one continuous screen with the real waveform). The
 * server's measured envelope draws the call as soon as it has one (until
 * then the motif stands in, marked as such for screen readers). The teal
 * part grows as each step finishes: it marks finished steps, not time
 * listened, and never moves on a timer.
 */
import { useEffect, useState, type CSSProperties } from "react";

import {
  parseWaveform,
  waveformBins,
  type WaveformEnvelope,
} from "./source-waveform";
import styles from "./analysis-wave.module.css";

const BARS = 96;

// A fixed pattern (identical on server and client) until the measurement.
const MOTIF = Array.from({ length: BARS }, (_, index) => {
  const envelope = Math.abs(Math.sin(index * 0.15) * Math.cos(index * 0.035));
  const grain = ((index * 37) % 11) / 11;
  return 0.12 + 0.8 * (0.28 + 0.72 * envelope) * (0.6 + 0.4 * grain);
});

/**
 * The measured envelope for a saved call, read again whenever `retryKey`
 * changes (each new stage) until the server has one; null until then.
 */
export function useMeasuredWave(
  submissionId: string | undefined,
  retryKey: unknown,
): WaveformEnvelope | null {
  const [found, setFound] = useState<{
    id: string;
    envelope: WaveformEnvelope;
  } | null>(null);
  const have = found !== null && found.id === submissionId;
  useEffect(() => {
    if (!submissionId || have) return;
    const controller = new AbortController();
    fetch(
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
          setFound({ id: submissionId, envelope });
      })
      .catch(() => {
        // Not measured yet, or offline: the motif stays; asked again later.
      });
    return () => controller.abort();
  }, [submissionId, have, retryKey]);
  return have ? found.envelope : null;
}

export type WaveState = "arriving" | "working" | "attention" | "done" | "still";

/**
 * `arrived` (0-1): how much of the file has reached us (uploading); bars
 * beyond it are faint. `played` (0-1): the share of steps finished.
 */
export function AnalysisWave({
  envelope,
  arrived = 1,
  played,
  state,
}: {
  envelope: WaveformEnvelope | null;
  arrived?: number;
  played: number;
  state: WaveState;
}) {
  const levels = envelope
    ? waveformBins(envelope, 0, envelope.duration_ms, BARS).map((level) =>
        level === null ? 0.04 : 0.08 + 0.92 * level,
      )
    : MOTIF;
  const label =
    state === "arriving"
      ? `Uploading your call, ${Math.round(arrived * 100)}% sent`
      : state === "done"
        ? "Your call, fully analysed"
        : envelope
          ? "Your call's sound level over its length"
          : "Your call";
  return (
    <div
      className={styles.wave}
      data-state={state}
      data-measured={envelope ? "" : undefined}
      role="img"
      aria-label={label}
      style={{ "--played": played, "--arrived": arrived } as CSSProperties}
    >
      {levels.map((level, index) => {
        const at = (index + 0.5) / BARS;
        return (
          <i
            key={index}
            data-played={at <= played ? "" : undefined}
            data-next={at > played && at <= played + 1 / 3 ? "" : undefined}
            data-pending={at > arrived ? "" : undefined}
            style={
              {
                "--h": `${Math.round(Math.max(4, level * 100))}%`,
                "--i": index,
              } as CSSProperties
            }
          />
        );
      })}
      {/* The scanning light the owner liked on the upload screen: across the
          whole call while it arrives, then over the current step's stretch. */}
      <span className={styles.beam} aria-hidden="true" />
    </div>
  );
}
