import type { ReportEvidence, Transcript } from "../report-contract";
import type { Line } from "../report-story-model";
import {
  POINTERS,
  clock,
  spelled,
  type Pointer,
  type PointerQuote,
  type PointerStatus,
  type Scoring,
  type Stat,
  type XrayView,
} from "./model";

/**
 * Lenient reader for the API's `report.structure` (report-structure/1). A part
 * that does not check out is left out; it never removes the report. Scores are
 * shown only when the analysis saved one ("ai_draft"); the browser never makes
 * one up.
 */

type Json = Record<string, unknown>;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, max = 2000) =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, max) : null;
const num = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const STATUSES: readonly PointerStatus[] = [
  "excellent",
  "good",
  "average",
  "needs_improvement",
  "not_observed",
  "not_applicable",
  "insufficient_evidence",
];

function evidenceList(
  value: unknown,
  transcript?: Transcript,
): ReportEvidence[] {
  if (!Array.isArray(value)) return [];
  const segments = new Set(transcript?.segments.map((s) => s.id) ?? []);
  return value
    .filter(isObject)
    .map((item) => ({
      segment_id: String(item.segment_id ?? ""),
      quote: text(item.quote, 600) ?? "",
      start_ms: num(item.start_ms) ?? -1,
      end_ms: num(item.end_ms) ?? -1,
    }))
    .filter(
      (item) =>
        item.quote &&
        item.start_ms >= 0 &&
        item.end_ms >= item.start_ms &&
        (!transcript || segments.has(item.segment_id)),
    )
    .slice(0, 6);
}

function line(value: unknown, transcript?: Transcript): Line | null {
  if (!isObject(value)) return null;
  const words = text(value.text);
  return words
    ? { text: words, sources: evidenceList(value.evidence, transcript) }
    : null;
}

export type StructureRoles = Record<string, "rep" | "prospect">;

function roles(stats: Json | null): StructureRoles {
  const found: StructureRoles = {};
  const speakers = stats && Array.isArray(stats.speakers) ? stats.speakers : [];
  for (const speaker of speakers.filter(isObject)) {
    const id = text(speaker.speaker_id, 120);
    if (id && (speaker.role === "rep" || speaker.role === "prospect"))
      found[id] = speaker.role;
  }
  return found;
}

function statsFrom(value: unknown): XrayView["overview"]["stats"] | null {
  if (!isObject(value) || value.status !== "available") return null;
  // Owner 18 Oct: roles may be guessed from the call; say so (the speakers
  // card confirms or changes them).
  const guessed =
    Array.isArray(value.speakers) &&
    value.speakers.some(
      (row) =>
        isObject(row) &&
        (row.role_source === "predicted" || row.role_source === "model"),
    );
  const sides = guessed
    ? "Salesperson : Prospect (guessed)"
    : "Salesperson : Prospect";
  const duration = num(value.duration_ms);
  const share = isObject(value.talk_share_percent)
    ? value.talk_share_percent
    : {};
  const questions = isObject(value.questions_asked)
    ? value.questions_asked
    : {};
  const rep = num(share.rep);
  const prospect = num(share.prospect);
  const repQ = num(questions.rep);
  const prospectQ = num(questions.prospect);
  const longest = isObject(value.longest_rep_turn)
    ? num(value.longest_rep_turn.duration_ms)
    : null;
  const pair = (a: number, b: number, sub: string): Stat => ({
    value: `${a} : ${b}`,
    sub,
  });
  let talk: Stat | null = null;
  if (rep !== null && prospect !== null && rep + prospect > 0) {
    const yours = Math.round((rep / (rep + prospect)) * 100);
    talk = pair(yours, 100 - yours, sides);
  }
  return {
    duration:
      duration && duration > 0
        ? { value: clock(duration), sub: spelled(duration) }
        : null,
    talk,
    questions:
      repQ !== null && prospectQ !== null ? pair(repQ, prospectQ, sides) : null,
    longest:
      longest && longest > 0
        ? { value: clock(longest), sub: spelled(longest) }
        : null,
  };
}

function quotes(
  sources: ReportEvidence[],
  transcript: Transcript | undefined,
  who: (speakerId: string | null) => PointerQuote["who"],
): PointerQuote[] {
  const speaker = new Map(
    transcript?.segments.map((s) => [s.id, s.speaker_id]) ?? [],
  );
  return sources.slice(0, 4).map((source) => ({
    who: who(speaker.get(source.segment_id) ?? null),
    name: null,
    at_ms: source.start_ms,
    text: source.quote,
    source,
  }));
}

export type StructureView = {
  overview: Partial<
    Pick<XrayView["overview"], "summary" | "strength" | "improvement" | "score">
  > & {
    stats: XrayView["overview"]["stats"] | null;
  };
  pointers: Pointer[] | null;
  /** Where the deal stands, in the call's own words (AI review); never the outcome itself. */
  outcome: Partial<
    Pick<
      XrayView["outcome"],
      "stages" | "reasons" | "objections" | "nextSteps" | "notes" | "suggested"
    >
  > | null;
  /** True when any score came from the analysis (shown as an AI draft). */
  aiDraft: boolean;
  /** Why no score yet, when the server says (owner, 18 Oct). */
  scoring: Scoring;
  roles: StructureRoles;
};

export function readStructure(
  structure: unknown,
  transcript: Transcript | undefined,
  sellerId: string | null,
  prospectId: string | null,
): StructureView | null {
  if (!isObject(structure) || structure.version !== "report-structure/1")
    return null;
  const overview = isObject(structure.overview) ? structure.overview : {};
  const stats = isObject(overview.call_statistics)
    ? overview.call_statistics
    : null;
  const apiRoles = roles(stats);
  const who = (speakerId: string | null): PointerQuote["who"] => {
    if (!speakerId) return "other";
    if (speakerId === sellerId || apiRoles[speakerId] === "rep") return "you";
    if (speakerId === prospectId || apiRoles[speakerId] === "prospect")
      return "prospect";
    return "other";
  };
  let aiDraft = false;
  const overall = num(overview.score);
  const score =
    overall !== null && overall >= 0 && overall <= 100
      ? {
          value: Math.round(overall),
          label: text(overview.score_label, 40) ?? "",
          line: text(overview.score_line, 400) ?? "",
        }
      : null;
  if (score) aiDraft = true;

  const items = Array.isArray(structure.pointers)
    ? structure.pointers.filter(isObject)
    : [];
  const pointers: Pointer[] | null = items.length
    ? POINTERS.map((base, index) => {
        const item = items.find((p) => num(p.number) === index + 1) ?? {};
        const scored = num(item.score);
        const status = STATUSES.includes(item.status as PointerStatus)
          ? (item.status as PointerStatus)
          : null;
        // "No separate assessment is saved" is not a judgement about the call.
        const assessed = item.score_status !== "not_scored" || scored !== null;
        if (assessed && scored !== null) aiDraft = true;
        const evidence = evidenceList(item.evidence, transcript);
        const observations = Array.isArray(item.observations)
          ? item.observations
              .map((o) => line(o, transcript))
              .filter((o): o is Line => o !== null)
          : [];
        const related = Array.isArray(item.related_dimensions)
          ? item.related_dimensions
              .filter(isObject)
              .map((d) => {
                const words = text(d.observation);
                return words && !/^insufficient evidence/i.test(words)
                  ? {
                      text: `${text(d.label, 80) ?? "Related skill"}: ${words}`,
                      sources: evidenceList(d.evidence, transcript),
                    }
                  : null;
              })
              .filter((d): d is Line => d !== null)
          : [];
        const improve = Array.isArray(item.how_to_improve)
          ? item.how_to_improve
              .map((t) => text(t, 400))
              .filter((t): t is string => !!t)
          : text(item.how_to_improve, 1200)
            ? [text(item.how_to_improve, 1200) as string]
            : [];
        const video = isObject(item.training_video)
          ? item.training_video
          : null;
        const what =
          text(item.what_happened) ??
          (assessed ? null : (observations[0]?.text ?? null));
        return {
          ...base,
          number: index + 1,
          status: assessed ? status : null,
          score:
            assessed && scored !== null && scored >= 0 && scored <= 100
              ? Math.round(scored)
              : null,
          whatHappened: what,
          whyItMatters: text(item.why_it_matters),
          evidence: quotes(
            evidence.length ? evidence : (observations[0]?.sources ?? []),
            transcript,
            who,
          ),
          howToImprove: improve,
          training:
            video && text(video.title)
              ? {
                  title: text(video.title, 200) as string,
                  minutes: num(video.minutes),
                  href: text(video.url, 600),
                }
              : null,
          related: [...observations.slice(assessed ? 0 : 1), ...related].slice(
            0,
            3,
          ),
        };
      })
    : null;
  return {
    overview: {
      summary:
        line(
          { text: overview.summary, evidence: overview.evidence },
          transcript,
        ) ?? undefined,
      strength: line(overview.biggest_strength, transcript) ?? undefined,
      improvement: line(overview.biggest_improvement, transcript) ?? undefined,
      score: score ?? undefined,
      stats: statsFrom(stats),
    },
    pointers,
    outcome: outcomeDetails(structure.call_outcome_details),
    aiDraft,
    scoring: aiDraft ? null : scoringFrom(structure.pointer_review),
    roles: apiRoles,
  };
}

/** True while the server says this report's pointers are still being scored. */
export function scoringPending(structure: unknown): boolean {
  return (
    isObject(structure) &&
    isObject(structure.pointer_review) &&
    structure.pointer_review.status === "scoring"
  );
}

function scoringFrom(value: unknown): Scoring {
  if (!isObject(value)) return null;
  const status = value.status;
  if (
    status !== "scoring" &&
    status !== "before_scores" &&
    status !== "not_scored"
  )
    return null;
  return { status, reportCreatedAt: text(value.report_created_at, 64) };
}

const STAGES = [
  "Initial Contact",
  "Discovery",
  "Solution Presentation",
  "Negotiation",
  "Closing",
];

function outcomeDetails(value: unknown): StructureView["outcome"] {
  if (!isObject(value)) return null;
  const list = (items: unknown, count: number) =>
    Array.isArray(items)
      ? items
          .map((item) => text(item, 400))
          .filter((item): item is string => item !== null)
          .slice(0, count)
      : [];
  const stages = Array.isArray(value.stages)
    ? STAGES.filter((stage) => (value.stages as unknown[]).includes(stage))
    : [];
  const objections = Array.isArray(value.objections)
    ? value.objections
        .filter(isObject)
        .map((item) => ({
          text: text(item.text, 400) ?? "",
          sources: [],
          handled: item.handled === true,
        }))
        .filter((item) => item.text)
        .slice(0, 4)
    : [];
  const steps = Array.isArray(value.next_steps)
    ? value.next_steps
        .filter(isObject)
        .map((item) => ({
          text: text(item.text, 300) ?? "",
          date: text(item.when, 60),
          owner:
            item.owner === "you" || item.owner === "prospect"
              ? (item.owner as "you" | "prospect")
              : null,
          source: null,
        }))
        .filter((item) => item.text)
        .slice(0, 4)
    : [];
  const found: NonNullable<StructureView["outcome"]> = {};
  if (stages.length) found.stages = stages;
  const reasons = list(value.reasons, 4);
  if (reasons.length)
    found.reasons = reasons.map((t) => ({ text: t, sources: [] }));
  if (objections.length) found.objections = objections;
  if (steps.length) found.nextSteps = steps;
  const notes = list(value.notes, 3);
  if (notes.length) found.notes = notes.map((t) => ({ text: t, sources: [] }));
  const suggested = text(value.suggested_action, 400);
  if (suggested) found.suggested = suggested;
  return found;
}
