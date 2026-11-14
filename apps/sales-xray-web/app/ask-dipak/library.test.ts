import { describe, expect, it } from "vitest";

import coach from "./coach-notes.json";
import { hasIcon } from "./icons";
import data from "./library.json";
import {
  ALIASES,
  CATEGORIES,
  CATEGORY_ICONS,
  CATEGORY_LABELS,
  FEATURED,
  LESSONS,
  QUESTIONS,
  REAL_SITUATIONS,
  SUGGESTIONS,
  featuredQuestions,
  lessonFor,
  questionById,
  questionLabel,
  searchQuestions,
} from "./library";

/** Dipak's spec, section 8: the ten categories and their question counts. */
const SPEC_CATEGORIES = [
  ["01", "Sales Mindset & Psychology", 14],
  ["02", "Rapport Building & Trust", 10],
  ["03", "Communication & Listening", 18],
  ["04", "Problem & Desire Discovery", 14],
  ["05", "Value Creation & Quantification", 10],
  ["06", "Qualification & Decision Process", 18],
  ["07", "Solution Presentation & Influence", 14],
  ["08", "Objection Handling & Negotiation", 15],
  ["09", "Closing & Follow-Up", 16],
  ["10", "Sales Growth & Performance", 21],
] as const;

/** Spec section 24: the twelve complete lessons. */
const SPEC_LESSONS = [
  "CF01",
  "RP01",
  "TP03",
  "PG01",
  "IM01",
  "DM01",
  "EX02",
  "PB03",
  "NX02",
  "NEW-035",
  "DM02",
  "OB03",
];

const ids = (list: readonly { id: string }[]) => list.map((item) => item.id);

describe("the topic library (spec sections 8, 24, 26, 27, 33)", () => {
  it("has all 10 categories, titled as the source, with their question counts", () => {
    expect(
      CATEGORIES.map((category) => [
        category.id,
        category.name,
        category.questions.length,
      ]),
    ).toEqual(SPEC_CATEGORIES);
  });

  it("keeps all 150 question records, each with its own unique ID", () => {
    expect(QUESTIONS).toHaveLength(150);
    expect(new Set(ids(QUESTIONS)).size).toBe(150);
    for (const question of QUESTIONS)
      expect(question.id).toMatch(/^([A-Z]{2}\d{2}|NEW-\d{3})$/);
  });

  it("keeps each question in its own category, with its category's source document", () => {
    for (const category of CATEGORIES) {
      expect(category.doc).toMatch(
        /^https:\/\/docs\.google\.com\/document\/d\/[\w-]+\/edit$/,
      );
      for (const { id } of category.questions)
        expect(questionById(id)).toMatchObject({
          categoryId: category.id,
          categoryName: category.name,
          source: category.doc,
        });
    }
  });

  it("has an icon and a short line for every category", () => {
    for (const category of CATEGORIES) {
      expect(hasIcon(CATEGORY_ICONS[category.id])).toBe(true);
      expect(CATEGORY_LABELS[category.id]).toBeTruthy();
    }
  });

  it("holds exactly the twelve complete lessons, each whole", () => {
    expect(Object.keys(LESSONS).sort()).toEqual([...SPEC_LESSONS].sort());
    for (const id of SPEC_LESSONS) {
      const lesson = lessonFor(id);
      expect(questionById(id), id).not.toBeNull();
      expect(lesson?.quick, id).toBeTruthy();
      expect(lesson?.scenario, id).toBeTruthy();
      expect(lesson?.options, id).toHaveLength(3);
      for (const option of lesson?.options ?? [])
        expect(
          option.every((part) => part.trim().length > 0),
          id,
        ).toBe(true);
      expect(new Set(lesson?.options.map((option) => option[1])).size).toBe(3);
      expect(lesson?.deep.length, id).toBeGreaterThan(0);
      expect(lesson?.cue, id).toBeTruthy();
      expect(lesson?.mission, id).toBeTruthy();
      expect(lesson?.next.length, id).toBeGreaterThan(0);
      for (const next of lesson?.next ?? [])
        expect(questionById(next), `${id} → ${next}`).not.toBeNull();
    }
  });

  it("invents no lesson for the other 138 questions", () => {
    const without = QUESTIONS.filter((question) => !lessonFor(question.id));
    expect(without).toHaveLength(138);
    expect(lessonFor("toString")).toBeNull();
  });

  it("keeps the coaching notes apart from the learner's lessons", () => {
    expect(Object.keys(coach.notes).sort()).toEqual([...SPEC_LESSONS].sort());
    const learner = JSON.stringify(data.lessons);
    expect(learner).not.toContain('"coach"');
    for (const note of Object.values(coach.notes))
      expect(learner).not.toContain(note);
  });

  it("keeps Dipak's Hindi-English words as written", () => {
    expect(lessonFor("PB03")?.cue).toBe(
      "“Expensive” सुनते ही discount नहीं; पहले पूछिए किस comparison में।",
    );
    expect(lessonFor("PB03")?.mission).toBe(
      "अगली तीन price objections में discount से पहले actual comparison पूछें।",
    );
    expect(data.sourceSha256).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe("the homepage's shortcuts use the same records (spec sections 7 and 10)", () => {
  it("groups the four featured topics from the full categories", () => {
    expect(
      FEATURED.map((topic) => [topic.name, topic.sub, [...topic.cats]]),
    ).toEqual([
      ["Communication & Rapport", "Trust और listening", ["02", "03"]],
      ["Customer को समझना", "Problem और impact", ["04", "05"]],
      ["Price & Objections", "Price और hesitation", ["08"]],
      ["Closing & Follow-Up", "Decision और next steps", ["09"]],
    ]);
    for (const topic of FEATURED) {
      expect(hasIcon(topic.icon)).toBe(true);
      const questions = featuredQuestions(topic);
      expect(questions.length).toBe(
        topic.cats.reduce(
          (sum, cat) =>
            sum + (CATEGORIES.find((c) => c.id === cat)?.questions.length ?? 0),
          0,
        ),
      );
      for (const question of questions)
        expect(questionById(question.id)).toBe(question);
    }
  });

  it("links the three real situations to PB03, DM02 and OB03, in Dipak's words", () => {
    expect(REAL_SITUATIONS).toEqual(["PB03", "DM02", "OB03"]);
    expect(
      REAL_SITUATIONS.map((id) => questionLabel(questionById(id)!)),
    ).toEqual([
      "Customer कहता है, “Price बहुत high है।” क्या करूँ?",
      "“मुझे wife/partner से पूछना है।” क्या यह objection है?",
      "Customer बोलता है, “मैं सोचकर बताऊँगा।” अब क्या करूँ?",
    ]);
  });
});

describe("search (spec sections 11, 12, 33)", () => {
  it("suggests six questions while the field is empty", () => {
    expect(SUGGESTIONS).toEqual([
      "PB03",
      "OB03",
      "DM02",
      "NX02",
      "RP01",
      "CO02",
    ]);
    expect(ids(searchQuestions(""))).toEqual(SUGGESTIONS);
    expect(ids(searchQuestions("   "))).toEqual(SUGGESTIONS);
  });

  it("finds titles, ignoring case", () => {
    expect(ids(searchQuestions("CONFIDENT"))).toContain("CF01");
    expect(ids(searchQuestions("rapport, really"))).toEqual(["RP01"]);
  });

  it("finds a category's questions by its name", () => {
    const found = searchQuestions("closing & follow-up");
    expect(ids(found)).toEqual(
      expect.arrayContaining(
        CATEGORIES.find((c) => c.id === "09")!.questions.map((q) => q.id),
      ),
    );
  });

  it("finds a question by its ID and by its shown wording", () => {
    expect(ids(searchQuestions("nx02"))).toEqual(["NX02"]);
    expect(ids(searchQuestions("सोचकर बताऊँगा"))[0]).toBe("OB03");
  });

  it.each(Object.entries(ALIASES))(
    "puts the alias %s's question first (%s)",
    (word, id) => {
      expect(ids(searchQuestions(word))[0]).toBe(id);
      expect(ids(searchQuestions(`customer said ${word} today`))).toContain(id);
    },
  );

  it("knows the sample's aliases", () => {
    expect(ALIASES).toEqual({
      expensive: "PB03",
      mahanga: "PB03",
      "high price": "PB03",
      "price high": "PB03",
      कीमत: "PB03",
      discount: "PB05",
      wife: "DM02",
      partner: "DM02",
      सोचकर: "OB03",
      सोचना: "OB03",
      think: "OB03",
      lead: "LE03",
      followup: "FU02",
      "follow-up": "FU02",
    });
  });

  it("finds nothing rather than something unrelated", () => {
    expect(searchQuestions("xyzzy")).toEqual([]);
  });

  it("lists each question once", () => {
    const found = ids(searchQuestions("price"));
    expect(new Set(found).size).toBe(found.length);
  });
});
