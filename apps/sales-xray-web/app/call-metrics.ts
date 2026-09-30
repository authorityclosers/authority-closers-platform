import type { TranscriptSegment } from "./report-contract";

// System-computed timing visuals for the Overview (AUT-341 plan §3.1).
// Measurements only: no AI, no score. The shared vectors in
// tests/fixtures/call-metrics-vectors.json pin every rule below.

export const QUIET_RULES = {
  bin_ms: 60000,
  below: 0.1,
  min_bins: 3,
  recover: 0.25,
} as const;

export const MONOLOGUE_GAP_MS = 2000;

const MONOLOGUE_LIMIT = 3;

export type SpeakerMetrics = {
  talk_ms: number;
  talk_share: number | null;
  questions: number;
};

export type CurveBin = {
  start_ms: number;
  shares: Record<string, number | null>;
};

export type Monologue = {
  speaker_id: string;
  start_ms: number;
  end_ms: number;
};

export type CallMetrics = {
  time_used_ms: number;
  speakers: Record<string, SpeakerMetrics>;
  curve: CurveBin[];
  monologues: Monologue[];
};

export type TimePromise = {
  promised_ms: number;
  evidence: { segment_id: string }[];
};

export type QuietRun = { start_ms: number; recovered: boolean };

type Interval = [number, number];

const round2 = (value: number) => Math.round(value * 100) / 100;

const hasSpeaker = (
  segment: TranscriptSegment,
): segment is TranscriptSegment & { speaker_id: string } =>
  segment.speaker_id !== null;

// Segments with a speaker and a positive length, ordered by start then end.
function timedSegments(segments: TranscriptSegment[]) {
  return segments
    .filter(hasSpeaker)
    .filter((segment) => segment.end_ms > segment.start_ms)
    .sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms);
}

function union(intervals: Interval[]): Interval[] {
  const merged: Interval[] = [];
  for (const [start, end] of [...intervals].sort((a, b) => a[0] - b[0])) {
    const last = merged.at(-1);
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

function overlapMs(intervals: Interval[], from: number, to: number) {
  let total = 0;
  for (const [start, end] of intervals)
    total += Math.max(0, Math.min(end, to) - Math.max(start, from));
  return total;
}

function countQuestions(text: string) {
  return text.match(/[?？]+/g)?.length ?? 0;
}

export function computeCallMetrics(
  segments: TranscriptSegment[],
  durationMs: number | null,
): CallMetrics {
  const timed = timedSegments(segments);
  const lastEnd = Math.max(0, ...timed.map((segment) => segment.end_ms));
  const timeUsed =
    durationMs !== null && Number.isFinite(durationMs) && durationMs > 0
      ? durationMs
      : lastEnd;

  const talk = new Map<string, Interval[]>();
  const questions = new Map<string, number>();
  for (const segment of segments.filter(hasSpeaker)) {
    const id = segment.speaker_id;
    if (!talk.has(id)) talk.set(id, []);
    questions.set(id, (questions.get(id) ?? 0) + countQuestions(segment.text));
  }
  for (const segment of timed)
    talk.get(segment.speaker_id)!.push([segment.start_ms, segment.end_ms]);
  for (const [id, intervals] of talk) talk.set(id, union(intervals));

  const talkMs = new Map(
    [...talk].map(([id, intervals]) => [id, overlapMs(intervals, 0, Infinity)]),
  );
  const totalMs = [...talkMs.values()].reduce((sum, ms) => sum + ms, 0);
  const speakers: Record<string, SpeakerMetrics> = {};
  for (const [id, ms] of talkMs)
    speakers[id] = {
      talk_ms: ms,
      talk_share: totalMs > 0 ? round2(ms / totalMs) : null,
      questions: questions.get(id) ?? 0,
    };

  const curve: CurveBin[] = [];
  for (let from = 0; from < timeUsed; from += QUIET_RULES.bin_ms) {
    const to = Math.min(from + QUIET_RULES.bin_ms, timeUsed);
    const inBin = [...talk].map(
      ([id, intervals]) => [id, overlapMs(intervals, from, to)] as const,
    );
    const binTotal = inBin.reduce((sum, [, ms]) => sum + ms, 0);
    curve.push({
      start_ms: from,
      shares: Object.fromEntries(
        inBin.map(([id, ms]) => [
          id,
          binTotal > 0 ? round2(ms / binTotal) : null,
        ]),
      ),
    });
  }

  // A later segment of the same speaker joins the run only when no other
  // speaker's segment starts in between (the scan is in start order).
  const runs: Monologue[] = [];
  for (const segment of timed) {
    const run = runs.at(-1);
    if (
      run &&
      run.speaker_id === segment.speaker_id &&
      segment.start_ms - run.end_ms <= MONOLOGUE_GAP_MS
    )
      run.end_ms = Math.max(run.end_ms, segment.end_ms);
    else
      runs.push({
        speaker_id: segment.speaker_id,
        start_ms: segment.start_ms,
        end_ms: segment.end_ms,
      });
  }
  const monologues = runs
    .sort(
      (a, b) =>
        b.end_ms - b.start_ms - (a.end_ms - a.start_ms) ||
        a.start_ms - b.start_ms,
    )
    .slice(0, MONOLOGUE_LIMIT);

  return { time_used_ms: timeUsed, speakers, curve, monologues };
}

export function quietFrom(
  metrics: CallMetrics,
  speakerId: string,
): QuietRun | null {
  if (!(speakerId in metrics.speakers)) return null;
  let runStart = -1;
  let runLength = 0;
  for (const [index, bin] of metrics.curve.entries()) {
    const share = bin.shares[speakerId];
    const low =
      share !== null && share !== undefined && share < QUIET_RULES.below;
    runLength = low ? runLength + 1 : 0;
    if (runLength === 1) runStart = index;
    if (runLength === QUIET_RULES.min_bins) {
      const recovered = metrics.curve
        .slice(index + 1)
        .some(
          (later) => (later.shares[speakerId] ?? -1) >= QUIET_RULES.recover,
        );
      return { start_ms: metrics.curve[runStart].start_ms, recovered };
    }
  }
  return null;
}

export function timePromiseOverrun(
  promise: TimePromise | null,
  segments: TranscriptSegment[],
  timeUsedMs: number,
): number | null {
  const evidenceId = promise?.evidence[0]?.segment_id;
  const segment = segments.find((candidate) => candidate.id === evidenceId);
  if (!promise || !segment) return null;
  return Math.max(0, timeUsedMs - (segment.start_ms + promise.promised_ms));
}
