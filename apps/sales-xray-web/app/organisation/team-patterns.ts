"use client";

/*
 * What keeps coming up across the team's calls (AUT-1679), for organisation
 * owners and admins. Everything here is a count of labels each report already
 * gave: how the call ended, each sales skill's evidence status and the
 * report's own "fix first" line. Nothing is scored, ranked by person or
 * inferred. Reports are read with the same GET the report screen uses.
 */
import { useEffect, useRef, useState } from "react";

import {
  AcquisitionError,
  acquisition,
  submissionPath,
  UUID,
} from "../acquisition-client";

/** The report Overview's own words for each outcome kind. */
export const OUTCOME_LABEL = {
  follow_up: "Next step agreed",
  closed: "Deal closed",
  future_date: "Call back later",
  unclear: "No clear next step",
  no_sale: "No sale",
  disqualified: "Not a fit",
} as const;
export type OutcomeKind = keyof typeof OUTCOME_LABEL;

export type ReportPattern = {
  outcome: OutcomeKind | null;
  skills: { id: string; label: string; status: string }[];
  fixFirst: string | null;
};

export type PatternCall = {
  id: string;
  ownerName: string | null;
  label: string | null;
  createdAt: string;
};

export type SkillTally = {
  id: string;
  label: string;
  /** Calls where the report says "Partly seen" or "Need more evidence". */
  gaps: number;
  /** Calls where the report assessed this skill (not "Not relevant here"). */
  assessed: number;
};

export type TeamPatterns = {
  reports: number;
  outcomes: { kind: OutcomeKind; label: string; calls: number }[];
  skills: SkillTally[];
  fixFirst: { call: PatternCall; text: string }[];
};

const obj = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const text = (value: unknown, max = 500): string | null =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, max) : null;

const GAP = new Set(["partial", "insufficient_evidence"]);
const NOT_ASSESSED = new Set(["not_applicable", "unknown"]);

/** The parts of one report this view counts; null when it has none. */
export function extractPattern(payload: unknown): ReportPattern | null {
  // GET /report: { report: { content: { overview, dimensions, ... } } }.
  const outer = obj(payload);
  const content = obj(obj(outer.report).content ?? outer.content);
  const overview = obj(content.overview);
  const kind = obj(overview.outcome).kind;
  const outcome =
    typeof kind === "string" && kind in OUTCOME_LABEL
      ? (kind as OutcomeKind)
      : null;
  const skills = (Array.isArray(content.dimensions) ? content.dimensions : [])
    .map((raw) => {
      const item = obj(raw);
      const id = text(item.dimension_id, 96);
      const label = text(item.label, 160);
      const status = text(item.status, 40);
      return id && label && status ? { id, label, status } : null;
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);
  const fixFirst = text(obj(overview.final_assessment).fix_first);
  if (!outcome && !skills.length && !fixFirst) return null;
  return { outcome, skills, fixFirst };
}

/** Counts across reports; `reads` are newest call first. */
export function tallyPatterns(
  reads: { call: PatternCall; pattern: ReportPattern }[],
): TeamPatterns {
  const outcomes = new Map<OutcomeKind, number>();
  const skills = new Map<string, SkillTally>();
  for (const { pattern } of reads) {
    if (pattern.outcome)
      outcomes.set(pattern.outcome, (outcomes.get(pattern.outcome) ?? 0) + 1);
    // One count per call, even if a report repeats a skill.
    const seen = new Set<string>();
    for (const skill of pattern.skills) {
      if (seen.has(skill.id) || NOT_ASSESSED.has(skill.status)) continue;
      seen.add(skill.id);
      const tally = skills.get(skill.id) ?? {
        id: skill.id,
        label: skill.label,
        gaps: 0,
        assessed: 0,
      };
      tally.assessed += 1;
      if (GAP.has(skill.status)) tally.gaps += 1;
      skills.set(skill.id, tally);
    }
  }
  const order = Object.keys(OUTCOME_LABEL) as OutcomeKind[];
  return {
    reports: reads.length,
    outcomes: [...outcomes]
      .map(([kind, calls]) => ({ kind, label: OUTCOME_LABEL[kind], calls }))
      .sort(
        (a, b) =>
          b.calls - a.calls || order.indexOf(a.kind) - order.indexOf(b.kind),
      ),
    skills: [...skills.values()].sort(
      (a, b) =>
        b.gaps - a.gaps ||
        b.gaps / b.assessed - a.gaps / a.assessed ||
        a.label.localeCompare(b.label),
    ),
    fixFirst: reads
      .filter(({ pattern }) => pattern.fixFirst)
      .map(({ call, pattern }) => ({ call, text: pattern.fixFirst as string })),
  };
}

export type PatternRead =
  | { status: "ready"; pattern: ReportPattern | null }
  | { status: "unavailable" }
  | { status: "denied" }
  | { status: "error" };

async function readPattern(id: string, signal: AbortSignal) {
  try {
    const payload = await acquisition(`${submissionPath(id)}/report`, {
      signal,
    });
    return { status: "ready", pattern: extractPattern(payload) } as const;
  } catch (error) {
    if (signal.aborted) throw error;
    if (error instanceof AcquisitionError) {
      if (error.status === 401 || error.status === 403)
        return { status: "denied" } as const;
      // Not ready, withheld or gone: not counted, never an error.
      if (error.status === 404 || error.status === 409 || error.status === 410)
        return { status: "unavailable" } as const;
    }
    return { status: "error" } as const;
  }
}

/** Reads each call's report, three at a time; `retry` re-reads failures. */
export function useTeamPatterns(ids: string[]) {
  const [reads, setReads] = useState(() => new Map<string, PatternRead>());
  const [attempt, setAttempt] = useState(0);
  const cache = useRef(new Map<string, PatternRead>());
  const key = ids.join(",");
  useEffect(() => {
    const controller = new AbortController();
    const queue = key
      .split(",")
      .filter((id) => UUID.test(id) && !cache.current.has(id));
    let active = 0;
    const next = () => {
      while (active < 3 && queue.length) {
        const id = queue.shift() as string;
        active += 1;
        void readPattern(id, controller.signal)
          .then((read) => {
            if (controller.signal.aborted) return;
            cache.current.set(id, read);
            setReads(new Map(cache.current));
          })
          .catch(() => {})
          .finally(() => {
            active -= 1;
            if (!controller.signal.aborted) next();
          });
      }
    };
    next();
    return () => controller.abort();
  }, [key, attempt]);
  return {
    reads,
    retry: () => {
      for (const [id, read] of cache.current)
        if (read.status === "error") cache.current.delete(id);
      setReads(new Map(cache.current));
      setAttempt((value) => value + 1);
    },
  };
}
