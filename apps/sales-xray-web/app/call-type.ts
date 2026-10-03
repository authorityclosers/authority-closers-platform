// Call type derived by code from structured call-map inputs, never by a
// model (AUT-341 decision brief, decision 1). First match wins, in the order
// of CALL_TYPES. No score: the result is one closed key. The shared vectors in
// tests/fixtures/call-type-vectors.json pin every rule below; the Python twin
// is ac_platform/conversation_intelligence/call_type.py.

export const CALL_TYPES = [
  "not_sales",
  "objection_negotiation",
  "prospect_story",
  "screening",
  "first_meeting",
  "pitch_demo",
  "follow_up_closing",
  "full_sales",
] as const;

export type CallType = (typeof CALL_TYPES)[number] | "unclear";

// Proposed test settings from profiles/call_types_v1.json. The owner fixes
// them at Gate 2; they are not approved business semantics.
export const CALL_TYPE_THRESHOLDS = {
  prospect_share_over: 0.6,
  pitch_share_over: 0.5,
  short_call_ms: 600000,
  little_questions_ms: 120000,
} as const;

const PURPOSES = ["sales", "support", "onboarding", "internal", "personal"];
const NOT_SALES = ["support", "onboarding", "internal", "personal"];
const PHASES = ["opening", "discovery", "pitch", "objection", "close"];
const OUTCOMES = ["won", "lost", "follow_up", "disqualified", "none"];
const ADVANCE_OR_STOP = ["follow_up", "disqualified", "lost"];

type Span = { start_ms: number; end_ms: number };

export type CallTypeInput = {
  call_purpose: string | null;
  duration_ms: number | null;
  phases: { name: string; start_ms: number }[];
  objection_spans?: Span[];
  prospect_talk_share: number | null;
  qualification_confirmed: string[];
  outcome_kind: string | null;
  price_moments?: number | null;
};

const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

function unionMs(spans: Span[]): number {
  let total = 0;
  let reach = -Infinity;
  for (const span of [...spans].sort((a, b) => a.start_ms - b.start_ms)) {
    const start = Math.max(span.start_ms, reach);
    if (span.end_ms > start) total += span.end_ms - start;
    reach = Math.max(reach, span.end_ms);
  }
  return total;
}

// Stage time per phase name. A phase ends where the next one starts, the last
// at the call's end; repeated stages add up and never overlap.
function stageMs(
  input: CallTypeInput,
  duration: number,
): Record<string, number> | null {
  const { phases, objection_spans: extra = [] } = input;
  if (!Array.isArray(phases) || phases.length === 0 || !Array.isArray(extra))
    return null;
  if (!phases.every((p) => PHASES.includes(p?.name) && finite(p.start_ms)))
    return null;
  const clip = (ms: number) => Math.min(Math.max(ms, 0), duration);
  const sorted = [...phases].sort((a, b) => a.start_ms - b.start_ms);
  const spans: Record<string, Span[]> = {};
  for (const name of PHASES) spans[name] = [];
  for (const [i, phase] of sorted.entries()) {
    const next = sorted[i + 1]?.start_ms ?? duration;
    spans[phase.name].push({
      start_ms: clip(phase.start_ms),
      end_ms: clip(next),
    });
  }
  for (const span of extra) {
    if (!finite(span?.start_ms) || !finite(span.end_ms)) return null;
    if (span.end_ms < span.start_ms) return null;
    spans.objection.push({
      start_ms: clip(span.start_ms),
      end_ms: clip(span.end_ms),
    });
  }
  return Object.fromEntries(PHASES.map((name) => [name, unionMs(spans[name])]));
}

export function deriveCallType(input: CallTypeInput): CallType {
  const t = CALL_TYPE_THRESHOLDS;
  const purpose = input?.call_purpose;
  if (typeof purpose !== "string" || !PURPOSES.includes(purpose))
    return "unclear";
  if (NOT_SALES.includes(purpose)) return "not_sales";

  const duration = input.duration_ms;
  const share = input.prospect_talk_share;
  if (!finite(duration) || duration <= 0) return "unclear";
  if (!finite(share) || share < 0 || share > 1) return "unclear";
  if (!Array.isArray(input.qualification_confirmed)) return "unclear";
  if (!OUTCOMES.includes(input.outcome_kind as string)) return "unclear";
  const ms = stageMs(input, duration);
  if (!ms) return "unclear";

  const has = (name: string) => ms[name] > 0;
  const others = PHASES.filter((name) => name !== "objection");
  const littleQuestions = ms.discovery <= t.little_questions_ms;
  const moments = input.price_moments;
  const priceTalk = Number.isSafeInteger(moments) && (moments as number) > 0;

  if (has("objection") && others.every((name) => ms.objection > ms[name]))
    return "objection_negotiation";
  if (share > t.prospect_share_over) return "prospect_story";
  if (
    duration <= t.short_call_ms &&
    input.qualification_confirmed.length > 0 &&
    !has("pitch") &&
    ADVANCE_OR_STOP.includes(input.outcome_kind as string)
  )
    return "screening";
  if (has("discovery") && !has("pitch") && !has("close"))
    return "first_meeting";
  if (ms.pitch > duration * t.pitch_share_over && littleQuestions)
    return "pitch_demo";
  if (littleQuestions && (has("close") || priceTalk))
    return "follow_up_closing";
  if (has("discovery") && has("pitch") && has("close")) return "full_sales";
  return "unclear";
}
