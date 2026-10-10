import type { ReportEvidence, Transcript } from "./report-contract";

export const CALL_OUTCOMES = [
  "Won",
  "Lost",
  "Follow-up Set",
  "Decision Pending",
  "Deferred",
  "Meeting Booked",
  "Disqualified",
  "No Clear Next Step",
  "Still Open",
] as const;
export const CALL_SKILL_STATES = [
  "Strongly Demonstrated",
  "Observed",
  "Needs Attention",
  "Not Enough Evidence",
  "Not Applicable",
] as const;

type Note = { text: string; evidence: ReportEvidence[] };
export type ReportStory = {
  version: "report-story/1";
  phases: {
    name: "opening" | "discovery" | "pitch" | "objection" | "close";
    start_ms: number;
  }[];
  outcome: {
    kind: "won" | "lost" | "follow_up" | "disqualified" | "none";
    next_step_rung:
      | "none"
      | "vague"
      | "dated_call"
      | "invite_sent"
      | "committed";
    next_step_when: string | null;
    evidence: ReportEvidence[];
  };
  next_step: Note | null;
  prospect_commitments: (Note & { effort_ms: number | null })[];
  prospect_tasks?: (Note & { effort_ms: number | null })[];
  seller_commitments: (Note & { due_text: string | null })[];
};

function check(value: unknown): asserts value {
  if (!value) throw new Error("report_story_invalid");
}
function object(value: unknown, keys: string[]): Record<string, unknown> {
  check(value && typeof value === "object" && !Array.isArray(value));
  const result = value as Record<string, unknown>;
  check(
    Object.keys(result).length === keys.length &&
      keys.every((k) => Object.hasOwn(result, k)),
  );
  return result;
}
function list(value: unknown, max: number): unknown[] {
  check(Array.isArray(value) && value.length <= max);
  return value;
}
function text(value: unknown): string {
  check(typeof value === "string" && value.trim() && value.length <= 400);
  return value;
}
function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}
function number(value: unknown): number {
  check(Number.isSafeInteger(value) && (value as number) >= 0);
  return value as number;
}
function member<T extends string>(value: unknown, allowed: readonly T[]): T {
  check(typeof value === "string" && allowed.includes(value as T));
  return value as T;
}

/** Every new C5 reference must resolve in this report's already bound transcript. */
export function parseReportStory(
  value: unknown,
  transcript: Transcript,
): ReportStory {
  const keys = [
    "version",
    "phases",
    "outcome",
    "next_step",
    "prospect_commitments",
    "seller_commitments",
  ];
  if (
    value &&
    typeof value === "object" &&
    Object.hasOwn(value, "prospect_tasks")
  )
    keys.push("prospect_tasks");
  const item = object(value, keys);
  check(item.version === "report-story/1");
  const byId = new Map(transcript.segments.map((s) => [s.id, s]));
  const squash = (s: string) => s.trim().replace(/\s+/g, " ");
  const evidence = (value: unknown, max: number, min = 1): ReportEvidence[] => {
    const refs = list(value, max);
    check(refs.length >= min);
    return refs.map((ref) => {
      const r = object(ref, ["segment_id", "quote"]);
      const segment = byId.get(text(r.segment_id));
      const quote = text(r.quote);
      check(segment && squash(segment.text).includes(squash(quote)));
      return {
        segment_id: segment.id,
        quote,
        start_ms: segment.start_ms,
        end_ms: segment.end_ms,
      };
    });
  };
  const phases = list(item.phases, 8).map((value) => {
    const phase = object(value, ["name", "start_ms"]);
    const start = number(phase.start_ms);
    check(start < transcript.duration_ms);
    return {
      name: member(phase.name, [
        "opening",
        "discovery",
        "pitch",
        "objection",
        "close",
      ]),
      start_ms: start,
    };
  });
  check(
    phases.length &&
      phases.every(
        (p, i) =>
          !i ||
          (p.start_ms > phases[i - 1].start_ms &&
            p.name !== phases[i - 1].name),
      ),
  );
  const outcome = object(item.outcome, [
    "kind",
    "next_step_rung",
    "next_step_when",
    "evidence",
  ]);
  const parsedOutcome: ReportStory["outcome"] = {
    kind: member(outcome.kind, [
      "won",
      "lost",
      "follow_up",
      "disqualified",
      "none",
    ]),
    next_step_rung: member(outcome.next_step_rung, [
      "none",
      "vague",
      "dated_call",
      "invite_sent",
      "committed",
    ]),
    next_step_when: nullableText(outcome.next_step_when),
    evidence: evidence(outcome.evidence, 2, 0),
  };
  const available = (refs: ReportEvidence[]) =>
    refs.some((e) => e.quote !== "[Withheld for privacy]");
  if (parsedOutcome.evidence.length && !available(parsedOutcome.evidence)) {
    parsedOutcome.kind = "none";
    parsedOutcome.next_step_rung = "none";
    parsedOutcome.next_step_when = null;
  }
  if (
    parsedOutcome.kind !== "none" ||
    parsedOutcome.next_step_rung !== "none" ||
    parsedOutcome.next_step_when !== null
  )
    check(parsedOutcome.evidence.length);
  if (parsedOutcome.next_step_when !== null)
    check(
      parsedOutcome.evidence.some((e) =>
        squash(e.quote).includes(squash(parsedOutcome.next_step_when!)),
      ),
    );
  const next =
    item.next_step === null
      ? null
      : object(item.next_step, ["text", "evidence"]);
  const nextRefs = next ? evidence(next.evidence, 2) : [];
  const tasks = (input: unknown) =>
    list(input, 4)
      .map((value) => {
        const note = object(value, ["text", "effort_ms", "evidence"]);
        return {
          text: text(note.text),
          effort_ms: note.effort_ms === null ? null : number(note.effort_ms),
          evidence: evidence(note.evidence, 1),
        };
      })
      .filter((note) => available(note.evidence));
  return {
    version: "report-story/1",
    phases,
    outcome: parsedOutcome,
    next_step:
      next && available(nextRefs)
        ? {
            text: text(next.text),
            evidence: nextRefs,
          }
        : null,
    prospect_commitments: tasks(item.prospect_commitments),
    ...(item.prospect_tasks !== undefined
      ? { prospect_tasks: tasks(item.prospect_tasks) }
      : {}),
    seller_commitments: list(item.seller_commitments, 6)
      .map((value) => {
        const note = object(value, ["text", "due_text", "evidence"]);
        const refs = evidence(note.evidence, 1);
        const due = nullableText(note.due_text);
        if (due !== null && available(refs))
          check(refs.some((e) => squash(e.quote).includes(squash(due))));
        return { text: text(note.text), due_text: due, evidence: refs };
      })
      .filter((note) => available(note.evidence)),
  };
}
