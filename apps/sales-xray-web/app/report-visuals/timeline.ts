/*
 * Pure helpers for the Report's call timeline: who spoke when, and how many
 * wave bars each stage gets. Everything here is measured from the transcript
 * or the server's sound envelope; nothing is invented or scored.
 */
import type { Transcript } from "../report-contract";

export type Span = { start_ms: number; end_ms: number };

/** Speech of the two people the timeline draws: top (the seller) and bottom. */
export type Speech = { top: Span[]; bottom: Span[] };

export type TimelinePhase = { label: string; start_ms: number; end_ms: number };

/** All the wave bars in a timeline, shared out between its stages. */
export const WAVE_BARS = 96;

/**
 * The two people to draw, from the transcript: the seller on top and the
 * prospect below when roles are known, else the two who talked most.
 */
export function speechFromTranscript(
  transcript: Pick<Transcript, "segments"> | null | undefined,
  roles?: { top?: string | null; bottom?: string | null },
): (Speech & { topId: string; bottomId: string | null }) | null {
  const segments = transcript?.segments ?? [];
  const talk = new Map<string, number>();
  for (const segment of segments)
    if (segment.speaker_id && segment.end_ms > segment.start_ms)
      talk.set(
        segment.speaker_id,
        (talk.get(segment.speaker_id) ?? 0) + segment.end_ms - segment.start_ms,
      );
  const ranked = [...talk.keys()].sort(
    (a, b) => (talk.get(b) ?? 0) - (talk.get(a) ?? 0),
  );
  const topId =
    roles?.top && talk.has(roles.top) ? roles.top : (ranked[0] ?? null);
  if (!topId) return null;
  const bottomId =
    roles?.bottom && talk.has(roles.bottom) && roles.bottom !== topId
      ? roles.bottom
      : (ranked.find((id) => id !== topId) ?? null);
  const spans = (id: string | null) =>
    id
      ? segments
          .filter((s) => s.speaker_id === id && s.end_ms > s.start_ms)
          .map((s) => ({ start_ms: s.start_ms, end_ms: s.end_ms }))
      : [];
  return { top: spans(topId), bottom: spans(bottomId), topId, bottomId };
}

/**
 * For each of `count` equal bins between start and end, the share of the bin
 * (0-1) in which the person was talking.
 */
export function activityBins(
  spans: Span[],
  startMs: number,
  endMs: number,
  count: number,
): number[] {
  const bins = Array.from({ length: Math.max(0, count) }, () => 0);
  const length = endMs - startMs;
  if (!(length > 0) || !count) return bins;
  const width = length / count;
  for (const span of spans) {
    const from = Math.max(span.start_ms, startMs);
    const to = Math.min(span.end_ms, endMs);
    if (to <= from) continue;
    const first = Math.floor((from - startMs) / width);
    const last = Math.min(count - 1, Math.floor((to - startMs - 1e-6) / width));
    for (let index = first; index <= last; index += 1) {
      const binStart = startMs + index * width;
      const overlap = Math.min(to, binStart + width) - Math.max(from, binStart);
      if (overlap > 0) bins[index] += overlap / width;
    }
  }
  return bins.map((value) => Math.min(1, value));
}

/**
 * Stages cleaned for drawing: in time order, inside the call, no zero-length
 * stage, each ending where the next begins.
 */
export function cleanPhases(
  phases: TimelinePhase[] | null | undefined,
  durationMs: number,
): TimelinePhase[] {
  if (!phases?.length || !(durationMs > 0)) return [];
  const sorted = phases
    .filter(
      (phase) =>
        Number.isFinite(phase.start_ms) &&
        Number.isFinite(phase.end_ms) &&
        phase.start_ms < durationMs,
    )
    .map((phase) => ({
      label: phase.label,
      start_ms: Math.max(0, phase.start_ms),
      end_ms: Math.min(durationMs, phase.end_ms),
    }))
    .sort((a, b) => a.start_ms - b.start_ms);
  return sorted
    .map((phase, index) => ({
      ...phase,
      end_ms: Math.min(phase.end_ms, sorted[index + 1]?.start_ms ?? durationMs),
    }))
    .filter((phase) => phase.end_ms > phase.start_ms);
}

/**
 * Shares `total` bars between stages by length, each stage at least `min`.
 * The result always sums to `total` when total >= min * stages.
 */
export function allocateBars(
  lengths: number[],
  total = WAVE_BARS,
  min = 3,
): number[] {
  if (!lengths.length) return [];
  const floor = Math.min(min, Math.floor(total / lengths.length));
  const sum = lengths.reduce((a, b) => a + Math.max(0, b), 0);
  const spare = total - floor * lengths.length;
  if (!(sum > 0) || spare <= 0) return lengths.map(() => floor);
  const exact = lengths.map((length) => (Math.max(0, length) / sum) * spare);
  const bars = exact.map((value) => floor + Math.floor(value));
  let left = total - bars.reduce((a, b) => a + b, 0);
  const order = exact
    .map((value, index) => ({ index, rest: value - Math.floor(value) }))
    .sort((a, b) => b.rest - a.rest);
  for (let i = 0; left > 0; i = (i + 1) % order.length, left -= 1)
    bars[order[i].index] += 1;
  return bars;
}

/** Position (0-1) of a time inside a stretch of the call, clamped. */
export function positionIn(atMs: number, startMs: number, endMs: number) {
  if (!(endMs > startMs)) return 0;
  return Math.min(1, Math.max(0, (atMs - startMs) / (endMs - startMs)));
}

/** Two measured numbers as rounded shares that add up to 100. */
export function shares(a: number, b: number): [number, number] {
  const sum = Math.max(0, a) + Math.max(0, b);
  if (!(sum > 0)) return [0, 0];
  const first = Math.round((Math.max(0, a) / sum) * 100);
  return [first, 100 - first];
}

/** "62 : 38" (a figure the report shows as a pair) as two numbers. */
export function splitPair(value: string): [number, number] | null {
  const match = /^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$/.exec(value);
  return match ? [Number(match[1]), Number(match[2])] : null;
}

/**
 * Bar heights (0-1) above and below the line for one stretch: who talked
 * (activity) shaped by how loud the call was there (the measured envelope,
 * when the server has one). Without an envelope the activity alone.
 */
export function voiceBars(
  top: number[],
  bottom: number[],
  levels?: (number | null)[] | null,
): { top: number[]; bottom: number[] } {
  const shape = (activity: number[]) =>
    activity.map((share, index) => {
      if (!(share > 0)) return 0;
      const level = levels?.[index];
      if (level == null) return share;
      return Math.max(0.12, level) * Math.min(1, share * 1.25);
    });
  return { top: shape(top), bottom: shape(bottom) };
}
