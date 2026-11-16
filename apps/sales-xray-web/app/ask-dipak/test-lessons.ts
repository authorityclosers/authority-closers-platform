/**
 * Tests only: Dipak's 150 lessons as the server holds them (the bundled
 * library.json in packages/python/ac_platform/ask_dipak, lock included), and
 * a lesson as the API serves it (catalogue.lesson), for a fake server. The
 * app's own library.json holds no lesson since 16 Nov 2026.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { Lesson } from "./library";

export type StoredLesson = Lesson &
  Readonly<{ title: string; lock: readonly string[] }>;

const here = dirname(fileURLToPath(import.meta.url));
export const SERVER_LIBRARY = join(
  here,
  "../../../../packages/python/ac_platform/ask_dipak/library.json",
);
const server = JSON.parse(readFileSync(SERVER_LIBRARY, "utf8")) as {
  lessons: Record<string, StoredLesson>;
};

/** Every lesson, word for word, as the server keeps it. */
export const LESSONS: Readonly<Record<string, StoredLesson>> = server.lessons;

/** A lesson as a seller's phone receives it: no lock, no title field. */
export function sellerLesson(id: string): Lesson {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { lock, title, ...lesson } = LESSONS[id];
  return lesson;
}

export const SELLER_LESSONS: Readonly<Record<string, Lesson>> =
  Object.fromEntries(Object.keys(LESSONS).map((id) => [id, sellerLesson(id)]));

/** GET /v1/sales-xray/ask-dipak/lessons/{id}'s answer for a lesson. */
export function servedLesson(id: string, version = "test") {
  const lesson = LESSONS[id];
  return {
    version,
    question: { id },
    lesson: {
      id,
      title: lesson.title,
      mindset_shift: {
        heading: lesson.shift ?? null,
        before: lesson.before ?? null,
        after: lesson.after ?? null,
      },
      quick_answer: lesson.quick,
      scenario: lesson.scenario,
      options: lesson.options.map((option, index) => ({
        letter: "ABC"[index],
        choice: option[0],
        why: option[1],
        takeaway: option[2],
        takeaway_label: option[3] ?? "Better सोच",
      })),
      deep_lesson: lesson.deep,
      remember: lesson.cue,
      next_call_mission: lesson.mission,
      related: lesson.next.map((code) => ({ id: code })),
    },
  };
}
