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

export type AnalysisInsights = {
  days: number;
  callsAnalysed: number;
  callsScored: number;
  said: { objections: Said[]; questions: Said[]; pains: Said[]; goals: Said[] };
  commitments: Record<string, number>;
  readings: Record<string, Said[]>;
  skills: SkillScore[];
};

const said = (raw: unknown): Said[] =>
  read.array(raw).map((item) => {
    const row = read.object(item);
    return { text: read.string(row.text), calls: read.number(row.calls) };
  });

export function normalizeAnalysis(raw: unknown): AnalysisInsights {
  const body = read.object(raw);
  const window = read.object(body.window);
  const saidBody = read.object(body.said);
  const readings = read.object(body.readings);
  return {
    days: read.number(window.days, 30),
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
  };
}

/** "30d" → 30; anything else → the company view's default 90 days. */
export function rangeDays(range: string): number {
  const match = /^(\d{1,3})d$/.exec(range);
  return match ? Math.max(1, Math.min(365, Number(match[1]))) : 90;
}
