/**
 * Ask Dipak's library (Dipak's spec and clickable sample, 13 Nov 2026): a
 * predefined sales-learning library, not a chatbot. Ten categories, 150
 * questions with stable IDs and twelve complete lessons, read from
 * library.json, which is the sample's own data copied word for word (its
 * internal coaching notes are kept apart in coach-notes.json and never reach
 * the learner's screen). The other 138 questions have no approved lesson yet,
 * and nothing here writes one.
 */

import data from "./library.json";

export type Category = Readonly<{
  id: string;
  name: string;
  description: string;
  /** The category's source document in Dipak's folder (spec section 27). */
  doc: string;
  questions: readonly Readonly<{ id: string; title: string }>[];
}>;

export type Question = Readonly<{
  id: string;
  title: string;
  categoryId: string;
  categoryName: string;
  source: string;
}>;

/** One MCQ option: what the seller says, why it works or not, the takeaway. */
export type Option = readonly [choice: string, why: string, takeaway: string];

export type Lesson = Readonly<{
  quick: string;
  scenario: string;
  options: readonly Option[];
  deep: readonly string[];
  cue: string;
  mission: string;
  next: readonly string[];
}>;

export type Featured = Readonly<{
  id: string;
  name: string;
  sub: string;
  icon: string;
  cats: readonly string[];
}>;

export const CATEGORIES: readonly Category[] = data.categories;
export const FEATURED: readonly Featured[] = data.featured;
export const LESSONS = data.lessons as unknown as Readonly<
  Record<string, Lesson>
>;
/** The sample's short card line and icon per category ("Price और hesitation"). */
export const CATEGORY_LABELS: Readonly<Record<string, string>> =
  data.categoryLabels;
export const CATEGORY_ICONS: Readonly<Record<string, string>> =
  data.categoryIcons;
/** The homepage's real-situation wording of three questions (PB03, DM02, OB03). */
const LABELS: Readonly<Record<string, string>> = data.labels;
/** Shown while the search field is empty (spec section 11). */
export const SUGGESTIONS: readonly string[] = data.suggestions;
/** Common words that point at one question ("mahanga" → PB03). */
export const ALIASES: Readonly<Record<string, string>> = data.aliases;
/** "Start with a real situation", in the sample's order. */
export const REAL_SITUATIONS = ["PB03", "DM02", "OB03"] as const;

export const QUESTIONS: readonly Question[] = CATEGORIES.flatMap((category) =>
  category.questions.map((question) => ({
    id: question.id,
    title: question.title,
    categoryId: category.id,
    categoryName: category.name,
    source: category.doc,
  })),
);

const BY_ID = new Map(QUESTIONS.map((question) => [question.id, question]));
const BY_CATEGORY = new Map(
  CATEGORIES.map((category) => [category.id, category]),
);

export const questionById = (id: string): Question | null =>
  BY_ID.get(id) ?? null;
export const categoryById = (id: string): Category | null =>
  BY_CATEGORY.get(id) ?? null;
export const featuredById = (id: string): Featured | null =>
  FEATURED.find((topic) => topic.id === id) ?? null;
export const lessonFor = (id: string): Lesson | null =>
  Object.prototype.hasOwnProperty.call(LESSONS, id) ? LESSONS[id] : null;

/** The words a question is shown with: its real-situation wording, if any. */
export const questionLabel = (question: Question): string =>
  LABELS[question.id] ?? question.title;

/** A lesson's category chip; the price lesson carries its featured topic's name, as in the sample. */
export const lessonChip = (question: Question): string =>
  question.id === "PB03" ? "Price & Objections" : question.categoryName;

/** A featured topic's questions: its categories' own records, never copies. */
export const featuredQuestions = (topic: Featured): Question[] =>
  QUESTIONS.filter((question) => topic.cats.includes(question.categoryId));

export const categoryQuestions = (category: Category): Question[] =>
  QUESTIONS.filter((question) => question.categoryId === category.id);

/**
 * The sample's keyword search: titles, category names, IDs and the shown
 * wording, ignoring case, with its aliases first. No AI, no guessing: an
 * empty field shows the six suggestions, and no match shows none.
 */
export function searchQuestions(query: string): Question[] {
  const needle = query.toLocaleLowerCase().trim();
  if (!needle)
    return SUGGESTIONS.map((id) => BY_ID.get(id)).filter(
      (question): question is Question => Boolean(question),
    );
  const special = Object.entries(ALIASES)
    .filter(([word]) => needle.includes(word))
    .map(([, id]) => BY_ID.get(id))
    .filter((question): question is Question => Boolean(question));
  const match = QUESTIONS.filter((question) =>
    [
      question.title,
      question.categoryName,
      question.id,
      questionLabel(question),
    ].some((text) => text.toLocaleLowerCase().includes(needle)),
  );
  return [
    ...new Map(
      [...special, ...match].map((question) => [question.id, question]),
    ).values(),
  ];
}
