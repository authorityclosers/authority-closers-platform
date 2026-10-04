"use client";

/*
 * Per-call insights for the Calls workspace (AUT-999 v2, owner 5 Oct 2026).
 * Reads the existing GET-only endpoints (`/call-record`, `/report`) for calls
 * that have a report, three at a time, cached for this mounted workspace. Extraction is
 * tolerant: a missing or changed field hides that insight, never the row.
 */
import { useEffect, useMemo, useState } from "react";

import {
  ACQUISITION,
  AcquisitionError,
  acquisition,
  submissionPath,
} from "./acquisition-client";
import { parseCallRecord, type CallRecord } from "./call-record-contract";

export type CallMoment = { label: string; startMs: number };

export type CallInsight = {
  durationMs: number | null;
  speakers: { share: number; questions: number }[];
  questions: number | null;
  callType: string | null;
  signals: {
    commitments: number | null;
    business: number | null;
    concerns: number | null;
  };
  assessment: string | null;
  fixFirst: string | null;
  nextFocus: string | null;
  strengths: number | null;
  missed: number | null;
  moments: CallMoment[];
};

export type InsightReadState = "loading" | "ready" | "unavailable" | "error";
type InsightRead = { status: InsightReadState; insight: CallInsight | null };

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

export function extractInsight(
  callRecord: unknown,
  report: unknown,
): CallInsight {
  let record: CallRecord | null = null;
  try {
    record = parseCallRecord(callRecord);
  } catch {
    /* Unavailable measurements stay unknown. */
  }
  const speakers =
    record?.numbers.speakers.map((speaker) => ({
      share: speaker.talk_share,
      questions: speaker.questions,
    })) ?? [];
  const count = (tag: string) =>
    record ? record.facts.filter((fact) => fact.tag === tag).length : null;
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
      record && record.numbers.duration_ms > 0
        ? record.numbers.duration_ms
        : null,
    speakers,
    questions: speakers.length
      ? speakers.reduce((sum, speaker) => sum + speaker.questions, 0)
      : null,
    callType: record?.call_type ?? null,
    signals: {
      commitments: count("Next steps and commitments"),
      business: count("Business details"),
      concerns: count("Concerns"),
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
    strengths: Array.isArray(content.strengths) ? strengthsList.length : null,
    missed: Array.isArray(content.missed_opportunities)
      ? content.missed_opportunities.length
      : null,
    moments,
  };
}

async function readJson(path: string, signal: AbortSignal) {
  try {
    return await acquisition(path, { signal });
  } catch (error) {
    if (error instanceof AcquisitionError && error.status === 404) return null;
    throw error;
  }
}

async function loadInsight(id: string, signal: AbortSignal) {
  const base = submissionPath(id);
  const reads = await Promise.allSettled([
    readJson(`${base}/call-record`, signal),
    readJson(`${base}/report`, signal),
  ]);
  const [callRecord, report] = reads.map((read) =>
    read.status === "fulfilled" ? read.value : null,
  );
  const insight =
    callRecord || report ? extractInsight(callRecord, report) : null;
  return {
    insight,
    status: reads.some((read) => read.status === "rejected")
      ? "error"
      : insight
        ? "ready"
        : "unavailable",
  } as InsightRead;
}

/** Insights for the given report-ready call ids; loads lazily, three at a time. */
export function useCallInsights(ids: string[], enabled: boolean) {
  const [, setVersion] = useState(0);
  const [attempt, setAttempt] = useState(0);
  // CallsLibrary remounts on person/session/workspace changes. Never share reads globally.
  const cache = useMemo(() => new Map<string, InsightRead>(), [enabled]);
  const key = ids.join(",");
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const queue = key
      .split(",")
      .filter(
        (id) => id && (!cache.has(id) || cache.get(id)?.status === "error"),
      );
    let active = 0;
    const next = () => {
      while (active < 3 && queue.length) {
        const id = queue.shift() as string;
        active += 1;
        void loadInsight(id, controller.signal)
          .then((read) => {
            if (controller.signal.aborted) return;
            cache.set(id, read);
            setVersion((value) => value + 1);
          })
          .catch(() => {
            if (controller.signal.aborted) return;
            cache.set(id, { status: "error", insight: null });
            setVersion((value) => value + 1);
          })
          .finally(() => {
            active -= 1;
            if (!controller.signal.aborted) next();
          });
      }
    };
    next();
    return () => controller.abort();
  }, [key, enabled, cache, attempt]);
  return {
    insightOf: (id: string) => cache.get(id)?.insight ?? null,
    statusOf: (id: string): InsightReadState =>
      cache.get(id)?.status ?? "loading",
    retry: () => {
      for (const [id, read] of cache)
        if (read.status === "error") cache.delete(id);
      setAttempt((value) => value + 1);
    },
  };
}

export function audioSource(id: string) {
  return `${ACQUISITION}${submissionPath(id)}/source`;
}
