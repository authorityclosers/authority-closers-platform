/**
 * Dipak's guided coaching (owner and Dipak, 2 Nov 2026): his own questions
 * and answers, walked from up to 4 starters through up to 3 follow-ups each.
 * No AI, no typing and no request to the server: content.json is built from
 * his sheet by scripts/coaching_guide.py, and the screen shows exactly what
 * it holds. content-summary.json is its small twin for the Coaching page's
 * entry row, so that row is there on the first paint or not at all.
 *
 * Hidden until real content is loaded: an empty file, EXAMPLE content or a
 * file that fails these checks is never shown to users.
 */

export type GuideQuestion = {
  id: string;
  tab: string;
  question: string;
  answer: string;
  next: string[];
  category: string;
  tags: string[];
  sale_stage: string;
  difficulty: string;
  example_line: string;
  start: boolean;
};

export type Guide = {
  version: number;
  welcome: string;
  examples: boolean;
  starters: string[];
  questions: Map<string, GuideQuestion>;
};

export type GuideSummary = {
  version: number;
  shown: boolean;
  questions: number;
  categories: string[];
};

export const MAX_STARTERS = 4;
export const MAX_NEXT = 3;
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const text = (value: unknown) => (typeof value === "string" ? value : "");

const strings = (value: unknown): string[] | null =>
  Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : null;

function question(raw: unknown): GuideQuestion | null {
  if (!isRecord(raw)) return null;
  const next = strings(raw.next);
  const tags = strings(raw.tags ?? []);
  if (
    typeof raw.id !== "string" ||
    !ID.test(raw.id) ||
    !text(raw.question).trim() ||
    !text(raw.answer).trim() ||
    !next ||
    next.length > MAX_NEXT ||
    !tags
  )
    return null;
  return {
    id: raw.id,
    tab: text(raw.tab),
    question: text(raw.question).trim(),
    answer: text(raw.answer).trim(),
    next,
    category: text(raw.category).trim(),
    tags,
    sale_stage: text(raw.sale_stage),
    difficulty: text(raw.difficulty),
    example_line: text(raw.example_line).trim(),
    start: raw.start === true,
  };
}

/**
 * The file as the screen can walk it, or null. The converter already refuses
 * a broken sheet; this refuses a broken or hand-edited file the same way, so
 * a seller never lands on a missing answer.
 */
export function parseGuide(raw: unknown): Guide | null {
  if (!isRecord(raw) || raw.format !== 1) return null;
  const starters = strings(raw.starters);
  if (
    typeof raw.version !== "number" ||
    !Array.isArray(raw.questions) ||
    !starters
  )
    return null;
  const questions = new Map<string, GuideQuestion>();
  for (const item of raw.questions) {
    const parsed = question(item);
    if (!parsed || questions.has(parsed.id)) return null;
    questions.set(parsed.id, parsed);
  }
  if (questions.size > 0) {
    if (starters.length === 0 || starters.length > MAX_STARTERS) return null;
    if (new Set(starters).size !== starters.length) return null;
  }
  for (const id of starters) if (!questions.has(id)) return null;
  for (const item of questions.values())
    for (const id of item.next) if (!questions.has(id)) return null;
  return {
    version: raw.version,
    welcome: text(raw.welcome).trim(),
    examples: raw.examples !== false,
    starters,
    questions,
  };
}

/** Real content only: never an empty file, never EXAMPLE rows. */
export const guideShown = (guide: Guide | null): guide is Guide =>
  guide !== null && guide.questions.size > 0 && !guide.examples;

export function parseSummary(raw: unknown): GuideSummary | null {
  if (!isRecord(raw)) return null;
  const categories = strings(raw.categories);
  if (
    typeof raw.version !== "number" ||
    typeof raw.questions !== "number" ||
    !categories
  )
    return null;
  return {
    version: raw.version,
    shown: raw.shown === true && raw.questions > 0,
    questions: raw.questions,
    categories,
  };
}

export const questionCount = (count: number) =>
  `${count} ${count === 1 ? "question" : "questions"}`;

/** "Objection handling, closing and more": the kinds of question it answers. */
export function summaryHint(summary: GuideSummary): string {
  const count = questionCount(summary.questions);
  const kinds = summary.categories
    .slice(0, 2)
    .map((kind, index) =>
      index === 0 ? kind.charAt(0).toUpperCase() + kind.slice(1) : kind,
    );
  if (!kinds.length) return count;
  const more = summary.categories.length > 2 ? " and more" : "";
  return `${kinds.join(", ")}${more} · ${count}`;
}

let loading: Promise<Guide | null> | null = null;

/**
 * The whole content, in its own chunk: only the guide's screen pays for it,
 * once per visit. A failed load is tried again next time.
 */
export function loadGuide(): Promise<Guide | null> {
  loading ??= import("./content.json").then(
    (module) => parseGuide(module.default),
    () => {
      loading = null;
      return null;
    },
  );
  return loading;
}
