import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
  TranscriptSegment,
} from "./report-contract";

/**
 * Plain measurements read straight from the transcript's own text and timings.
 * No model is asked anything here: every number is counted, never guessed.
 */

// A switch within this gap still counts as the same person holding the floor.
export const SAME_TURN_GAP_MS = 1500;

export function voiceOf(segment: TranscriptSegment): string {
  return segment.speaker_id ?? "unknown";
}

/** Speaker labels in the order they first spoke. */
export function voicesOf(transcript: Transcript): string[] {
  const voices: string[] = [];
  for (const segment of transcript.segments) {
    const voice = voiceOf(segment);
    if (!voices.includes(voice)) voices.push(voice);
  }
  return voices;
}

/** Sentences that end in a question mark, each with its segment. */
export function questionsAsked(
  transcript: Transcript,
): Array<{ segment: TranscriptSegment; voice: string; text: string }> {
  const rows: Array<{
    segment: TranscriptSegment;
    voice: string;
    text: string;
  }> = [];
  for (const segment of transcript.segments) {
    if (!/[?？]/u.test(segment.text)) continue;
    for (const sentence of segment.text.split(/(?<=[?？।.!])\s+/u)) {
      if (/[?？]\s*$/u.test(sentence.trim()))
        rows.push({ segment, voice: voiceOf(segment), text: sentence.trim() });
    }
  }
  return rows;
}

export type VoiceStats = {
  id: string;
  talkMs: number;
  share: number;
  words: number;
  questions: number;
  longestMs: number;
  firstLine: string | null;
};

export function voiceStats(transcript: Transcript): VoiceStats[] {
  const voices = voicesOf(transcript);
  const stats = new Map<string, VoiceStats>(
    voices.map((id) => [
      id,
      {
        id,
        talkMs: 0,
        share: 0,
        words: 0,
        questions: 0,
        longestMs: 0,
        firstLine: null,
      },
    ]),
  );
  let run: { voice: string; start: number; end: number } | null = null;
  for (const segment of transcript.segments) {
    const voice = voiceOf(segment);
    const entry = stats.get(voice)!;
    entry.talkMs += Math.max(0, segment.end_ms - segment.start_ms);
    const words = segment.text.trim().split(/\s+/u).filter(Boolean);
    entry.words += words.length;
    if (!entry.firstLine && words.length >= 4) entry.firstLine = segment.text;
    if (
      run &&
      run.voice === voice &&
      segment.start_ms - run.end <= SAME_TURN_GAP_MS
    )
      run.end = Math.max(run.end, segment.end_ms);
    else run = { voice, start: segment.start_ms, end: segment.end_ms };
    entry.longestMs = Math.max(entry.longestMs, run.end - run.start);
  }
  for (const row of questionsAsked(transcript))
    stats.get(row.voice)!.questions += 1;
  const total = [...stats.values()].reduce((sum, s) => sum + s.talkMs, 0);
  for (const entry of stats.values())
    entry.share = total > 0 ? entry.talkMs / total : 0;
  return voices.map((id) => stats.get(id)!);
}

/**
 * One voice's share of all talking in each window of the call (0–1), or null
 * where nobody spoke in that window.
 */
export function talkShareSeries(
  transcript: Transcript,
  voice: string,
  binMs = 60_000,
): Array<number | null> {
  const total = Math.max(1, transcript.duration_ms);
  const bins = Math.max(1, Math.ceil(total / binMs));
  const mine = new Array<number>(bins).fill(0);
  const all = new Array<number>(bins).fill(0);
  for (const segment of transcript.segments) {
    const first = Math.max(0, Math.floor(segment.start_ms / binMs));
    const last = Math.min(bins - 1, Math.floor((segment.end_ms - 1) / binMs));
    for (let bin = first; bin <= last; bin += 1) {
      const overlap =
        Math.min(segment.end_ms, (bin + 1) * binMs) -
        Math.max(segment.start_ms, bin * binMs);
      if (overlap <= 0) continue;
      all[bin] += overlap;
      if (voiceOf(segment) === voice) mine[bin] += overlap;
    }
  }
  return all.map((ms, bin) => (ms > 0 ? mine[bin] / ms : null));
}

export type HeardNumber = {
  id: string;
  segment: TranscriptSegment;
  voice: string;
  /** As spoken, e.g. "₹15-20 लाख" or "1 CR". */
  spoken: string;
  kind: "money" | "percent" | "time" | "quantity";
};

const UNIT_KIND: Array<[RegExp, HeardNumber["kind"]]> = [
  [
    /^(cr|crore|crores|करोड़|करोड|lakh|lakhs|lac|लाख|l|k|thousand|हज़ार|हजार)$/iu,
    "quantity",
  ],
  [/^(%|percent|प्रतिशत|टक्के|टक्का)$/iu, "percent"],
  [
    /^(days?|दिन|months?|महीने|महीना|years?|साल|बरस|minutes?|मिनट|min)$/iu,
    "time",
  ],
];
const NUMBER =
  /(?<![\p{L}\d])((?:₹|Rs\.?|INR)\s*)?(\d+(?:[.,]\d+)?)(?:\s*(?:-|–|to|से|,)\s*(\d+(?:[.,]\d+)?))?\s*(CR|Cr|cr|crores?|करोड़|करोड|lakhs?|lac|लाख|L(?![\p{L}])|K(?![\p{L}])|thousand|हज़ार|हजार|rupees?|रुपये|रुपए|%|percent|प्रतिशत|टक्के|टक्का|days?|दिन|months?|महीने|महीना|years?|साल|बरस|minutes?|मिनट|min(?![\p{L}]))?/giu;

/**
 * Numbers said with a unit, as spoken. Magnitudes stay quantities unless
 * nearby wording or an explicit currency symbol identifies money.
 */
export function numbersHeard(transcript: Transcript): HeardNumber[] {
  const rows: HeardNumber[] = [];
  for (const segment of transcript.segments) {
    let match: RegExpExecArray | null;
    NUMBER.lastIndex = 0;
    let index = 0;
    while ((match = NUMBER.exec(segment.text))) {
      const [spokenRaw, rupee, , , unit] = match;
      const unitKind = UNIT_KIND.find(([pattern]) =>
        pattern.test(unit ?? ""),
      )?.[1];
      const before = segment.text.slice(
        Math.max(0, match.index - 40),
        match.index,
      );
      const after = segment.text.slice(
        match.index + spokenRaw.length,
        match.index + spokenRaw.length + 32,
      );
      const objectCount =
        /^\s*(?:customers?|users?|people|members?|clients?|staff|employees?|units?|items?|orders?|products?|families|visits|tanks?|lit(?:er|re)s?)\b/iu.test(
          after,
        );
      const currencyEvidence =
        rupee ||
        /^(?:rupees?|रुपये|रुपए)$/iu.test(unit ?? "") ||
        (!objectCount &&
          (/\b(?:inr|rs\.?|rupees?|रुप(?:ये|ए)|कीमत|मूल्य|पैसे|बजट|टर्नओवर)\s*$/iu.test(
            before,
          ) ||
            /^\s*(?:rupees?|inr|रुप(?:ये|ए))\b/iu.test(after) ||
            /\b(?:price|cost|budget|fee|salary|revenue|sales|turnover|profit|amount|money)\s+(?:of\s+)?$/iu.test(
              before,
            ) ||
            /^\s*(?:worth|in\s+(?:revenue|sales|turnover|profit))\b/iu.test(
              after,
            )));
      if (!unit && !currencyEvidence) continue;
      const kind = currencyEvidence
        ? "money"
        : unitKind === "quantity"
          ? "quantity"
          : unitKind;
      if (!kind) continue;
      rows.push({
        id: `${segment.id}:${index}`,
        segment,
        voice: voiceOf(segment),
        spoken: spokenRaw.trim(),
        kind,
      });
      index += 1;
    }
  }
  return rows;
}

/** Share of letters written in Devanagari and in Latin script. */
export function scriptMix(transcript: Transcript) {
  let devanagari = 0;
  let latin = 0;
  for (const segment of transcript.segments) {
    devanagari += (segment.text.match(/[ऀ-ॿ]/gu) ?? []).length;
    latin += (segment.text.match(/[A-Za-z]/g) ?? []).length;
  }
  const total = devanagari + latin;
  return total
    ? { devanagari: devanagari / total, latin: latin / total }
    : { devanagari: 0, latin: 0 };
}

const MINUTES =
  /(?<![\p{L}\d])(\d+)(?:\s*(?:-|–|to|से|,)?\s*(\d+))?\s*(?:minutes?|मिनट|min(?![\p{L}]))/giu;

function hasTimeRequestContext(text: string, start: number, end: number) {
  const before = text.slice(Math.max(0, start - 60), start);
  const after = text.slice(end, end + 36);
  return (
    /\b(?:give\s+me|allow\s+me|reserve|block)(?:\s+[\p{L}\d]+){0,2}\s*$/iu.test(
      before,
    ) ||
    /\b(?:i|we)\s*(?:'ll|will)\s+(?:call|send|get\s+back)\b[\s\S]{0,36}\bin\s*$/iu.test(
      before,
    ) ||
    (/(?:मुझे|हमें)(?:\s+[\p{L}\d]+){0,5}\s*$/u.test(before) &&
      /^\s*(?:का\s+time\s+लगेगा|तक\s+चलेगा|तक\s+चलेगी)/u.test(after)) ||
    /^\s*(?:दीजिए|दीजिये|दें|दे दीजिए)/u.test(after)
  );
}

/** Minutes of call time asked for or agreed in the opening three minutes. */
export function timePromise(transcript: Transcript) {
  const minutes: number[] = [];
  const segments: TranscriptSegment[] = [];
  for (const segment of transcript.segments) {
    if (segment.start_ms > 180_000) break;
    MINUTES.lastIndex = 0;
    let match: RegExpExecArray | null;
    let found = false;
    while ((match = MINUTES.exec(segment.text))) {
      if (!hasTimeRequestContext(segment.text, match.index, MINUTES.lastIndex))
        continue;
      for (const value of [match[1], match[2]])
        if (value) {
          const number = Number(value);
          if (number >= 2 && number <= 90) {
            minutes.push(number);
            found = true;
          }
        }
    }
    if (found) segments.push(segment);
  }
  MINUTES.lastIndex = 0;
  if (!minutes.length) return null;
  return { upToMinutes: Math.max(...minutes), segments };
}

const PRICE_WORDS =
  /(budget|बजट|price|प्राइस|कीमत|fees?|फीस|charges|कितने का है|कितने का पड़ेगा)/iu;

/** Segments where price, fees or budget came up. */
export function priceTalk(transcript: Transcript): TranscriptSegment[] {
  return transcript.segments.filter((segment) =>
    PRICE_WORDS.test(segment.text),
  );
}

const FINDING_KINDS = [
  ["strengths", "Done well"],
  ["missed_opportunities", "Missed chance"],
  ["improvements", "To improve"],
  ["objection_analysis", "Pushback"],
  ["closing_analysis", "Closing"],
] as const;

/** Every finding the report made, with a plain kind label. */
export function reportFindings(report: SalesReport): Array<{
  kind: string;
  title: string;
  evidence: ReportEvidence[];
}> {
  return FINDING_KINDS.flatMap(([key, kind]) =>
    ((report[key] as Finding[] | undefined) ?? []).map((finding) => ({
      kind,
      title: finding.title,
      evidence: finding.evidence,
    })),
  );
}
