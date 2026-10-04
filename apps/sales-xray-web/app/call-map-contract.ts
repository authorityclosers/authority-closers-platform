import { computeCallMetrics } from "./call-metrics";
import type { TranscriptSegment } from "./report-contract";

// Strict parser for the AI half of the Overview, `call-map/1` (AUT-341 plan
// §3.2). The back end (B1) raises the same failure codes. Nothing here judges
// with a number: the fields are readings backed by quotes.

export const CALL_MAP_FAILURE_CODES = [
  "call_map_invalid",
  "call_map_evidence_unresolved",
  "call_map_time_out_of_range",
  "call_map_phase_order_invalid",
  "call_map_reference_unknown",
  "call_map_qualification_invalid",
  "call_map_word_cap_exceeded",
  "call_map_signal_kind_unknown",
  "call_map_money_invalid",
] as const;

export type CallMapFailureCode = (typeof CALL_MAP_FAILURE_CODES)[number];

export class CallMapContractError extends Error {
  constructor(readonly code: CallMapFailureCode) {
    super(code);
    this.name = "CallMapContractError";
  }
}

// signal-kinds:v1 start
export const SIGNAL_KINDS_V1 = {
  forward: [
    "pain_confirmed",
    "budget_confirmed",
    "decision_maker_engaged",
    "timeline_stated",
    "next_step_agreed",
    "buying_question",
  ],
  risk: [
    "price_concern",
    "affordability_gap",
    "time_constraint",
    "stall",
    "competitor_or_status_quo",
    "decision_maker_absent",
    "trust_concern",
    "unanswered_question",
  ],
} as const;
// signal-kinds:v1 end

export const QUALIFICATION_ITEMS = [
  "budget",
  "timeline",
  "decision_maker",
  "authority",
  "need",
] as const;

const ROLES = ["seller", "prospect", "other"] as const;
const PHASES = ["opening", "discovery", "pitch", "objection", "close"] as const;
const OUTCOMES = ["won", "lost", "follow_up", "disqualified", "none"] as const;
const RUNGS = ["none", "vague", "dated_call", "invite_sent", "committed"];
const PERIODS = ["once", "day", "week", "month", "year"] as const;
const PROMISE_MS = { min: 60000, max: 14400000 } as const;
// Verdicts are readings, never judgements by number (AGENTS.md, AC-SVAL).
const SCORE_WORDS =
  /\b(scor\w*|grad(e|es|ed|ing)|rat(ing|ings|ed)|percent\w*)\b|\d\s*%|\bout\s+of\s+(\d+|five|ten|hundred)\b|\b(?:\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|hundred)\s*(?:points?|stars?|marks?)\b|\d\s+\/\s*\d|\d\s*\/\s+\d|\bgot\s+\d+\/\d+/i;
const DATE = /^(?:0?[1-9]|[12]\d|3[01])\/(?:0?[1-9]|1[0-2])(?:\/\d{2,4})?$/;

function hasScoreProse(text: string): boolean {
  return (
    SCORE_WORDS.test(text) ||
    (text.match(/\d+\/\d+(?:\/\d+)?/g) ?? []).some(
      (fraction) => !DATE.test(fraction),
    )
  );
}

type Polarity = keyof typeof SIGNAL_KINDS_V1;
type Qualification = (typeof QUALIFICATION_ITEMS)[number];
export type EvidenceRef = { segment_id: string; quote: string };
type Evidenced = { evidence: EvidenceRef[] };
type WithText = { text: string } & Evidenced;

export type CallMap = {
  version: "call-map/1";
  verdict_line: string;
  speakers: { speaker_id: string; role: (typeof ROLES)[number] }[];
  phases: { name: (typeof PHASES)[number]; start_ms: number }[];
  time_promise: ({ promised_ms: number } & Evidenced) | null;
  outcome: {
    kind: (typeof OUTCOMES)[number];
    next_step_rung:
      | "none"
      | "vague"
      | "dated_call"
      | "invite_sent"
      | "committed";
  } & Evidenced;
  signals: ({
    [P in Polarity]: { polarity: P; kind: (typeof SIGNAL_KINDS_V1)[P][number] };
  }[Polarity] &
    WithText)[];
  pitch_items: ({ id: string; start_ms: number; end_ms: number } & WithText)[];
  pains: ({
    id: string;
    raised_by: string;
    times: number;
    prospect_intensity: "low" | "med" | "high";
    addressed_by: string | null;
  } & WithText)[];
  money: ({
    label: string;
    value_min: number;
    value_max: number;
    unit: string;
    period: (typeof PERIODS)[number] | null;
  } & Evidenced)[];
  claims: ({
    id: string;
    verifiable: "yes" | "no" | "unclear";
    seller_error: "factual" | "term" | null;
  } & WithText)[];
  qualification_gaps: Qualification[];
  qualification_confirmed: ({ item: Qualification } & Evidenced)[];
  prospect_tasks: ({ effort_ms: number | null } & WithText)[];
};

type Check = (value: unknown) => void;

function check(ok: boolean, code: CallMapFailureCode = "call_map_invalid") {
  if (!ok) throw new CallMapContractError(code);
}

// Shape checks: any miss is `call_map_invalid`.
const str: Check = (v) =>
  check(typeof v === "string" && v.trim() !== "" && v.length <= 400);
const count: Check = (v) =>
  check(Number.isSafeInteger(v) && (v as number) >= 0);
const amount: Check = (v) => check(typeof v === "number" && Number.isFinite(v));
const id =
  (prefix: string): Check =>
  (v) =>
    check(typeof v === "string" && new RegExp(`^${prefix}[1-9]\\d*$`).test(v));
const oneOf =
  (values: readonly unknown[]): Check =>
  (v) =>
    check(values.includes(v));
const orNull =
  (inner: Check): Check =>
  (v) => {
    if (v !== null) inner(v);
  };
const list =
  (min: number, max: number, item: Check): Check =>
  (v) => {
    check(Array.isArray(v) && v.length >= min && v.length <= max);
    (v as unknown[]).forEach(item);
  };
const shape =
  (fields: Record<string, Check>): Check =>
  (v) => {
    check(!!v && typeof v === "object" && !Array.isArray(v));
    const keys = Object.keys(v as object);
    check(
      keys.length === Object.keys(fields).length &&
        keys.every((key) => Object.hasOwn(fields, key)),
    );
    for (const [key, inner] of Object.entries(fields))
      inner((v as Record<string, unknown>)[key]);
  };
const ev = (min: number, max: number) =>
  list(min, max, shape({ segment_id: str, quote: str }));

const CALL_MAP_SHAPE = shape({
  version: oneOf(["call-map/1"]),
  verdict_line: str,
  speakers: list(1, 16, shape({ speaker_id: str, role: oneOf(ROLES) })),
  phases: list(1, 8, shape({ name: oneOf(PHASES), start_ms: count })),
  time_promise: orNull(shape({ promised_ms: count, evidence: ev(1, 1) })),
  outcome: shape({
    kind: oneOf(OUTCOMES),
    next_step_rung: oneOf(RUNGS),
    evidence: ev(0, 2),
  }),
  signals: list(
    0,
    8,
    shape({
      polarity: oneOf(Object.keys(SIGNAL_KINDS_V1)),
      kind: str,
      text: str,
      evidence: ev(1, 2),
    }),
  ),
  pitch_items: list(
    0,
    8,
    shape({
      id: id("pi"),
      text: str,
      start_ms: count,
      end_ms: count,
      evidence: ev(1, 2),
    }),
  ),
  pains: list(
    0,
    6,
    shape({
      id: id("pn"),
      text: str,
      raised_by: str,
      times: (v) => check(Number.isSafeInteger(v) && (v as number) >= 1),
      prospect_intensity: oneOf(["low", "med", "high"]),
      addressed_by: orNull(str),
      evidence: ev(1, 3),
    }),
  ),
  money: list(
    0,
    8,
    shape({
      label: str,
      value_min: amount,
      value_max: amount,
      unit: str,
      period: orNull(oneOf(PERIODS)),
      evidence: ev(1, 1),
    }),
  ),
  claims: list(
    0,
    8,
    shape({
      id: id("cl"),
      text: str,
      verifiable: oneOf(["yes", "no", "unclear"]),
      seller_error: orNull(oneOf(["factual", "term"])),
      evidence: ev(1, 2),
    }),
  ),
  qualification_gaps: list(0, 5, oneOf(QUALIFICATION_ITEMS)),
  qualification_confirmed: list(
    0,
    5,
    shape({
      item: oneOf(QUALIFICATION_ITEMS),
      evidence: ev(1, 2),
    }),
  ),
  prospect_tasks: list(
    0,
    4,
    shape({
      text: str,
      effort_ms: orNull(count),
      evidence: ev(1, 1),
    }),
  ),
});

const words = (value: string) => value.trim().split(/\s+/).length;
const squash = (value: string) => value.trim().replace(/\s+/g, " ");
const unique = (values: string[]) => new Set(values).size === values.length;

/** Parses a stored `call_map`; `null` means "not available yet". The segments
 * and duration are the same report's transcript; a missing duration falls
 * back to the time used from `call-metrics.ts`, so both agree. */
export function parseCallMap(
  value: unknown,
  segments: readonly TranscriptSegment[],
  durationMs: number | null,
): CallMap | null {
  if (value === null) return null;
  CALL_MAP_SHAPE(value);
  const map = structuredClone(value) as CallMap;
  for (const items of [map.pitch_items, map.pains, map.claims])
    check(unique(items.map((item) => item.id)));

  const refs = [
    ...(map.time_promise?.evidence ?? []),
    ...map.outcome.evidence,
    ...[
      map.signals,
      map.pitch_items,
      map.pains,
      map.money,
      map.claims,
      map.qualification_confirmed,
      map.prospect_tasks,
    ].flatMap((items: Evidenced[]) => items.flatMap((item) => item.evidence)),
  ];
  const byId = new Map(segments.map((segment) => [segment.id, segment]));
  for (const ref of refs) {
    const segment = byId.get(ref.segment_id);
    check(
      !!segment && squash(segment.text).includes(squash(ref.quote)),
      "call_map_evidence_unresolved",
    );
  }
  const { kind, next_step_rung, evidence } = map.outcome;
  check(
    evidence.length > 0 || (kind === "none" && next_step_rung === "none"),
    "call_map_evidence_unresolved",
  );

  const end = computeCallMetrics([...segments], durationMs).time_used_ms;
  const inside = (ms: number) => ms >= 0 && ms <= end;
  const promise = map.time_promise?.promised_ms ?? PROMISE_MS.min;
  check(
    map.phases.every((phase) => inside(phase.start_ms)) &&
      map.pitch_items.every((p) => p.start_ms < p.end_ms && inside(p.end_ms)) &&
      promise >= PROMISE_MS.min &&
      promise <= PROMISE_MS.max,
    "call_map_time_out_of_range",
  );
  check(
    map.phases.every(
      (phase, i) =>
        i === 0 ||
        (phase.start_ms > map.phases[i - 1].start_ms &&
          phase.name !== map.phases[i - 1].name),
    ),
    "call_map_phase_order_invalid",
  );

  const speakers = new Set(segments.flatMap((s) => s.speaker_id ?? []));
  const named = map.speakers.map((speaker) => speaker.speaker_id);
  const pitchIds = new Set(map.pitch_items.map((item) => item.id));
  check(
    named.length === speakers.size &&
      unique(named) &&
      named.every((speaker) => speakers.has(speaker)) &&
      map.pains.every(
        (pain) =>
          speakers.has(pain.raised_by) &&
          (pain.addressed_by === null || pitchIds.has(pain.addressed_by)),
      ),
    "call_map_reference_unknown",
  );

  const items = [
    ...map.qualification_gaps,
    ...map.qualification_confirmed.map((entry) => entry.item),
  ];
  check(
    items.length === QUALIFICATION_ITEMS.length &&
      QUALIFICATION_ITEMS.every((item) => items.includes(item)),
    "call_map_qualification_invalid",
  );

  const texts = [map.pitch_items, map.pains, map.claims, map.prospect_tasks];
  const capped: [string, number][] = [
    [map.verdict_line, 12],
    ...refs.map((ref): [string, number] => [ref.quote, 20]),
    ...map.signals.map((signal): [string, number] => [signal.text, 8]),
    ...texts.flatMap((list: WithText[]) =>
      list.map((item): [string, number] => [item.text, 12]),
    ),
    ...map.money.map((money): [string, number] => [money.label, 6]),
  ];
  check(
    capped.every(([text, cap]) => words(text) <= cap),
    "call_map_word_cap_exceeded",
  );
  check(!hasScoreProse(map.verdict_line));

  check(
    map.money.every(
      (m) =>
        m.value_min >= 0 && m.value_min <= m.value_max && m.unit.length <= 12,
    ),
    "call_map_money_invalid",
  );
  check(
    map.signals.every((signal) =>
      (SIGNAL_KINDS_V1[signal.polarity] as readonly string[]).includes(
        signal.kind,
      ),
    ),
    "call_map_signal_kind_unknown",
  );
  return map;
}
