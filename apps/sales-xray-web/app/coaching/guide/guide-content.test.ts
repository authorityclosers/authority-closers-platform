import { describe, expect, it } from "vitest";

import example from "../../review-fixture/coaching-guide/example.json";
import content from "./content.json";
import summaryFile from "./content-summary.json";
import {
  guideShown,
  parseGuide,
  parseSummary,
  summaryHint,
} from "./guide-content";

/** Fictional placeholder rows, never coaching content. */
function file(overrides: Record<string, unknown> = {}) {
  const q = (id: string, next: string[], start = false) => ({
    id,
    tab: "Tab A",
    question: `Question ${id}?`,
    answer: `Answer ${id}.`,
    next,
    category: "closing",
    tags: [],
    sale_stage: "",
    difficulty: "",
    example_line: "",
    start,
  });
  return {
    format: 1,
    version: 3,
    sha256: "x",
    welcome: "",
    examples: false,
    starters: ["A-1"],
    questions: [q("A-1", ["A-2"], true), q("A-2", ["A-1"])],
    ...overrides,
  };
}

describe("Dipak's answers content", () => {
  it("reads a good file and shows it", () => {
    const guide = parseGuide(file());
    expect(guide?.questions.get("A-1")?.next).toEqual(["A-2"]);
    expect(guide?.version).toBe(3);
    expect(guideShown(guide)).toBe(true);
  });

  it("never shows an empty file or EXAMPLE content", () => {
    const empty = parseGuide(file({ starters: [], questions: [] }));
    expect(empty).not.toBeNull();
    expect(guideShown(empty)).toBe(false);
    expect(guideShown(parseGuide(file({ examples: true })))).toBe(false);
    // A file that does not say is treated as examples.
    const unsaid: Record<string, unknown> = file();
    delete unsaid.examples;
    expect(guideShown(parseGuide(unsaid))).toBe(false);
  });

  it.each([
    ["another format", { format: 2 }],
    ["no starter", { starters: [] }],
    ["a starter that is not a question", { starters: ["A-9"] }],
    ["five starters", { starters: ["A-1", "A-1", "A-2", "A-2", "A-1"] }],
    [
      "a follow-up to a missing question",
      {
        questions: [{ id: "A-1", question: "Q?", answer: "A.", next: ["A-9"] }],
      },
    ],
    [
      "four follow-ups",
      {
        questions: [
          {
            id: "A-1",
            question: "Q?",
            answer: "A.",
            next: ["A-1", "A-1", "A-1", "A-1"],
          },
        ],
      },
    ],
    [
      "a repeated id",
      {
        questions: [
          { id: "A-1", question: "Q?", answer: "A.", next: [] },
          { id: "A-1", question: "R?", answer: "B.", next: [] },
        ],
      },
    ],
    [
      "an empty answer",
      { questions: [{ id: "A-1", question: "Q?", answer: " ", next: [] }] },
    ],
    [
      "an id with a space",
      { questions: [{ id: "A 1", question: "Q?", answer: "A.", next: [] }] },
    ],
  ])("refuses %s", (_, overrides) => {
    expect(parseGuide(file(overrides))).toBeNull();
  });

  it("ships a content file the screen can walk, and its summary agrees", () => {
    const guide = parseGuide(content);
    expect(guide).not.toBeNull();
    const summary = parseSummary(summaryFile);
    expect(summary).not.toBeNull();
    expect(summaryFile.sha256).toBe(content.sha256);
    expect(summary?.version).toBe(guide?.version);
    expect(summary?.questions).toBe(guide?.questions.size);
    expect(summary?.shown).toBe(guideShown(guide));
    // Content with EXAMPLE rows never goes into the app's own file.
    expect(guide?.examples).toBe(false);
  });

  it("keeps the template's EXAMPLE rows in the review fixture only", () => {
    const guide = parseGuide(example);
    expect(guide?.examples).toBe(true);
    expect(guideShown(guide)).toBe(false);
    expect(guide?.starters).toEqual(["EXAMPLE-1", "EXAMPLE-2"]);
  });

  it("says what the guide answers, in plain words", () => {
    const hint = (questions: number, categories: string[]) =>
      summaryHint({ version: 1, shown: true, questions, categories });
    expect(hint(58, ["objection handling", "closing", "discovery"])).toBe(
      "Objection handling, closing and more · 58 questions",
    );
    expect(hint(1, ["closing"])).toBe("Closing · 1 question");
    expect(hint(12, [])).toBe("12 questions");
    expect(
      parseSummary({ version: 1, shown: true, questions: 0, categories: [] })
        ?.shown,
    ).toBe(false);
  });
});
