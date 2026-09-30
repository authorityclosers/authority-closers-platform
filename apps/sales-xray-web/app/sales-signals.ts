import { computeCallMetrics } from "./call-metrics";
import type { Transcript, TranscriptSegment } from "./report-contract";

// Salesperson signals measured from the transcript's own timings and words
// (AUT-416). No AI and no score: every item points at the exact moment, and
// word-based finds are labelled so the user checks them by listening.

type Timed = TranscriptSegment & { speaker_id: string };

export type Roles = { seller: string; prospect: string };

export type Moment = {
  segment: TranscriptSegment;
  /** The exact words, one sentence where possible. */
  text: string;
  start_ms: number;
};

export type UnansweredQuestion = Moment & {
  reason: "no reply" | "very short reply";
};

export type TalkOver = Moment & {
  /** The prospect words that were cut. */
  cut: string;
  overlap_ms: number;
};

export type PriceMoment = Moment & {
  silence_ms: number | null;
  reply: Moment | null;
  pushback: boolean;
};

export type MoreSignals = {
  first_question_ms: number | null;
  seller_questions_per_10_min: number | null;
  longest_answer: { start_ms: number; length_ms: number } | null;
  /** The minute where the prospect held their highest talk share (half or
   * more). Talk share only: it says nothing about interest or openness. */
  prospect_peak_ms: number | null;
  next_step_ms: number | null;
};

const SENTENCE_BREAK = /(?<=[?？।.!])\s+/u;
const PROBLEM_WORDS =
  /(problem|issue|stuck|loss|difficult|tough|worr|slow|not working|दिक्कत|परेशानी|समस्या|प्रॉब्लम|प्रॉब्लेम|फंस|फँस|नुकसान|मुश्किल|टेंशन|नहीं हो रहा|नहीं मिल|अडचण|त्रास|अडकल)/iu;
const PRICE_WORDS =
  /(budget|बजट|price|प्राइस|कीमत|fees?|फीस|charges|cost|रुपये|₹|कितने का)/iu;
const PUSHBACK_WORDS =
  /(expensive|costly|too much|discount|high|महंगा|महँगा|ज़्यादा|ज्यादा|कम कर|डिस्काउंट|सोच|think about|later|बाद में|महाग)/iu;
const PROMISE_WORDS =
  /(i(?:'|’| wi)ll (?:send|share|call|mail|email|whatsapp|forward|check|get back|arrange|connect)|will (?:send|share|call|mail|forward)|भेज (?:दूंगा|दूँगा|देता|देंगे|दूंगी|दूँगी)|भेजता हूं|भेजता हूँ|शेयर कर (?:दूंगा|दूँगा|देता|देंगे)|कॉल कर(?:ूंगा|ूँगा|ता हूं|ेंगे)|बता (?:दूंगा|दूँगा|देता|देंगे)|पाठव(?:तो|ते|ीन)|कळव(?:तो|ीन))/iu;
const NEXT_STEP_WORDS =
  /(tomorrow|next week|meeting|call back|demo|visit|appointment|schedule|कल|परसों|मीटिंग|डेमो|विजिट|मिलते|भेटू|उद्या)/iu;

const words = (text: string) => text.trim().split(/\s+/).filter(Boolean).length;

function timed(transcript: Transcript): Timed[] {
  return transcript.segments
    .filter((segment): segment is Timed => segment.speaker_id !== null)
    .filter((segment) => segment.end_ms > segment.start_ms)
    .sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms);
}

function sentences(text: string) {
  return text
    .split(SENTENCE_BREAK)
    .map((part) => part.trim())
    .filter(Boolean);
}

function moment(segment: TranscriptSegment, text = segment.text): Moment {
  return { segment, text: text.trim(), start_ms: segment.start_ms };
}

/** The voices marked as salesperson (or you) and prospect on the call map. */
export function confirmedRoles(
  voices: string[],
  roles: Record<string, string | null | undefined>,
): Roles | null {
  let seller = voices.find(
    (id) => roles[id] === "you" || roles[id] === "salesperson",
  );
  let prospect = voices.find((id) => roles[id] === "prospect");
  if (voices.length === 2) {
    if (seller && !prospect) prospect = voices.find((id) => id !== seller);
    if (prospect && !seller) seller = voices.find((id) => id !== prospect);
  }
  return seller && prospect && seller !== prospect
    ? { seller, prospect }
    : null;
}

/** Sentences where the prospect described a problem, in their own words. */
export function ownWords(transcript: Transcript, roles: Roles): Moment[] {
  const found: Moment[] = [];
  for (const segment of timed(transcript)) {
    if (segment.speaker_id !== roles.prospect) continue;
    for (const sentence of sentences(segment.text))
      if (PROBLEM_WORDS.test(sentence) && words(sentence) >= 3)
        found.push(moment(segment, sentence));
  }
  return found.slice(0, 6);
}

/** Prospect questions followed by no reply, or a reply of a few words. */
export function unansweredQuestions(
  transcript: Transcript,
  roles: Roles,
): UnansweredQuestion[] {
  const list = timed(transcript);
  const found: UnansweredQuestion[] = [];
  list.forEach((segment, index) => {
    if (segment.speaker_id !== roles.prospect) return;
    const asked = sentences(segment.text).filter((part) => /[?？]$/.test(part));
    if (!asked.length) return;
    // The prospect's back-to-back lines are one turn; the reply is what the
    // salesperson says before the prospect speaks again after that.
    // A reply must start within 10 s of the last words before it.
    const replies: Timed[] = [];
    let lastEnd = segment.end_ms;
    for (const next of list.slice(index + 1)) {
      if (next.speaker_id === roles.prospect) {
        if (replies.length) break;
        lastEnd = next.end_ms;
        continue;
      }
      if (next.start_ms - lastEnd > 10_000) break;
      if (next.speaker_id === roles.seller) {
        replies.push(next);
        lastEnd = next.end_ms;
      }
    }
    const replyWords = replies.reduce(
      (sum, reply) => sum + words(reply.text),
      0,
    );
    const question = asked.at(-1)!;
    if (!replies.length)
      found.push({ ...moment(segment, question), reason: "no reply" });
    else if (replyWords < 4)
      found.push({ ...moment(segment, question), reason: "very short reply" });
  });
  return found;
}

/** The salesperson starting to talk while the prospect was mid-sentence. */
export function talkOvers(transcript: Transcript, roles: Roles): TalkOver[] {
  const list = timed(transcript);
  const prospectTurns = list.filter(
    (segment) => segment.speaker_id === roles.prospect,
  );
  const found: TalkOver[] = [];
  for (const segment of list) {
    if (segment.speaker_id !== roles.seller) continue;
    const cut = prospectTurns.find(
      (turn) =>
        (segment.start_ms > turn.start_ms + 500 &&
          segment.start_ms < turn.end_ms - 300) ||
        (segment.start_ms >= turn.end_ms &&
          segment.start_ms - turn.end_ms < 250 &&
          !/[?？।.!]$/.test(turn.text.trim())),
    );
    if (!cut) continue;
    found.push({
      ...moment(segment, sentences(segment.text)[0] ?? segment.text),
      cut: sentences(cut.text).at(-1) ?? cut.text,
      overlap_ms: Math.max(0, cut.end_ms - segment.start_ms),
    });
  }
  return found;
}

/** Each time the salesperson said a price: the silence, and what came back. */
export function afterPrice(
  transcript: Transcript,
  roles: Roles,
): PriceMoment[] {
  const list = timed(transcript);
  const found: PriceMoment[] = [];
  list.forEach((segment, index) => {
    if (segment.speaker_id !== roles.seller || !PRICE_WORDS.test(segment.text))
      return;
    const said = sentences(segment.text).find((part) => PRICE_WORDS.test(part));
    const reply = list
      .slice(index + 1)
      .find((next) => next.speaker_id === roles.prospect);
    const replyText = reply ? (sentences(reply.text)[0] ?? reply.text) : "";
    found.push({
      ...moment(segment, said ?? segment.text),
      silence_ms: reply ? Math.max(0, reply.start_ms - segment.end_ms) : null,
      reply: reply ? moment(reply, replyText) : null,
      pushback: reply ? PUSHBACK_WORDS.test(reply.text) : false,
    });
  });
  return found.slice(0, 4);
}

/** Things the salesperson said they would do after the call. */
export function promises(transcript: Transcript, roles: Roles): Moment[] {
  const found: Moment[] = [];
  for (const segment of timed(transcript)) {
    if (segment.speaker_id !== roles.seller) continue;
    for (const sentence of sentences(segment.text))
      if (PROMISE_WORDS.test(sentence)) found.push(moment(segment, sentence));
  }
  return found;
}

/** A few timing facts that show how the call was run. */
export function moreSignals(transcript: Transcript, roles: Roles): MoreSignals {
  const list = timed(transcript);
  const duration =
    transcript.duration_ms && transcript.duration_ms > 0
      ? transcript.duration_ms
      : Math.max(0, ...list.map((segment) => segment.end_ms));
  const metrics = computeCallMetrics(transcript.segments, duration);

  const firstQuestion = list.find(
    (segment) =>
      segment.speaker_id === roles.seller && /[?？]/.test(segment.text),
  );
  const sellerQuestions = metrics.speakers[roles.seller]?.questions ?? 0;

  let longest: MoreSignals["longest_answer"] = null;
  list.forEach((segment, index) => {
    if (segment.speaker_id !== roles.prospect || !/[?？]/.test(segment.text))
      return;
    let start = -1;
    let end = -1;
    for (const next of list.slice(index + 1)) {
      if (next.speaker_id === roles.prospect) {
        if (start >= 0) break;
        continue;
      }
      if (next.speaker_id !== roles.seller) continue;
      if (start < 0) start = next.start_ms;
      else if (next.start_ms - end > 2000) break;
      end = Math.max(end, next.end_ms);
    }
    if (start >= 0 && (!longest || end - start > longest.length_ms))
      longest = { start_ms: start, length_ms: end - start };
  });

  let opened: { start_ms: number; share: number } | null = null;
  for (const bin of metrics.curve) {
    const share = bin.shares[roles.prospect];
    if (share !== null && share !== undefined && share >= 0.5)
      if (!opened || share > opened.share)
        opened = { start_ms: bin.start_ms, share };
  }

  const nextStep = list.find(
    (segment) =>
      segment.start_ms >= duration * 0.5 && NEXT_STEP_WORDS.test(segment.text),
  );

  return {
    first_question_ms: firstQuestion?.start_ms ?? null,
    seller_questions_per_10_min:
      duration > 0
        ? Math.round((sellerQuestions / duration) * 600_000 * 10) / 10
        : null,
    longest_answer: longest,
    prospect_peak_ms: opened?.start_ms ?? null,
    next_step_ms: nextStep?.start_ms ?? null,
  };
}
