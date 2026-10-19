/**
 * Review 2.0 for one call (GET /v1/admin/conversation/review/calls/{id}): the
 * active pipelines and every reviewer's current answers. Reviewers judge the
 * analysis (objects, facts, segments), never report lines. Pure.
 */
import { read } from "../lib/read";

export type ReviewQuestion = {
  key: string;
  kind: "verdict" | "pick" | "correct" | "scale";
  label: string;
  options: string[];
  /** Asked only when another answer has this value, e.g. { correct: "wrong" }. */
  when: Record<string, string>;
};

export type ReviewPipelineView = {
  key: string;
  version: number;
  kind: string;
  title: string;
  targets: string[];
  questions: ReviewQuestion[];
};

export type ReviewAnswer = { value?: string | number; text?: string };

export type ReviewVerdictView = {
  id: string;
  targetKind: string;
  targetRef: string;
  question: string;
  answer: ReviewAnswer | null;
  mine: boolean;
  reviewerId: string;
};

export type ReviewCall = {
  pipelines: ReviewPipelineView[];
  verdicts: ReviewVerdictView[];
};

const KINDS = ["verdict", "pick", "correct", "scale"] as const;

function answer(raw: unknown): ReviewAnswer | null {
  if (raw === null || raw === undefined) return null;
  const body = read.object(raw);
  const value = body.value;
  return {
    ...(typeof value === "string" || typeof value === "number"
      ? { value }
      : {}),
    ...(typeof body.text === "string" ? { text: body.text } : {}),
  };
}

export function normalizeVerdict(raw: unknown): ReviewVerdictView {
  const row = read.object(raw);
  const target = read.object(row.target);
  return {
    id: read.string(row.id),
    targetKind: read.string(target.kind),
    targetRef: read.string(target.ref),
    question: read.string(row.question),
    answer: answer(row.answer),
    mine: row.mine === true,
    reviewerId: read.string(row.reviewer_id),
  };
}

export function normalizeReviewCall(raw: unknown): ReviewCall {
  const body = read.object(raw);
  return {
    pipelines: read.array(body.pipelines).map((item) => {
      const pipeline = read.object(item);
      const definition = read.object(pipeline.definition);
      return {
        key: read.string(pipeline.key),
        version: read.number(pipeline.version, 1),
        kind: read.string(pipeline.kind, "analysis"),
        title: read.string(pipeline.title, read.string(pipeline.key)),
        targets: read.strings(definition.targets),
        questions: read.array(definition.questions).map((entry) => {
          const question = read.object(entry);
          const kind = read.string(question.kind);
          const when = read.object(question.when);
          return {
            key: read.string(question.key),
            kind: (KINDS as readonly string[]).includes(kind)
              ? (kind as ReviewQuestion["kind"])
              : "verdict",
            label: read.string(question.label, read.string(question.key)),
            options: read.strings(question.options),
            when: Object.fromEntries(
              Object.entries(when).filter(
                (entry): entry is [string, string] =>
                  typeof entry[1] === "string",
              ),
            ),
          };
        }),
      };
    }),
    verdicts: read.array(body.verdicts).map(normalizeVerdict),
  };
}

/** This reviewer's current answers about one target, by question. */
export function myAnswers(
  verdicts: readonly ReviewVerdictView[],
  targetRef: string,
): Record<string, ReviewAnswer> {
  const found: Record<string, ReviewAnswer> = {};
  for (const verdict of verdicts)
    if (verdict.mine && verdict.targetRef === targetRef && verdict.answer)
      found[verdict.question] = verdict.answer;
  return found;
}

/** How many other reviewers answered about this target. */
export function othersOn(
  verdicts: readonly ReviewVerdictView[],
  targetRef: string,
): number {
  return new Set(
    verdicts
      .filter((verdict) => !verdict.mine && verdict.targetRef === targetRef)
      .map((verdict) => verdict.reviewerId),
  ).size;
}

/** Replace this reviewer's answer to one question with a newly saved one. */
export function withSaved(
  verdicts: readonly ReviewVerdictView[],
  saved: ReviewVerdictView,
): ReviewVerdictView[] {
  return [
    ...verdicts.filter(
      (verdict) =>
        !(
          verdict.mine &&
          verdict.targetRef === saved.targetRef &&
          verdict.question === saved.question
        ),
    ),
    saved,
  ];
}
