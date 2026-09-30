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

export const CALL_METRICS_RULES = "call-metrics/2";
export const CUT_IN_RULES = { overlap_ms: 250, latch_ms: 100 } as const;
export const PRICE_WORDS =
  /(budget|बजट|price|प्राइस|कीमत|fees?|फीस|charges|कितने का है|कितने का पड़ेगा)/iu;

export const MONOLOGUE_GAP_MS = 2000;

const MONOLOGUE_LIMIT = 3;

export type SpeakerMetrics = {
  talk_ms: number;
  talk_share: number | null;
  questions: number;
  questions_per_minute: number | null;
  cut_ins: number;
  longest_monologue_ms: number;
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

export type CutIn = {
  speaker_id: string;
  over_speaker_id: string;
  segment_id: string;
  over_segment_id: string;
  at_ms: number;
  overlap_ms: number;
};

export type PriceMoment = {
  segment_id: string;
  speaker_id: string;
  at_ms: number;
  silence_ms: number | null;
  next_speaker_id: string | null;
  next_segment_id: string | null;
};

export type LongestReplyAfterQuestion = {
  speaker_id: string;
  question_segment_id: string;
  start_ms: number;
  end_ms: number;
};

export type CallMetrics = {
  time_used_ms: number;
  speakers: Record<string, SpeakerMetrics>;
  curve: CurveBin[];
  monologues: Monologue[];
  cut_ins: CutIn[];
  price_moments: PriceMoment[];
  longest_reply_after_question: LongestReplyAfterQuestion | null;
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
      questions_per_minute:
        timeUsed > 0
          ? round2((questions.get(id) ?? 0) / (timeUsed / 60000))
          : null,
      cut_ins: 0,
      longest_monologue_ms: 0,
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
  for (const run of runs)
    speakers[run.speaker_id].longest_monologue_ms = Math.max(
      speakers[run.speaker_id].longest_monologue_ms,
      run.end_ms - run.start_ms,
    );

  const cutIns: CutIn[] = [];
  for (const [index, segment] of timed.entries()) {
    let overSegment: (typeof timed)[number] | undefined;
    for (const prior of timed.slice(0, index))
      if (
        prior.speaker_id !== segment.speaker_id &&
        (!overSegment || prior.end_ms >= overSegment.end_ms)
      )
        overSegment = prior;
    if (!overSegment) continue;

    const overlap = overSegment.end_ms - segment.start_ms;
    const gap = segment.start_ms - overSegment.end_ms;
    const isCutIn =
      overlap >= CUT_IN_RULES.overlap_ms ||
      (gap >= 0 &&
        gap <= CUT_IN_RULES.latch_ms &&
        !/[.?!।？！…]$/.test(overSegment.text.trim()));
    if (!isCutIn) continue;

    cutIns.push({
      speaker_id: segment.speaker_id,
      over_speaker_id: overSegment.speaker_id,
      segment_id: segment.id,
      over_segment_id: overSegment.id,
      at_ms: segment.start_ms,
      overlap_ms: Math.max(0, overlap),
    });
    speakers[segment.speaker_id].cut_ins += 1;
  }

  const priceMoments: PriceMoment[] = [];
  for (const [index, segment] of timed.entries()) {
    if (!PRICE_WORDS.test(segment.text)) continue;
    const next = timed
      .slice(index + 1)
      .find((candidate) => candidate.speaker_id !== segment.speaker_id);
    priceMoments.push({
      segment_id: segment.id,
      speaker_id: segment.speaker_id,
      at_ms: segment.start_ms,
      silence_ms: next ? Math.max(0, next.start_ms - segment.end_ms) : null,
      next_speaker_id: next?.speaker_id ?? null,
      next_segment_id: next?.id ?? null,
    });
    if (priceMoments.length === 20) break;
  }

  let longestReplyAfterQuestion: LongestReplyAfterQuestion | null = null;
  for (const [index, question] of timed.entries()) {
    if (countQuestions(question.text) === 0) continue;
    const replyIndex = timed.findIndex(
      (candidate, candidateIndex) =>
        candidateIndex > index && candidate.speaker_id !== question.speaker_id,
    );
    if (replyIndex < 0) continue;

    const reply = timed[replyIndex];
    let endMs = reply.end_ms;
    for (
      let nextIndex = replyIndex + 1;
      nextIndex < timed.length;
      nextIndex += 1
    ) {
      const next = timed[nextIndex];
      if (
        next.speaker_id !== reply.speaker_id ||
        next.start_ms - endMs > MONOLOGUE_GAP_MS
      )
        break;
      endMs = Math.max(endMs, next.end_ms);
    }
    const candidate = {
      speaker_id: reply.speaker_id,
      question_segment_id: question.id,
      start_ms: reply.start_ms,
      end_ms: endMs,
    };
    if (
      !longestReplyAfterQuestion ||
      candidate.end_ms - candidate.start_ms >
        longestReplyAfterQuestion.end_ms - longestReplyAfterQuestion.start_ms
    )
      longestReplyAfterQuestion = candidate;
  }

  const monologues = runs
    .sort(
      (a, b) =>
        b.end_ms - b.start_ms - (a.end_ms - a.start_ms) ||
        a.start_ms - b.start_ms,
    )
    .slice(0, MONOLOGUE_LIMIT);

  return {
    time_used_ms: timeUsed,
    speakers,
    curve,
    monologues,
    cut_ins: cutIns,
    price_moments: priceMoments,
    longest_reply_after_question: longestReplyAfterQuestion,
  };
}

export function quietFrom(
  metrics: CallMetrics,
  speakerId: string,
): QuietRun | null {
  if (!(speakerId in metrics.speakers)) return null;
  // The first run that never recovers wins (plan rev 3); when every run
  // recovers, the first run is reported.
  let firstRecovered: QuietRun | null = null;
  let runStart = -1;
  let runLength = 0;
  for (const [index, bin] of metrics.curve.entries()) {
    const share = bin.shares[speakerId];
    const low =
      share !== null && share !== undefined && share < QUIET_RULES.below;
    runLength = low ? runLength + 1 : 0;
    if (runLength === 1) runStart = index;
    if (runLength === QUIET_RULES.min_bins) {
      const run = {
        start_ms: metrics.curve[runStart].start_ms,
        recovered: metrics.curve
          .slice(index + 1)
          .some(
            (later) => (later.shares[speakerId] ?? -1) >= QUIET_RULES.recover,
          ),
      };
      if (!run.recovered) return run;
      firstRecovered ??= run;
    }
  }
  return firstRecovered;
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
