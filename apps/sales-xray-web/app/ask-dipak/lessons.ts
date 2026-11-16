/**
 * Ask Dipak's lessons, one at a time from the API (owner, 16 Nov 2026: Dipak's
 * lessons served from the database, so his edits reach the app without a
 * release; the page no longer downloads all 150, about 1.5 MB).
 *
 * GET /v1/sales-xray/ask-dipak/lessons/{id}
 *     {version, question, lesson}: the newest import of his docs (migration
 *     0157), never the report and coaching consistency lock.
 *
 * A lesson opened once is kept on the phone (localStorage, the last
 * KEEP lessons), so it opens at once next time and without a connection; it
 * is checked against the server once per visit and replaced if Dipak edited
 * it. Nothing here is the seller's: their saved lessons and missions are in
 * progress.ts.
 */
import { useEffect, useSyncExternalStore } from "react";

import type { Lesson, Option } from "./library";

export const LESSON_PATH = "/v1/sales-xray/ask-dipak/lessons";
const STORE = "sales-xray:ask-dipak:lesson:";
const ORDER = "sales-xray:ask-dipak:lessons";
/** Lessons kept on the phone: about 10 KB each. */
export const KEEP = 40;

export type LessonState = Readonly<{
  status: "loading" | "ready" | "failed";
  lesson: Lesson | null;
  /** The question in Dipak's doc wording, as served. */
  title: string | null;
}>;

type Kept = Readonly<{ version: string; title: string | null; lesson: Lesson }>;

const LOADING: LessonState = { status: "loading", lesson: null, title: null };
const FAILED: LessonState = { status: "failed", lesson: null, title: null };

const states = new Map<string, LessonState>();
/** Asked of the server this visit (or primed): not asked again until reload. */
const checked = new Set<string>();
const asking = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();

function set(id: string, next: LessonState) {
  states.set(id, next);
  listeners.forEach((listener) => listener());
}

const text = (value: unknown): string =>
  typeof value === "string" ? value : "";

/** The API's lesson (catalogue.lesson on the server) in the app's shape. */
export function fromServed(raw: unknown): Kept | null {
  if (typeof raw !== "object" || raw === null) return null;
  const body = raw as Record<string, unknown>;
  const lesson = body.lesson as Record<string, unknown> | null;
  if (typeof lesson !== "object" || lesson === null) return null;
  const options = Array.isArray(lesson.options) ? lesson.options : [];
  const deep = Array.isArray(lesson.deep_lesson) ? lesson.deep_lesson : [];
  const related = Array.isArray(lesson.related) ? lesson.related : [];
  const shift = (lesson.mindset_shift ?? {}) as Record<string, unknown>;
  if (!text(lesson.quick_answer) || options.length !== 3) return null;
  return {
    version: text(body.version),
    title: text(lesson.title) || null,
    lesson: {
      quick: text(lesson.quick_answer),
      scenario: text(lesson.scenario),
      options: options.map((option: Record<string, unknown>) => [
        text(option.choice),
        text(option.why),
        text(option.takeaway),
        text(option.takeaway_label) || "Better सोच",
      ]) as unknown as readonly Option[],
      deep: deep.map(text),
      cue: text(lesson.remember),
      mission: text(lesson.next_call_mission),
      next: related
        .map((item: Record<string, unknown>) => text(item?.id))
        .filter(Boolean),
      ...(text(shift.before) ? { before: text(shift.before) } : {}),
      ...(text(shift.after) ? { after: text(shift.after) } : {}),
      ...(text(shift.heading) ? { shift: text(shift.heading) } : {}),
    },
  };
}

function readKept(id: string): Kept | null {
  try {
    const raw = window.localStorage.getItem(STORE + id);
    if (!raw) return null;
    const kept = JSON.parse(raw) as Kept;
    return kept && kept.lesson && Array.isArray(kept.lesson.options)
      ? kept
      : null;
  } catch {
    return null;
  }
}

function keep(id: string, kept: Kept) {
  try {
    const order = (
      JSON.parse(window.localStorage.getItem(ORDER) ?? "[]") as string[]
    ).filter((item) => item !== id);
    order.push(id);
    while (order.length > KEEP) {
      const old = order.shift();
      if (old) window.localStorage.removeItem(STORE + old);
    }
    window.localStorage.setItem(STORE + id, JSON.stringify(kept));
    window.localStorage.setItem(ORDER, JSON.stringify(order));
  } catch {
    // Storage full or blocked: the lesson still shows this visit.
  }
}

const ready = (kept: Kept): LessonState => ({
  status: "ready",
  lesson: kept.lesson,
  title: kept.title,
});

/** Where a lesson stands: first from the phone's copy, if there is one. */
function current(id: string): LessonState {
  let state = states.get(id);
  if (!state) {
    const kept = typeof window === "undefined" ? null : readKept(id);
    state = kept ? ready(kept) : LOADING;
    states.set(id, state);
  }
  return state;
}

/** Ask the server once per visit; a kept copy stays if it can't be reached. */
export function loadLesson(id: string): Promise<void> {
  const running = asking.get(id);
  if (running) return running;
  current(id);
  if (checked.has(id)) return Promise.resolve();
  const request = (async () => {
    try {
      const response = await fetch(`${LESSON_PATH}/${encodeURIComponent(id)}`, {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: { accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Lesson answered ${response.status}`);
      const kept = fromServed(await response.json());
      if (!kept) throw new Error("Lesson answer was not understood");
      checked.add(id);
      keep(id, kept);
      set(id, ready(kept));
    } catch {
      if (states.get(id)?.status !== "ready") set(id, FAILED);
    } finally {
      asking.delete(id);
    }
  })();
  asking.set(id, request);
  return request;
}

/** Try again after a failure (the retry button). */
export function retryLesson(id: string): Promise<void> {
  checked.delete(id);
  set(id, LOADING);
  return loadLesson(id);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The lesson for a question: loading, ready (from the phone or the server) or failed. */
export function useLesson(id: string): LessonState {
  const state = useSyncExternalStore(
    subscribe,
    () => current(id),
    () => LOADING,
  );
  useEffect(() => {
    void loadLesson(id);
  }, [id]);
  return state;
}

/**
 * Lessons already known, as if just served (tests and the review fixture):
 * shown at once and not asked of the server this visit.
 */
export function primeLessons(
  lessons: Readonly<Record<string, Lesson>>,
  titles: Readonly<Record<string, string>> = {},
) {
  for (const [id, lesson] of Object.entries(lessons)) {
    states.set(id, { status: "ready", lesson, title: titles[id] ?? null });
    checked.add(id);
  }
  listeners.forEach((listener) => listener());
}

/** Forget every lesson this visit (tests). */
export function resetLessons() {
  states.clear();
  checked.clear();
  asking.clear();
}
