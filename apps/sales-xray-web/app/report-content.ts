import type { ReportEvidence, Transcript } from "./report-contract";
import { CALL_OUTCOMES } from "./report-story";

export type ContentNote = {
  text: string;
  actor_id: string;
  evidence: ReportEvidence[];
};
type ContentFinding = {
  title: string;
  observation: ContentNote;
  effect: ContentNote | null;
};
export type ReportContent = {
  version: "report-content/1";
  roles: Record<string, "seller" | "prospect" | "other">;
  purpose:
    | (ContentNote & {
        kind: "setter" | "discovery" | "closing" | "client_review";
      })
    | null;
  outcome: (ContentNote & { status: (typeof CALL_OUTCOMES)[number] }) | null;
  summary_sentences: ContentNote[];
  influence: ContentNote | null;
  strongest: ContentNote | null;
  concern: ContentNote | null;
  next_step: ContentNote | null;
  phases: ContentNote[];
  turning_point: {
    before: ContentNote;
    turn: ContentNote;
    after: ContentNote;
  } | null;
  worked: ContentFinding[];
  didnt: ContentFinding[];
  moments: (ContentFinding & {
    kind:
      | "Strong Moment"
      | "Turning Point"
      | "Buying Signal"
      | "Objection"
      | "Price Moment"
      | "Decision Moment"
      | "Trust Moment"
      | "Commitment"
      | "Risk";
  })[];
  missed_chances: {
    title: string;
    opening: ContentNote;
    response_opportunity: ContentNote;
    relevance: ContentNote;
  }[];
  position: ContentNote | null;
  blocker: ContentNote | null;
  prospect_commitments: ContentNote[];
  seller_commitments: ContentNote[];
  next_event: {
    observation: ContentNote;
    date_text: string | null;
    time_text: string | null;
    agreement_evidence: ReportEvidence[];
  } | null;
  commitment_quality: "Clear" | "Soft" | "Unclear" | null;
  unknowns: ContentNote[];
  action: ContentNote | null;
};

export function parseReportContent(
  value: unknown,
  transcript: Transcript,
): ReportContent {
  function check(value: unknown): asserts value {
    if (!value) throw new Error("report_content_invalid");
  }
  function obj(value: unknown, keys?: string[]): Record<string, unknown> {
    check(value && typeof value === "object" && !Array.isArray(value));
    const row = value as Record<string, unknown>;
    if (keys)
      check(
        Object.keys(row).length === keys.length &&
          keys.every((k) => Object.hasOwn(row, k)),
      );
    return row;
  }
  function text(value: unknown, max = 1200): string {
    check(typeof value === "string" && value.trim() && value.length <= max);
    return value;
  }
  function list<T>(
    value: unknown,
    max: number,
    parse: (v: unknown) => T,
    min = 0,
  ): T[] {
    check(Array.isArray(value) && value.length >= min && value.length <= max);
    return value.map((child) => parse(child));
  }
  function member<T extends string>(value: unknown, values: readonly T[]): T {
    check(typeof value === "string" && values.includes(value as T));
    return value as T;
  }
  function nullable<T>(value: unknown, parse: (v: unknown) => T): T | null {
    return value === null ? null : parse(value);
  }
  const keys = [
    "version",
    "roles",
    "purpose",
    "outcome",
    "summary_sentences",
    "influence",
    "strongest",
    "concern",
    "next_step",
    "phases",
    "turning_point",
    "worked",
    "didnt",
    "moments",
    "missed_chances",
    "position",
    "blocker",
    "prospect_commitments",
    "seller_commitments",
    "next_event",
    "commitment_quality",
    "unknowns",
    "action",
  ];
  const root = obj(value, keys);
  check(root.version === "report-content/1");
  const byId = new Map(transcript.segments.map((s) => [s.id, s]));
  const known = new Set(transcript.segments.map((s) => s.speaker_id));
  const roles = Object.fromEntries(
    Object.entries(obj(root.roles)).map(([id, role]) => {
      check(known.has(id));
      return [id, member(role, ["seller", "prospect", "other"] as const)];
    }),
  );
  function evidence(
    value: unknown,
    max: number,
    min: number,
    actor?: string,
  ): ReportEvidence[] {
    const refs = list(
      value,
      max,
      (v) => {
        const ref = obj(v, ["segment_id", "quote", "start_ms", "end_ms"]);
        const s = byId.get(text(ref.segment_id, 128));
        check(
          s &&
            (!actor || s.speaker_id === actor) &&
            ref.quote === s.text &&
            ref.start_ms === s.start_ms &&
            ref.end_ms === s.end_ms,
        );
        check(s.text.length <= 2000);
        return {
          segment_id: s.id,
          quote: s.text,
          start_ms: s.start_ms,
          end_ms: s.end_ms,
        };
      },
      min,
    );
    check(
      new Set(refs.map((r) => r.segment_id)).size === refs.length &&
        refs.every(
          (r, i) =>
            !i ||
            refs[i - 1].start_ms < r.start_ms ||
            (refs[i - 1].start_ms === r.start_ms &&
              refs[i - 1].segment_id < r.segment_id),
        ),
    );
    return refs;
  }
  function note(value: unknown, extras: string[] = []): ContentNote {
    const n = obj(value, ["text", "actor_id", "evidence", ...extras]);
    const actor_id = text(n.actor_id, 256);
    check(Object.hasOwn(roles, actor_id));
    return {
      text: text(n.text),
      actor_id,
      evidence: evidence(n.evidence, 3, 1, actor_id),
    };
  }
  function finding(value: unknown, moment = false): ContentFinding {
    const f = obj(value, [
      "title",
      "observation",
      "effect",
      ...(moment ? ["kind"] : []),
    ]);
    return {
      title: text(f.title, 160),
      observation: note(f.observation),
      effect: nullable(f.effect, note),
    };
  }
  const content: ReportContent = {
    version: "report-content/1",
    roles,
    purpose: nullable(root.purpose, (v) => ({
      ...note(v, ["kind"]),
      kind: member(obj(v).kind, [
        "setter",
        "discovery",
        "closing",
        "client_review",
      ] as const),
    })),
    outcome: nullable(root.outcome, (v) => ({
      ...note(v, ["status"]),
      status: member(obj(v).status, CALL_OUTCOMES),
    })),
    summary_sentences: list(root.summary_sentences, 5, note, 3),
    influence: nullable(root.influence, note),
    strongest: nullable(root.strongest, note),
    concern: nullable(root.concern, note),
    next_step: nullable(root.next_step, note),
    phases: list(root.phases, 12, note),
    turning_point: nullable(root.turning_point, (v) => {
      const t = obj(v, ["before", "turn", "after"]);
      return {
        before: note(t.before),
        turn: note(t.turn),
        after: note(t.after),
      };
    }),
    worked: list(root.worked, 5, finding),
    didnt: list(root.didnt, 3, finding),
    moments: list(root.moments, 12, (v) => ({
      ...finding(v, true),
      kind: member(obj(v).kind, [
        "Strong Moment",
        "Turning Point",
        "Buying Signal",
        "Objection",
        "Price Moment",
        "Decision Moment",
        "Trust Moment",
        "Commitment",
        "Risk",
      ] as const),
    })),
    missed_chances: list(root.missed_chances, 10, (v) => {
      const m = obj(v, [
        "title",
        "opening",
        "response_opportunity",
        "relevance",
      ]);
      return {
        title: text(m.title, 160),
        opening: note(m.opening),
        response_opportunity: note(m.response_opportunity),
        relevance: note(m.relevance),
      };
    }),
    position: nullable(root.position, note),
    blocker: nullable(root.blocker, note),
    prospect_commitments: list(root.prospect_commitments, 8, note),
    seller_commitments: list(root.seller_commitments, 8, note),
    next_event: nullable(root.next_event, (v) => {
      const e = obj(v, [
        "observation",
        "date_text",
        "time_text",
        "agreement_evidence",
      ]);
      return {
        observation: note(e.observation),
        date_text: nullable(e.date_text, (v) => text(v, 120)),
        time_text: nullable(e.time_text, (v) => text(v, 120)),
        agreement_evidence: evidence(e.agreement_evidence, 4, 2),
      };
    }),
    commitment_quality: nullable(root.commitment_quality, (v) =>
      member(v, ["Clear", "Soft", "Unclear"] as const),
    ),
    unknowns: list(root.unknowns, 8, note),
    action: nullable(root.action, note),
  };
  for (const [notes, role] of [
    [content.prospect_commitments, "prospect"],
    [content.seller_commitments, "seller"],
  ] as const)
    check(notes.every((n) => roles[n.actor_id] === role));
  check(
    [...content.worked, ...content.didnt].every(
      (f) => roles[f.observation.actor_id] === "seller",
    ),
  );
  check(
    content.missed_chances.every(
      (m) =>
        roles[m.opening.actor_id] === "prospect" &&
        roles[m.response_opportunity.actor_id] === "seller" &&
        m.response_opportunity.evidence[0].start_ms >=
          m.opening.evidence.at(-1)!.end_ms,
    ),
  );
  for (const notes of [
    content.phases,
    content.moments.map((m) => m.observation),
    content.missed_chances.map((m) => m.opening),
  ])
    check(
      notes.every(
        (n, i) =>
          !i || notes[i - 1].evidence[0].start_ms < n.evidence[0].start_ms,
      ),
    );
  const t = content.turning_point;
  if (t)
    check(
      t.before.evidence.at(-1)!.end_ms <= t.turn.evidence[0].start_ms &&
        t.turn.evidence.at(-1)!.end_ms <= t.after.evidence[0].start_ms,
    );
  const e = content.next_event;
  if (e) {
    const participants = new Set(
      e.agreement_evidence.map(
        (r) => roles[byId.get(r.segment_id)!.speaker_id ?? ""],
      ),
    );
    const quotes = e.agreement_evidence
      .map((r) => r.quote)
      .join(" ")
      .toLocaleLowerCase();
    check(
      participants.has("seller") &&
        participants.has("prospect") &&
        [e.date_text, e.time_text].every(
          (v) => v === null || quotes.includes(v.toLocaleLowerCase()),
        ),
    );
  }
  if (content.commitment_quality === "Clear")
    check(e?.date_text && e.time_text);
  return content;
}
