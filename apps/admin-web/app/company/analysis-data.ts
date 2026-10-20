/**
 * The company view's analysis read (GET /v1/admin/conversation/insights/
 * analysis): what buyers said, from the call data engine's current objects,
 * and each skill's AI pointer score, weakest first. Internal reads of AI
 * output, never an official score. Pure.
 */
import { read } from "../lib/read";

export type Said = { text: string; calls: number };

export type SkillScore = {
  label: string;
  calls: number;
  average: number;
  needsWorkShare: number;
};

/** One week (Monday, India time): calls made, read by the engine, scored, mean score. */
export type WeekRow = {
  week: string;
  calls: number;
  analysed: number;
  scored: number;
  average: number | null;
};

export type SkillWeeks = {
  label: string;
  weeks: { week: string; average: number | null; calls: number }[];
};

export type PersonTrend = {
  personId: string;
  name: string;
  calls: number;
  analysed: number;
  scored: number;
  average: number | null;
  needsWorkShare: number | null;
  weakest: { label: string; average: number; calls: number } | null;
  /** Calls per week, in the order of `weeks`. */
  weeks: number[];
};

export type FunnelStage = {
  key: string;
  label: string;
  reached: number;
  share: number | null;
  fromPrevious: number | null;
};

export type StageFunnel = {
  /** 0: the organisation never saved its own stages (Lead Desk's defaults). */
  version: number;
  leads: number;
  funnel: FunnelStage[];
  lost: number;
  unreachable: number;
};

export type AnalysisInsights = {
  days: number;
  /** Calls made in the window, read or not. */
  calls: number;
  callsAnalysed: number;
  callsScored: number;
  said: { objections: Said[]; questions: Said[]; pains: Said[]; goals: Said[] };
  commitments: Record<string, number>;
  readings: Record<string, Said[]>;
  skills: SkillScore[];
  weeks: WeekRow[];
  skillWeeks: SkillWeeks[];
  people: PersonTrend[];
  stages: StageFunnel;
};

const said = (raw: unknown): Said[] =>
  read.array(raw).map((item) => {
    const row = read.object(item);
    return { text: read.string(row.text), calls: read.number(row.calls) };
  });

const n = read.optionalNumber;

export function normalizeAnalysis(raw: unknown): AnalysisInsights {
  const body = read.object(raw);
  const window = read.object(body.window);
  const saidBody = read.object(body.said);
  const readings = read.object(body.readings);
  const stages = read.object(body.stages);
  return {
    days: read.number(window.days, 30),
    calls: read.number(body.calls),
    callsAnalysed: read.number(body.calls_analysed),
    callsScored: read.number(body.calls_scored),
    said: {
      objections: said(saidBody.objections),
      questions: said(saidBody.questions),
      pains: said(saidBody.pains),
      goals: said(saidBody.goals),
    },
    commitments: Object.fromEntries(
      Object.entries(read.object(body.commitments)).map(([key, value]) => [
        key,
        read.number(value),
      ]),
    ),
    readings: Object.fromEntries(
      Object.entries(readings).map(([key, value]) => [key, said(value)]),
    ),
    skills: read.array(body.skills).map((item) => {
      const row = read.object(item);
      return {
        label: read.string(row.label),
        calls: read.number(row.calls),
        average: read.number(row.average),
        needsWorkShare: read.number(row.needs_work_share),
      };
    }),
    weeks: read.array(body.weeks).map((item) => {
      const row = read.object(item);
      return {
        week: read.string(row.week),
        calls: read.number(row.calls),
        analysed: read.number(row.analysed),
        scored: read.number(row.scored),
        average: n(row.average),
      };
    }),
    skillWeeks: read.array(body.skill_weeks).map((item) => {
      const row = read.object(item);
      return {
        label: read.string(row.label),
        weeks: read.array(row.weeks).map((entry) => {
          const week = read.object(entry);
          return {
            week: read.string(week.week),
            average: n(week.average),
            calls: read.number(week.calls),
          };
        }),
      };
    }),
    people: read.array(body.people).map((item) => {
      const row = read.object(item);
      const weakest = read.object(row.weakest);
      return {
        personId: read.string(row.person_id),
        name: read.string(row.name, "Unknown"),
        calls: read.number(row.calls),
        analysed: read.number(row.analysed),
        scored: read.number(row.scored),
        average: n(row.average),
        needsWorkShare: n(row.needs_work_share),
        weakest:
          typeof weakest.label === "string"
            ? {
                label: weakest.label,
                average: read.number(weakest.average),
                calls: read.number(weakest.calls),
              }
            : null,
        weeks: read.array(row.weeks).map((value) => read.number(value)),
      };
    }),
    stages: {
      version: read.number(stages.version),
      leads: read.number(stages.leads),
      funnel: read.array(stages.funnel).map((item) => {
        const row = read.object(item);
        return {
          key: read.string(row.key),
          label: read.string(row.label, read.string(row.key)),
          reached: read.number(row.reached),
          share: n(row.share),
          fromPrevious: n(row.from_previous),
        };
      }),
      lost: read.number(stages.lost),
      unreachable: read.number(stages.unreachable),
    },
  };
}

/** "30d" → 30; "12m" and "all" → a year (the analysis reads at most 365 days); else 90. */
export function rangeDays(range: string): number {
  if (range === "12m" || range === "all") return 365;
  const match = /^(\d{1,3})d$/.exec(range);
  return match ? Math.max(1, Math.min(365, Number(match[1]))) : 90;
}

/**
 * How often the AI pointer review did not mark a skill good, over every
 * skill and scored call (weighted by calls); null when nothing was scored.
 */
export function needsWorkShare(skills: readonly SkillScore[]): number | null {
  const calls = skills.reduce((sum, skill) => sum + skill.calls, 0);
  if (!calls) return null;
  return (
    skills.reduce((sum, skill) => sum + skill.needsWorkShare * skill.calls, 0) /
    calls
  );
}
