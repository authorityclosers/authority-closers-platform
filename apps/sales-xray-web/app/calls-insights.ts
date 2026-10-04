"use client";

/*
 * Per-call insights for the Calls workspace (AUT-999 v2, owner 5 Oct 2026).
 * Reads the existing GET-only endpoints (`/call-record`, `/report`) for calls
 * that have a report, three at a time, cached for the session. Extraction is
 * tolerant: a missing or changed field hides that insight, never the row.
 */
import { useEffect, useRef, useState } from "react";

import { ACQUISITION, acquisition, submissionPath } from "./acquisition-client";

export type CallMoment = { label: string; startMs: number };

export type CallInsight = {
  durationMs: number | null;
  speakers: { share: number; questions: number }[];
  questions: number | null;
  callType: string | null;
  signals: { promises: number; nextStep: number; money: number };
  assessment: string | null;
  fixFirst: string | null;
  nextFocus: string | null;
  strengths: number;
  missed: number;
  moments: CallMoment[];
};

const cache = new Map<string, CallInsight | null>();

function obj(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const item = value as Record<string, unknown>;
    for (const key of [
      "text",
      "title",
      "assessment",
      "outcome",
      "diagnosis",
      "behavior",
      "value",
      "statement",
    ]) {
      const found = text(item[key]);
      if (found) return found;
    }
  }
  return null;
}

function list(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") {
    const item = value as Record<string, unknown>;
    for (const key of ["items", "findings", "moments"]) {
      if (Array.isArray(item[key])) return item[key] as unknown[];
    }
  }
  return [];
}

function firstStart(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (typeof item.start_ms === "number" && item.start_ms >= 0)
    return item.start_ms;
  for (const key of ["evidence", "quotes"]) {
    for (const entry of list(item[key])) {
      const start = firstStart(entry);
      if (start !== null) return start;
    }
  }
  return null;
}

function tagCount(facts: unknown[], words: RegExp) {
  return facts.filter((fact) => {
    const item = obj(fact);
    const tag = typeof item.tag === "string" ? item.tag : "";
    const statement = typeof item.statement === "string" ? item.statement : "";
    return words.test(tag) || (!tag && words.test(statement));
  }).length;
}

export function extractInsight(
  callRecord: unknown,
  report: unknown,
): CallInsight {
  const recordValue =
    callRecord && typeof callRecord === "object"
      ? (callRecord as Record<string, unknown>)
      : {};
  const numbers =
    recordValue.numbers && typeof recordValue.numbers === "object"
      ? (recordValue.numbers as Record<string, unknown>)
      : {};
  const speakers = list(numbers.speakers).map((speaker) => {
    const item = obj(speaker);
    return {
      share: typeof item.talk_share === "number" ? item.talk_share : 0,
      questions: typeof item.questions === "number" ? item.questions : 0,
    };
  });
  const facts = list(recordValue.facts);
  // The report endpoint wraps the content: { report: { content: {...} } }.
  const outer = obj(report);
  const content = obj(obj(outer.report).content ?? outer.content ?? outer);
  const overview = obj(content.overview);
  const assessmentBlock = obj(overview.final_assessment);
  const strengthsList = list(content.strengths);
  const nextAction = obj(content.next_action);
  const moments: CallMoment[] = [];
  const addMoment = (label: string | null, start: number | null) => {
    if (label && start !== null && moments.length < 4)
      moments.push({ label, startMs: start });
  };
  // "Listen to these": rewatch moments, then golden moments, then the next action.
  for (const entry of list(overview.rewatch))
    addMoment(text(entry), firstStart(entry));
  for (const entry of list(overview.golden_moments)) {
    const item = obj(entry);
    const strength = obj(
      strengthsList[
        typeof item.strength_index === "number" ? item.strength_index : -1
      ],
    );
    const evidence = list(strength.evidence)[
      typeof item.evidence_index === "number" ? item.evidence_index : 0
    ];
    addMoment(
      text(item.why_effective) ?? text(strength.title),
      firstStart(evidence),
    );
  }
  addMoment(text(nextAction.title), firstStart(nextAction));
  return {
    durationMs:
      typeof numbers.duration_ms === "number" && numbers.duration_ms > 0
        ? numbers.duration_ms
        : null,
    speakers,
    questions: speakers.length
      ? speakers.reduce((sum, speaker) => sum + speaker.questions, 0)
      : null,
    callType:
      typeof recordValue.call_type === "string" ? recordValue.call_type : null,
    signals: {
      promises: tagCount(facts, /promis|commit/i),
      nextStep:
        tagCount(facts, /next[_ -]?step|follow/i) ||
        (text(nextAction.title) ? 1 : 0),
      money: tagCount(facts, /money|price|budget|income|profit|₹|rupee/i),
    },
    assessment:
      text(assessmentBlock.assessment) ??
      text(overview.outcome) ??
      text(content.verdict) ??
      null,
    fixFirst: text(assessmentBlock.fix_first),
    nextFocus:
      text(assessmentBlock.next_focus) ??
      text(obj(overview.next_call_focus).behavior) ??
      text(nextAction.title),
    strengths: strengthsList.length,
    missed: list(content.missed_opportunities).length,
    moments,
  };
}

async function readJson(path: string, signal: AbortSignal) {
  try {
    return await acquisition(path, { signal });
  } catch {
    return null;
  }
}

async function loadInsight(id: string, signal: AbortSignal) {
  const base = submissionPath(id);
  const [callRecord, report] = await Promise.all([
    readJson(`${base}/call-record`, signal),
    readJson(`${base}/report`, signal),
  ]);
  if (!callRecord && !report) return null;
  return extractInsight(callRecord, report);
}

/** Insights for the given report-ready call ids; loads lazily, three at a time. */
export function useCallInsights(ids: string[], enabled: boolean) {
  const [, setVersion] = useState(0);
  const inFlight = useRef(new Set<string>());
  const key = ids.join(",");
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const queue = key
      .split(",")
      .filter((id) => id && !cache.has(id) && !inFlight.current.has(id));
    let active = 0;
    const next = () => {
      while (active < 3 && queue.length) {
        const id = queue.shift() as string;
        active += 1;
        inFlight.current.add(id);
        void loadInsight(id, controller.signal)
          .then((insight) => {
            if (controller.signal.aborted) return;
            cache.set(id, insight);
            setVersion((value) => value + 1);
          })
          .finally(() => {
            inFlight.current.delete(id);
            active -= 1;
            if (!controller.signal.aborted) next();
          });
      }
    };
    next();
    return () => controller.abort();
  }, [key, enabled]);
  return (id: string) => cache.get(id) ?? null;
}

export function audioSource(id: string) {
  return `${ACQUISITION}${submissionPath(id)}/source`;
}
