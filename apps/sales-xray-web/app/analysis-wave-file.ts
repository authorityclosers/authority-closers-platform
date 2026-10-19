"use client";

/*
 * The chosen file's own wave, measured in the browser before it is sent
 * (owner, 11 Oct: one continuous screen with the call's real wave). Same
 * measure as the server's envelope: the loudest channel's RMS level per
 * window, linear 0-1. Nothing leaves the device; the file is decoded at a low
 * sample rate. When the browser can't decode the format or the device is
 * short of memory there is no wave and the motif stands in, as before.
 */
import { useEffect, useState } from "react";

import type { WaveformEnvelope } from "./source-waveform";

/** Low enough to keep a 60-minute call small in memory, ample for loudness. */
const DECODE_RATE = 8_000;
/** At most this many points, like the server's envelope (and its parser). */
const MAX_POINTS = 1_200;
/** One point per second of call when the call is short enough. */
const WINDOW_MS = 1_000;
/** Above this the upload limit refuses the file anyway. */
const MAX_FILE_BYTES = 64 * 1048576;

/**
 * The envelope of decoded samples: per window, the loudest channel's RMS.
 * Pure, so it can be tested without a browser.
 */
export function envelopeFromSamples(
  channels: readonly Float32Array[],
  sampleRate: number,
): WaveformEnvelope | null {
  const length = channels[0]?.length ?? 0;
  if (!length || !(sampleRate > 0)) return null;
  const durationMs = Math.round((length / sampleRate) * 1000);
  if (!(durationMs > 0)) return null;
  const count = Math.max(
    1,
    Math.min(MAX_POINTS, Math.ceil(durationMs / WINDOW_MS), length),
  );
  const points: WaveformEnvelope["points"] = [];
  let previousStart = -1;
  for (let point = 0; point < count; point += 1) {
    const from = Math.floor((point * length) / count);
    const to = Math.max(from + 1, Math.floor(((point + 1) * length) / count));
    const startMs = Math.floor((from / sampleRate) * 1000);
    // Windows shorter than a millisecond would repeat a start time.
    if (startMs <= previousStart) continue;
    previousStart = startMs;
    let loudest = 0;
    for (const samples of channels) {
      let sum = 0;
      for (let index = from; index < to; index += 1)
        sum += samples[index] * samples[index];
      loudest = Math.max(loudest, Math.sqrt(sum / (to - from)));
    }
    points.push({ start_ms: startMs, level: Math.min(1, loudest) });
  }
  return {
    schema: "ac.sales-xray.waveform/1",
    kind: "rms_envelope",
    duration_ms: durationMs,
    points,
  };
}

type OfflineContextClass = new (
  channels: number,
  length: number,
  sampleRate: number,
) => BaseAudioContext;

async function decode(file: File): Promise<WaveformEnvelope | null> {
  if (typeof window === "undefined") return null;
  if (!(file.size > 0) || file.size > MAX_FILE_BYTES) return null;
  // A phone short of memory keeps the motif (Chrome reports this; Safari not).
  const memory = (navigator as Navigator & { deviceMemory?: number })
    .deviceMemory;
  if (memory !== undefined && memory < 4) return null;
  const Offline: OfflineContextClass | undefined =
    window.OfflineAudioContext ??
    (window as Window & { webkitOfflineAudioContext?: OfflineContextClass })
      .webkitOfflineAudioContext;
  if (!Offline) return null;
  const context = new Offline(1, 1, DECODE_RATE);
  const audio = await context.decodeAudioData(await file.arrayBuffer());
  const channels = Array.from({ length: audio.numberOfChannels }, (_, index) =>
    audio.getChannelData(index),
  );
  return envelopeFromSamples(channels, audio.sampleRate);
}

// One measurement per file, shared by the file card and the analysis panel.
const measured = new WeakMap<File, Promise<WaveformEnvelope | null>>();

export function measureFileWave(file: File): Promise<WaveformEnvelope | null> {
  let pending = measured.get(file);
  if (!pending) {
    pending = decode(file).catch(() => null);
    measured.set(file, pending);
  }
  return pending;
}

/**
 * The chosen file's wave for the call on screen: only when that file was sent
 * as this very call. Opening another call while a file is still chosen must
 * never draw the earlier file's shape over it (owner, 19 Oct: "old waveform
 * flashes").
 */
export function waveForCall(
  sent: { file: File; callId: string } | null,
  file: File | null | undefined,
  callId: string | null | undefined,
  wave: WaveformEnvelope | null,
): WaveformEnvelope | null {
  return sent && file && callId && sent.file === file && sent.callId === callId
    ? wave
    : null;
}

/** The file's measured wave once it is ready; null until then or if none. */
export function useFileWave(
  file: File | null | undefined,
): WaveformEnvelope | null {
  const [found, setFound] = useState<{
    file: File;
    envelope: WaveformEnvelope;
  } | null>(null);
  useEffect(() => {
    if (!file) return;
    let live = true;
    void measureFileWave(file).then((envelope) => {
      if (live && envelope) setFound({ file, envelope });
    });
    return () => {
      live = false;
    };
  }, [file]);
  return found && file && found.file === file ? found.envelope : null;
}
