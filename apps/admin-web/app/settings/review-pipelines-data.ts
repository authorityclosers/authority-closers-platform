/**
 * Review 2.0 pipelines as settings (GET /v1/admin/conversation/review/
 * pipelines): each pipeline's active version, whether this person may edit,
 * and the editor's limits. An edit saves a new version (POST .../pipelines/
 * {key}); the same checks run here first so a bad draft never leaves the page.
 * Pure.
 */
import type { ReviewQuestion } from "../calls/review-verdicts-data";
import { read } from "../lib/read";
import type { SettingsArea } from "./settings-data";

export type QuestionKind = ReviewQuestion["kind"];

export type PipelineSetting = {
  key: string;
  version: number;
  saved: boolean;
  kind: string;
  title: string;
  sampleLimit: number;
  targets: string[];
  show: string[];
  reconcileReviewers: number | null;
  measure: string[];
  questions: ReviewQuestion[];
};

export type PipelineLimits = {
  questions: number;
  options: number;
  label: number;
  sample: number;
  kinds: QuestionKind[];
};

export type PipelineSettings = {
  canEdit: boolean;
  limits: PipelineLimits;
  pipelines: PipelineSetting[];
};

const KINDS: readonly QuestionKind[] = ["verdict", "pick", "correct", "scale"];
const SLUG = /^[a-z][a-z0-9_]{0,31}$/;

export const KIND_LABEL: Record<QuestionKind, string> = {
  verdict: "Verdict",
  pick: "Pick one",
  correct: "Correction",
  scale: "Scale 1–5",
};

export const TARGET_LABEL: Record<string, string> = {
  object: "Call objects",
  fact: "Facts",
  segment: "Moments",
  voice: "Voice",
  coaching: "Coaching points",
};

const asKind = (value: string): QuestionKind =>
  (KINDS as readonly string[]).includes(value)
    ? (value as QuestionKind)
    : "verdict";

function question(raw: unknown): ReviewQuestion {
  const body = read.object(raw);
  const when = read.object(body.when);
  return {
    key: read.string(body.key),
    kind: asKind(read.string(body.kind)),
    label: read.string(body.label, read.string(body.key)),
    options: read.strings(body.options),
    when: Object.fromEntries(
      Object.entries(when).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    ),
  };
}

export function normalizePipelineSettings(raw: unknown): PipelineSettings {
  const body = read.object(raw);
  const limits = read.object(body.limits);
  const kinds = read
    .strings(limits.kinds)
    .filter((kind) =>
      (KINDS as readonly string[]).includes(kind),
    ) as QuestionKind[];
  return {
    canEdit: body.can_edit === true,
    limits: {
      questions: read.number(limits.questions, 8),
      options: read.number(limits.options, 12),
      label: read.number(limits.label, 120),
      sample: read.number(limits.sample, 100),
      kinds: kinds.length ? kinds : [...KINDS],
    },
    pipelines: read.array(body.pipelines).map((item) => {
      const pipeline = read.object(item);
      const definition = read.object(pipeline.definition);
      const sample = read.object(definition.sample);
      const reconcile = read.object(definition.reconcile);
      return {
        key: read.string(pipeline.key),
        version: read.number(pipeline.version, 1),
        saved: pipeline.saved === true,
        kind: read.string(pipeline.kind, "analysis"),
        title: read.string(pipeline.title, read.string(pipeline.key)),
        sampleLimit: read.number(sample.limit, 20),
        targets: read.strings(definition.targets),
        show: read.strings(definition.show),
        reconcileReviewers: read.optionalNumber(reconcile.reviewers),
        measure: read.strings(definition.measure),
        questions: read.array(definition.questions).map(question),
      };
    }),
  };
}

/** All settings' row for Review pipelines: one line per pipeline, changed on its page. */
export function reviewArea(
  result: { ok: true; data: PipelineSettings } | { ok: false; error: string },
): SettingsArea {
  const base = {
    key: "review",
    title: "Review pipelines",
    what: "What gold reviewers judge in each pipeline, the questions they answer and the sample",
    href: "/settings/review-pipelines",
    revision: null,
    changedAt: null,
  };
  if (!result.ok) return { ...base, rows: [], unavailable: result.error };
  return {
    ...base,
    unavailable: null,
    rows: result.data.pipelines.map((pipeline) => ({
      label: pipeline.title,
      value: `Version ${pipeline.version} · ${pipeline.questions.length} ${
        pipeline.questions.length === 1 ? "question" : "questions"
      } · ${pipeline.sampleLimit} calls a sample`,
      note: `${pipeline.targets.map((target) => TARGET_LABEL[target] ?? target).join(", ")}${
        pipeline.saved ? "" : " · default, never edited"
      }`,
    })),
  };
}

/** "Buyer's emotion!" → "buyers_emotion"; always a valid key or "". */
export function slug(text: string): string {
  const value = text
    .toLowerCase()
    .replaceAll(/[^a-z0-9]+/g, "_")
    .replaceAll(/^_+|_+$/g, "")
    .slice(0, 32);
  return /^[a-z]/.test(value) ? value : value ? `x_${value}`.slice(0, 32) : "";
}

/** "Correct, wrong , Not sure" → ["correct", "wrong", "not_sure"]. */
export function optionsFromText(text: string): string[] {
  return text
    .split(",")
    .map((item) => slug(item.trim()))
    .filter(Boolean);
}

/** A key no other question uses, for a question added in the editor. */
export function newQuestionKey(questions: ReviewQuestion[]): string {
  const taken = new Set(questions.map((item) => item.key));
  let index = questions.length + 1;
  while (taken.has(`question_${index}`)) index += 1;
  return `question_${index}`;
}

/** The checks the API runs, in the same words, so a draft that fails never leaves. */
export function draftProblems(
  draft: { title: string; sampleLimit: number; questions: ReviewQuestion[] },
  limits: PipelineLimits,
): string[] {
  const problems: string[] = [];
  if (!draft.title.trim() || draft.title.trim().length > limits.label)
    problems.push(`Write a title (1 to ${limits.label} characters).`);
  if (
    !Number.isInteger(draft.sampleLimit) ||
    draft.sampleLimit < 1 ||
    draft.sampleLimit > limits.sample
  )
    problems.push(`Sample 1 to ${limits.sample} calls at a time.`);
  if (!draft.questions.length || draft.questions.length > limits.questions)
    problems.push(`A pipeline asks 1 to ${limits.questions} questions.`);
  const seen = new Map<string, ReviewQuestion>();
  draft.questions.forEach((item, index) => {
    const place = `Question ${index + 1}`;
    if (!SLUG.test(item.key) || seen.has(item.key))
      problems.push(`${place}: its key must be unique.`);
    if (!item.label.trim() || item.label.trim().length > limits.label)
      problems.push(
        `${place}: write the question (1 to ${limits.label} characters).`,
      );
    if (item.kind === "verdict" || item.kind === "pick") {
      const unique = new Set(item.options);
      if (
        item.options.length < 2 ||
        item.options.length > limits.options ||
        unique.size !== item.options.length
      )
        problems.push(
          `${place}: give 2 to ${limits.options} different options.`,
        );
    }
    const follow = Object.entries(item.when);
    if (follow.length) {
      const [after, option] = follow[0];
      if (follow.length > 1 || !seen.get(after)?.options.includes(option))
        problems.push(
          `${place}: it must follow an option of an earlier question.`,
        );
    }
    seen.set(item.key, item);
  });
  if (draft.questions.length && draft.questions[0].kind !== "verdict")
    problems.push(
      "The first question must be a verdict: Analysis health measures it.",
    );
  return problems;
}

/** The POST body: only what the API reads, options only where they belong. */
export function pipelineRequest(
  basedOn: number,
  draft: { title: string; sampleLimit: number; questions: ReviewQuestion[] },
) {
  return {
    based_on: basedOn,
    title: draft.title.trim(),
    sample_limit: draft.sampleLimit,
    questions: draft.questions.map((item) => ({
      key: item.key,
      kind: item.kind,
      label: item.label.trim(),
      ...(item.kind === "verdict" || item.kind === "pick"
        ? { options: item.options }
        : {}),
      ...(Object.keys(item.when).length ? { when: item.when } : {}),
    })),
  };
}
