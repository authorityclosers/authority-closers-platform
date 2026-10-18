import type { ReportEvidence, Transcript } from "./report-contract";
import {
  profileValueText,
  type ProfileField,
  type ProfileKey,
} from "./prospect-profile-contract";
import type { ProspectSummary } from "./prospects-client";

/**
 * Prospect's Information v2 (owner design, 19 Oct): one read model for the
 * section, whatever produced the facts. Sources today: the prospect saved on
 * the account (a person's edit wins and is locked), the per-call AI review
 * (structure.prospect_profile) and the Report's own outcome. A later
 * "call objects" pipeline plugs in as another source of the same shape.
 * Every fact carries its evidence; a fact no source gives stays null
 * (shown as Unknown), never guessed.
 */

/** Where a value came from: said on the call, the AI's read, or a person. */
export type FactBasis = "call" | "ai_read" | "person";

export type ProspectFact = {
  value: string | null;
  basis: FactBasis | null;
  evidence: ReportEvidence[];
  /** The saved-prospect field this fact maps to, when a person may confirm or edit it. */
  editKey?: ProfileKey;
  /** True once a person set it: shown as theirs, never overwritten by a call. */
  locked?: boolean;
};

export type InsightKind =
  | "business"
  | "goal"
  | "team"
  | "investment"
  | "alternative"
  | "timeline"
  | "question"
  | "promise"
  | "other";

export type ProspectFacts = {
  name: ProspectFact;
  role: ProspectFact;
  company: ProspectFact;
  revenue: ProspectFact;
  teamSize: ProspectFact;
  industry: ProspectFact;
  problem: ProspectFact;
  wants: ProspectFact;
  stopping: ProspectFact;
  personal: ProspectFact;
  followUp: {
    when: string | null;
    about: string | null;
    evidence: ReportEvidence[];
  };
  nextAction: ProspectFact;
  /** The deal's state in words ("Decision Pending"); a person's outcome wins. */
  deal: string | null;
  quality: { score: number | null; reason: string | null };
  fit: { value: "strong" | "possible" | "weak" | null; reason: string | null };
  urgency: { value: "high" | "medium" | "low" | null; reason: string | null };
  insights: { kind: InsightKind; text: string; evidence: ReportEvidence[] }[];
  /** False until the call's AI review exists (it lands a few minutes after the report). */
  reviewed: boolean;
};

/** A source fills any subset; earlier sources in the list win per fact. */
export type ProspectFactsSource = Partial<
  Omit<ProspectFacts, "insights" | "reviewed" | "followUp"> & {
    insights: ProspectFacts["insights"];
    followUp: ProspectFacts["followUp"];
    reviewed: boolean;
  }
>;

const EMPTY: ProspectFact = { value: null, basis: null, evidence: [] };

const FACT_KEYS = [
  "name",
  "role",
  "company",
  "revenue",
  "teamSize",
  "industry",
  "problem",
  "wants",
  "stopping",
  "personal",
  "nextAction",
] as const;
type FactKey = (typeof FACT_KEYS)[number];

/** Saved-prospect fields each fact maps to (confirm and edit save here). */
export const FACT_PROFILE_KEYS: Partial<Record<FactKey, ProfileKey>> = {
  name: "name",
  role: "role",
  company: "business",
  revenue: "turnover",
  teamSize: "team_size",
  industry: "industry",
  problem: "main_pain",
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, max = 400) =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, max) : null;

/** Resolve {segment_id, quote} against the bound transcript; unknown ids are dropped. */
function evidenceFrom(
  value: unknown,
  transcript: Transcript | undefined,
): ReportEvidence[] {
  if (!Array.isArray(value) || !transcript) return [];
  const byId = new Map(transcript.segments.map((s) => [s.id, s]));
  return value.flatMap((ref) => {
    if (!isRecord(ref)) return [];
    const segment = byId.get(String(ref.segment_id));
    const quote = text(ref.quote, 600);
    return segment && quote
      ? [
          {
            segment_id: segment.id,
            quote,
            start_ms: segment.start_ms,
            end_ms: segment.end_ms,
          },
        ]
      : [];
  });
}

const INSIGHT_KINDS: readonly InsightKind[] = [
  "business",
  "goal",
  "team",
  "investment",
  "alternative",
  "timeline",
  "question",
  "promise",
  "other",
];

/** Source: the per-call AI review (structure.prospect_profile, prospect-profile/1). */
export function factsFromCallReview(
  structure: unknown,
  transcript: Transcript | undefined,
): ProspectFactsSource {
  const raw = isRecord(structure) ? structure.prospect_profile : null;
  if (!isRecord(raw) || raw.version !== "prospect-profile/1") return {};
  const fact = (key: string): ProspectFact => {
    const entry = isRecord(raw[key]) ? raw[key] : {};
    const value = text(entry.value, 200);
    const evidence = evidenceFrom(entry.evidence, transcript);
    // A fact the call cannot show is not a fact.
    return value && evidence.length
      ? { value, basis: "call", evidence }
      : EMPTY;
  };
  const follow = isRecord(raw.follow_up) ? raw.follow_up : {};
  const followEvidence = evidenceFrom(follow.evidence, transcript);
  const quality = isRecord(raw.quality) ? raw.quality : {};
  const score =
    Number.isInteger(quality.score) &&
    (quality.score as number) >= 1 &&
    (quality.score as number) <= 10
      ? (quality.score as number)
      : null;
  const read = <T extends string>(key: string, values: readonly T[]) => {
    const entry = isRecord(raw[key]) ? raw[key] : {};
    const value = values.includes(entry.value as T) ? (entry.value as T) : null;
    return { value, reason: value ? text(entry.reason, 200) : null };
  };
  return {
    name: fact("name"),
    role: fact("role"),
    company: fact("company"),
    revenue: fact("revenue"),
    teamSize: fact("team_size"),
    industry: fact("industry"),
    problem: fact("biggest_problem"),
    wants: fact("wants"),
    stopping: fact("stopping"),
    personal: fact("personal_context"),
    followUp:
      text(follow.when, 60) && followEvidence.length
        ? {
            when: text(follow.when, 60),
            about: text(follow.about, 120),
            evidence: followEvidence,
          }
        : undefined,
    insights: (Array.isArray(raw.insights) ? raw.insights : [])
      .flatMap((item) => {
        if (
          !isRecord(item) ||
          !INSIGHT_KINDS.includes(item.kind as InsightKind)
        )
          return [];
        const words = text(item.text, 240);
        const evidence = evidenceFrom(item.evidence, transcript);
        return words && evidence.length
          ? [{ kind: item.kind as InsightKind, text: words, evidence }]
          : [];
      })
      .slice(0, 8),
    quality: { score, reason: score ? text(quality.reason, 200) : null },
    fit: read("fit", ["strong", "possible", "weak"] as const),
    urgency: read("urgency", ["high", "medium", "low"] as const),
    reviewed: true,
  };
}

/** Source: the prospect saved on the account. A person's value wins and is locked. */
export function factsFromSavedProspect(
  prospect: ProspectSummary | null | undefined,
  transcript: Transcript | undefined,
): ProspectFactsSource {
  const fields = prospect?.profile_fields ?? {};
  const saved = (key: ProfileKey): ProspectFact | undefined => {
    const field: ProfileField | undefined = fields[key];
    if (field?.state !== "known") return undefined;
    const value = profileValueText(field.value);
    if (!value) return undefined;
    const heard =
      field.evidence && transcript
        ? evidenceFrom([field.evidence], transcript)
        : [];
    return {
      value,
      basis: field.basis === "person" ? "person" : "call",
      evidence: heard,
      editKey: key,
      locked: field.locked,
    };
  };
  const source: ProspectFactsSource = {};
  for (const [fact, key] of Object.entries(FACT_PROFILE_KEYS) as [
    FactKey,
    ProfileKey,
  ][]) {
    const value = saved(key);
    if (value) source[fact] = value;
  }
  return source;
}

/** Source: what the Report itself already says (no AI call). */
export function factsFromReport(report: {
  deal: string | null;
  blocker?: { text: string; sources: ReportEvidence[] } | null;
  nextAction?: string | null;
  nextStep?: {
    text: string;
    when: string | null;
    source: ReportEvidence | null;
  } | null;
}): ProspectFactsSource {
  return {
    deal: report.deal,
    stopping: report.blocker
      ? {
          value: report.blocker.text,
          basis: "ai_read",
          evidence: report.blocker.sources.slice(0, 1),
        }
      : undefined,
    nextAction: report.nextAction
      ? { value: report.nextAction, basis: "ai_read", evidence: [] }
      : undefined,
    followUp: report.nextStep?.when
      ? {
          when: report.nextStep.when,
          about: report.nextStep.text,
          evidence: report.nextStep.source ? [report.nextStep.source] : [],
        }
      : undefined,
  };
}

/** Merge sources in priority order: the first source that has a fact wins. */
export function prospectFacts(
  ...sources: ProspectFactsSource[]
): ProspectFacts {
  const first = <K extends keyof ProspectFactsSource>(key: K) =>
    sources.map((source) => source[key]).find((value) => value != null);
  const facts = Object.fromEntries(
    FACT_KEYS.map((key) => {
      const found = sources
        .map((source) => source[key] as ProspectFact | undefined)
        .find((fact) => fact?.value);
      const editKey = FACT_PROFILE_KEYS[key];
      return [
        key,
        found
          ? { ...found, ...(editKey ? { editKey } : {}) }
          : { ...EMPTY, ...(editKey ? { editKey } : {}) },
      ];
    }),
  ) as Record<FactKey, ProspectFact>;
  return {
    ...facts,
    followUp: first("followUp") ?? { when: null, about: null, evidence: [] },
    deal: (first("deal") as string | null | undefined) ?? null,
    quality: first("quality") ?? { score: null, reason: null },
    fit: first("fit") ?? { value: null, reason: null },
    urgency: first("urgency") ?? { value: null, reason: null },
    insights: first("insights") ?? [],
    reviewed: sources.some((source) => source.reviewed),
  };
}
