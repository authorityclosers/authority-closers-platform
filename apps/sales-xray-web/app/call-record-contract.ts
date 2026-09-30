/**
 * Strict parser for call-record/1 (L1 Call Record).
 * Call numbers and facts (quote + time + seek). No scoring or judgement words.
 */

export class CallRecordContractError extends Error {
  constructor(code: string) {
    super(code);
    this.name = "CallRecordContractError";
  }
}

export type CallRecordEvidence = Readonly<{
  segment_id: string;
  quote: string;
  start_ms: number;
  end_ms: number;
}>;

export type CallRecordSpeaker = Readonly<{
  speaker_id: string;
  talk_ms: number;
  talk_share: number;
  questions: number;
  longest_monologue_ms: number;
}>;

export type CallRecordNumbers = Readonly<{
  duration_ms: number;
  speakers: CallRecordSpeaker[];
  overlaps: number;
}>;

export type CallRecordFact = Readonly<{
  statement: string;
  evidence: CallRecordEvidence[];
  tag?: string | null;
}>;

export type CallRecord = Readonly<{
  version: "call-record/1";
  numbers: CallRecordNumbers;
  facts: CallRecordFact[];
  tags: string[] | Record<string, unknown> | null;
  call_type: string | null;
}>;

function fail(code: string): never {
  throw new CallRecordContractError(code);
}

function record(value: unknown, code = "call_record_invalid"): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(code);
  return value as Record<string, unknown>;
}

function nonNegativeInteger(value: unknown, code = "call_record_number_invalid"): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    fail(code);
  }
  return value;
}

function talkShare(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    fail("call_record_talk_share_invalid");
  }
  return value;
}

function nonEmptyString(value: unknown, code = "call_record_string_invalid"): string {
  if (typeof value !== "string" || !value.trim()) {
    fail(code);
  }
  return value;
}

function parseEvidence(value: unknown): CallRecordEvidence {
  const item = record(value, "call_record_evidence_invalid");
  const segment_id = nonEmptyString(item.segment_id, "call_record_evidence_segment_invalid");
  const quote = nonEmptyString(item.quote, "call_record_evidence_quote_invalid");
  const start_ms = nonNegativeInteger(item.start_ms, "call_record_evidence_time_invalid");
  const end_ms = nonNegativeInteger(item.end_ms, "call_record_evidence_time_invalid");
  if (end_ms < start_ms) {
    fail("call_record_evidence_range_invalid");
  }
  return { segment_id, quote, start_ms, end_ms };
}

function parseSpeaker(value: unknown): CallRecordSpeaker {
  const item = record(value, "call_record_speaker_invalid");
  const speaker_id = nonEmptyString(item.speaker_id, "call_record_speaker_id_invalid");
  const talk_ms = nonNegativeInteger(item.talk_ms, "call_record_speaker_talk_ms_invalid");
  const talk_share = talkShare(item.talk_share);
  const questions = nonNegativeInteger(item.questions, "call_record_speaker_questions_invalid");
  const longest_monologue_ms = nonNegativeInteger(
    item.longest_monologue_ms,
    "call_record_speaker_monologue_invalid",
  );
  return { speaker_id, talk_ms, talk_share, questions, longest_monologue_ms };
}

function parseNumbers(value: unknown): CallRecordNumbers {
  const item = record(value, "call_record_numbers_invalid");
  const duration_ms = nonNegativeInteger(item.duration_ms, "call_record_duration_invalid");
  if (!Array.isArray(item.speakers)) {
    fail("call_record_speakers_invalid");
  }
  const speakers = item.speakers.map(parseSpeaker);
  const overlaps = nonNegativeInteger(item.overlaps, "call_record_overlaps_invalid");
  return { duration_ms, speakers, overlaps };
}

function parseFact(value: unknown): CallRecordFact | null {
  const item = record(value, "call_record_fact_invalid");
  const statement = nonEmptyString(item.statement, "call_record_fact_statement_invalid");
  if (!Array.isArray(item.evidence) || item.evidence.length === 0) {
    // Check 2: Facts without a quote never render
    return null;
  }
  const evidence = item.evidence
    .map(parseEvidence)
    .filter((e) => e.quote.trim().length > 0);
  if (evidence.length === 0) {
    return null;
  }
  const tag =
    item.tag === undefined || item.tag === null
      ? null
      : typeof item.tag === "string"
        ? item.tag
        : fail("call_record_fact_tag_invalid");
  return { statement, evidence, tag };
}

export function parseCallRecord(value: unknown): CallRecord {
  const raw = record(value, "call_record_invalid");
  if (raw.version !== "call-record/1") {
    fail("call_record_version_invalid");
  }
  const numbers = parseNumbers(raw.numbers);
  if (!Array.isArray(raw.facts)) {
    fail("call_record_facts_invalid");
  }
  const facts: CallRecordFact[] = [];
  for (const rawFact of raw.facts) {
    const fact = parseFact(rawFact);
    if (fact) facts.push(fact);
  }

  let tags: string[] | Record<string, unknown> | null = null;
  if (raw.tags !== null && raw.tags !== undefined) {
    if (Array.isArray(raw.tags)) {
      tags = raw.tags.map((t) => nonEmptyString(t, "call_record_tag_invalid"));
    } else if (typeof raw.tags === "object") {
      tags = raw.tags as Record<string, unknown>;
    } else {
      fail("call_record_tags_invalid");
    }
  }

  let call_type: string | null = null;
  if (raw.call_type !== null && raw.call_type !== undefined) {
    call_type = nonEmptyString(raw.call_type, "call_record_call_type_invalid");
  }

  return {
    version: "call-record/1",
    numbers,
    facts,
    tags,
    call_type,
  };
}
