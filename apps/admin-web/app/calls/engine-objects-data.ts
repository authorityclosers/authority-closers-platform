/**
 * What the call data engine found in one call (GET /v1/admin/conversation/
 * calls/{id}/data-objects): facts, every segment's labels, the measured voice.
 * Normalizers give every field a default. Pure.
 */
import { read } from "../lib/read";

export type EngineFact = {
  objectId: string;
  type: string;
  category: string;
  label: string;
  display: string;
  confidence: number;
  basis: string;
  status: string;
  aiRead: boolean;
  pipeline: string;
  replacedFast: boolean;
};

export type EngineSegment = {
  segmentId: string;
  startMs: number;
  endMs: number;
  speaker: string;
  intent: string;
  act: string;
  sentiment: string | null;
  tone: string | null;
  topics: string[];
};

export type VoiceSpeaker = {
  label: string;
  share: number;
  paceWpm: number | null;
  pitchHz: number | null;
  loudnessDbfs: number | null;
  talkMs: number;
};

export type EngineObjects = {
  facts: EngineFact[];
  categories: Record<string, string>;
  segments: EngineSegment[];
  voice: {
    durationMs: number;
    peaks: number[];
    speakers: VoiceSpeaker[];
    pauses: { count: number; long: number; longestMs: number };
    overlapMs: number;
    source: string;
  } | null;
};

export function normalizeEngineObjects(raw: unknown): EngineObjects {
  const body = read.object(raw);
  const voice = body.voice === null ? null : read.object(body.voice);
  const categories = read.object(body.categories);
  return {
    categories: Object.fromEntries(
      Object.entries(categories).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    ),
    facts: read.array(body.facts).map((item) => {
      const fact = read.object(item);
      const source = read.object(fact.source);
      return {
        objectId: read.string(fact.object_id),
        type: read.string(fact.type),
        category: read.string(fact.category),
        label: read.string(fact.label, read.string(fact.type)),
        display: read.string(fact.display),
        confidence: read.number(fact.confidence),
        basis: read.string(fact.basis),
        status: read.string(fact.status),
        aiRead: read.boolean(fact.ai_read),
        pipeline: read.string(source.pipeline, "fast"),
        replacedFast: read.boolean(fact.superseded_a_fast_fact),
      };
    }),
    segments: read.array(body.segments).map((item) => {
      const segment = read.object(item);
      return {
        segmentId: read.string(segment.segment_id),
        startMs: read.number(segment.start_ms),
        endMs: read.number(segment.end_ms),
        speaker: read.string(segment.speaker, "unknown"),
        intent: read.string(segment.intent, "other"),
        act: read.string(segment.act, "statement"),
        sentiment: read.optionalString(segment.sentiment),
        tone: read.optionalString(segment.tone),
        topics: read.strings(segment.topics),
      };
    }),
    voice:
      voice === null || !Object.keys(voice).length
        ? null
        : {
            durationMs: read.number(voice.duration_ms),
            peaks: read.array(voice.peaks).map((value) => read.number(value)),
            speakers: Object.entries(read.object(voice.speakers)).map(
              ([label, value]) => {
                const speaker = read.object(value);
                return {
                  label,
                  share: read.number(speaker.share),
                  paceWpm: read.optionalNumber(speaker.pace_wpm),
                  pitchHz: read.optionalNumber(speaker.pitch_hz),
                  loudnessDbfs: read.optionalNumber(speaker.loudness_dbfs),
                  talkMs: read.number(speaker.talk_ms),
                };
              },
            ),
            pauses: {
              count: read.number(read.object(voice.pauses).count),
              long: read.number(read.object(voice.pauses).long),
              longestMs: read.number(read.object(voice.pauses).longest_ms),
            },
            overlapMs: read.number(voice.overlap_ms),
            source: read.string(voice.source),
          },
  };
}

/** Five plain groups of intent, so the timeline reads at a glance. */
export const INTENT_GROUPS = [
  {
    key: "opening",
    label: "Opening and rapport",
    intents: ["greeting", "rapport", "small_talk"],
  },
  {
    key: "discovery",
    label: "Discovery",
    intents: ["discovery", "pain", "goal", "qualification"],
  },
  { key: "offer", label: "Pitch and price", intents: ["pitch", "pricing"] },
  {
    key: "friction",
    label: "Objections and decision",
    intents: ["objection", "objection_handling", "decision_process"],
  },
  {
    key: "close",
    label: "Next steps and close",
    intents: ["next_steps", "closing", "logistics"],
  },
] as const;

export type IntentGroup = (typeof INTENT_GROUPS)[number]["key"] | "other";

export function intentGroup(intent: string): IntentGroup {
  return (
    INTENT_GROUPS.find((group) =>
      (group.intents as readonly string[]).includes(intent),
    )?.key ?? "other"
  );
}

/** How many segments each group has, per speaker role. */
export function intentMix(
  segments: EngineSegment[],
): Record<IntentGroup, number> {
  const counts: Record<IntentGroup, number> = {
    opening: 0,
    discovery: 0,
    offer: 0,
    friction: 0,
    close: 0,
    other: 0,
  };
  for (const segment of segments) counts[intentGroup(segment.intent)] += 1;
  return counts;
}

export const ROLE_LABEL: Record<string, string> = {
  salesperson: "Salesperson",
  prospect: "Prospect",
  other: "Someone else",
  unknown: "Speaker",
};
