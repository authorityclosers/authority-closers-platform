import type { Finding, ReportEvidence } from "./report-contract";

type ObjectValue = Record<string, unknown>;
type SourceNote = { text: string; evidence: ReportEvidence[] };
type EvidenceParser = (value: unknown) => ReportEvidence;
type Findings = Pick<
  import("./report-contract").SalesReport,
  "strengths" | "improvements" | "missed_opportunities"
>;

function fail(): never {
  throw new Error("report_overview_invalid");
}
function object(
  value: unknown,
  keys: string[],
  optionalKeys: string[] = [],
): ObjectValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  const item = value as ObjectValue;
  const allowedKeys = new Set([...keys, ...optionalKeys]);
  if (
    Object.keys(item).some((key) => !allowedKeys.has(key)) ||
    keys.some((key) => !Object.hasOwn(item, key))
  )
    fail();
  return item;
}
function text(value: unknown, max: number): string {
  if (typeof value !== "string" || !value.trim() || value.length > max) fail();
  return value;
}
function integer(value: unknown, max: number): number {
  if (
    !Number.isInteger(value) ||
    (value as number) < 0 ||
    (value as number) > max
  )
    fail();
  return value as number;
}
function list<T>(
  value: unknown,
  max: number,
  parse: (item: unknown) => T,
  min = 0,
): T[] {
  if (!Array.isArray(value) || value.length < min || value.length > max) fail();
  return value.map((item) => parse(item));
}
function oneOf<const T extends string>(
  value: unknown,
  values: readonly T[],
): T {
  if (!values.includes(value as T)) fail();
  return value as T;
}
function nullable<T>(value: unknown, parse: (item: unknown) => T): T | null {
  return value === null ? null : parse(value);
}

/** v1 fields stay strict; business impact is the server-governed optional field. */
export function parseDetailedOverview(
  value: unknown,
  findings: Findings,
  parseEvidence: EvidenceParser,
) {
  const item = object(
    value,
    [
      "version",
      "diagnosis",
      "outcome",
      "strength_details",
      "improvement_details",
      "golden_moments",
      "missed_details",
      "prospect_interpretations",
      "rewatch",
      "conversation_change",
      "ethics_notes",
      "next_call_focus",
      "practice",
      "progress",
      "final_assessment",
    ],
    ["business_impact"],
  );
  function source(value: unknown, max = 1200): SourceNote {
    const note = object(value, ["text", "evidence"]);
    return {
      text: text(note.text, max),
      evidence: list(note.evidence, 3, parseEvidence, 1),
    };
  }
  function impact(value: unknown) {
    const data = object(value, ["status", "missing_inputs"]);
    return {
      status: oneOf(data.status, ["insufficient_data"]),
      missing_inputs: list(data.missing_inputs, 6, (v) => text(v, 240), 1),
    };
  }
  const parsed = {
    version: oneOf(item.version, ["dipak-14-point-v1"]),
    diagnosis: nullable(item.diagnosis, (v) => source(v, 320)),
    outcome: nullable(item.outcome, (v) => {
      const data = object(v, ["kind", "text", "evidence"]);
      return {
        kind: oneOf(data.kind, [
          "closed",
          "follow_up",
          "no_sale",
          "future_date",
          "disqualified",
          "unclear",
        ]),
        ...source({ text: data.text, evidence: data.evidence }),
      };
    }),
    ...(item.business_impact === undefined
      ? {}
      : { business_impact: nullable(item.business_impact, impact) }),
    strength_details: list(item.strength_details, 3, (v) => {
      const data = object(v, ["finding_index", "why_it_matters"]);
      return {
        finding_index: integer(data.finding_index, 2),
        why_it_matters: text(data.why_it_matters, 700),
      };
    }),
    improvement_details: list(item.improvement_details, 3, (v) => {
      const data = object(v, [
        "finding_index",
        "what_happened",
        "why_it_matters",
        "replacement_behavior",
        "business_impact",
      ]);
      return {
        finding_index: integer(data.finding_index, 2),
        what_happened: source(data.what_happened),
        why_it_matters: text(data.why_it_matters, 700),
        replacement_behavior: text(data.replacement_behavior, 1200),
        business_impact: impact(data.business_impact),
      };
    }),
    golden_moments: list(item.golden_moments, 3, (v) => {
      const data = object(v, [
        "strength_index",
        "evidence_index",
        "why_effective",
      ]);
      return {
        strength_index: integer(data.strength_index, 2),
        evidence_index: integer(data.evidence_index, 7),
        why_effective: text(data.why_effective, 700),
      };
    }),
    missed_details: list(item.missed_details, 10, (v) => {
      const data = object(v, [
        "finding_index",
        "prospect_signal",
        "closer_response",
        "follow_up",
        "potential_impact",
      ]);
      return {
        finding_index: integer(data.finding_index, 9),
        prospect_signal: source(data.prospect_signal),
        closer_response: source(data.closer_response),
        follow_up: text(data.follow_up, 1200),
        potential_impact: text(data.potential_impact, 700),
      };
    }),
    prospect_interpretations: list(item.prospect_interpretations, 3, (v) => {
      const data = object(v, [
        "source",
        "possible_concern",
        "interpretation_kind",
      ]);
      return {
        source: source(data.source),
        possible_concern: text(data.possible_concern, 700),
        interpretation_kind: oneOf(data.interpretation_kind, ["inference"]),
      };
    }),
    rewatch: list(item.rewatch, 3, (v) => {
      const data = object(v, ["text", "purpose", "evidence"]);
      return {
        text: text(data.text, 1200),
        purpose: oneOf(data.purpose, ["must_watch", "watch", "repeat"]),
        evidence: list(data.evidence, 1, parseEvidence, 1),
      };
    }),
    conversation_change: nullable(item.conversation_change, (v) => {
      const data = object(v, [
        "before",
        "change",
        "after",
        "possible_effect",
        "interpretation_kind",
      ]);
      return {
        before: source(data.before),
        change: source(data.change),
        after: source(data.after),
        possible_effect: text(data.possible_effect, 1200),
        interpretation_kind: oneOf(data.interpretation_kind, ["inference"]),
      };
    }),
    ethics_notes: list(item.ethics_notes, 3, source),
    next_call_focus: nullable(item.next_call_focus, (v) => {
      const data = object(v, ["improvement_index", "behavior", "target"]);
      return {
        improvement_index: integer(data.improvement_index, 0),
        behavior: text(data.behavior, 500),
        target: text(data.target, 500),
      };
    }),
    practice: nullable(item.practice, (v) => {
      const data = object(v, [
        "improvement_index",
        "instructions",
        "success_condition",
      ]);
      return {
        improvement_index: integer(data.improvement_index, 0),
        instructions: text(data.instructions, 1200),
        success_condition: text(data.success_condition, 500),
      };
    }),
    progress: item.progress === null ? null : fail(),
    final_assessment: (() => {
      const data = object(item.final_assessment, [
        "repeat",
        "fix_first",
        "next_focus",
        "assessment",
      ]);
      return {
        repeat: text(data.repeat, 500),
        fix_first: text(data.fix_first, 500),
        next_focus: text(data.next_focus, 500),
        assessment: text(data.assessment, 1200),
      };
    })(),
  };
  function references(
    details: { finding_index: number }[],
    collection: Finding[],
    complete: boolean,
  ) {
    const indices = details.map((d) => d.finding_index);
    if (
      new Set(indices).size !== indices.length ||
      indices.some((i) => i >= collection.length) ||
      (complete && indices.length !== collection.length)
    )
      fail();
  }
  references(parsed.strength_details, findings.strengths, true);
  references(parsed.improvement_details, findings.improvements, true);
  references(parsed.missed_details, findings.missed_opportunities, false);
  const goldenRefs = parsed.golden_moments.map(
    (g) => `${g.strength_index}:${g.evidence_index}`,
  );
  if (
    new Set(goldenRefs).size !== goldenRefs.length ||
    parsed.golden_moments.some(
      (g) => !findings.strengths[g.strength_index]?.evidence[g.evidence_index],
    )
  )
    fail();
  if (
    Boolean(parsed.next_call_focus) !== Boolean(parsed.practice) ||
    Boolean(findings.improvements.length) !== Boolean(parsed.next_call_focus)
  )
    fail();
  const clips = parsed.rewatch.map(
    (r) =>
      `${r.evidence[0].segment_id}:${r.evidence[0].start_ms}:${r.evidence[0].end_ms}`,
  );
  if (new Set(clips).size !== clips.length) fail();
  const change = parsed.conversation_change;
  if (
    change &&
    (Math.max(...change.before.evidence.map((e) => e.end_ms)) >
      Math.min(...change.change.evidence.map((e) => e.start_ms)) ||
      Math.max(...change.change.evidence.map((e) => e.end_ms)) >
        Math.min(...change.after.evidence.map((e) => e.start_ms)))
  )
    fail();
  return parsed;
}

export type DetailedOverview = ReturnType<typeof parseDetailedOverview>;
