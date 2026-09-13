// @vitest-environment node
import { expect, it } from "vitest";
import { practiceCatalogSchema, practiceSetSchema } from "./practice-api";

const summary = {
  id: "next-move",
  version: 1,
  title: "Choose your next move",
  kind: "choice",
  skill: "Discovery",
  description: "Practice a question.",
  art: "discovery-compass",
  color: "cobalt",
  estimated_minutes: 4,
  item_count: 1,
};
const item = {
  id: "choice-01",
  kind: "choice",
  prompt: "What could clarify?",
  hint: "Ask a question.",
  options: [
    { id: 0, text: "Ask what matters." },
    { id: 1, text: "Assume the answer." },
  ],
};

it.each([
  ["editorial_preview", false],
  ["published", true],
] as const)("accepts the %s catalog contract", (mode, responsesStored) => {
  expect(
    practiceCatalogSchema.parse({
      mode,
      items: [summary],
      course_progress_affected: false,
      responses_stored: responsesStored,
    }),
  ).toMatchObject({ mode, responses_stored: responsesStored });
});

it("rejects a catalog with mismatched persistence semantics", () => {
  expect(() =>
    practiceCatalogSchema.parse({
      mode: "published",
      items: [summary],
      course_progress_affected: false,
      responses_stored: false,
    }),
  ).toThrow();
});

it("accepts a published set snapshot for the durable pilot", () => {
  expect(
    practiceSetSchema.parse({
      ...summary,
      mode: "published",
      items: [item],
    }),
  ).toMatchObject({ id: "next-move", mode: "published", items: [item] });
});
