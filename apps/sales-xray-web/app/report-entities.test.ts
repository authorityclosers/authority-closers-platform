import { expect, it } from "vitest";

import { findEntities, type EntityKind } from "./report-entities";

const kinds = (text: string) =>
  findEntities(text)
    .filter(
      (part): part is { kind: EntityKind; text: string } =>
        typeof part !== "string",
    )
    .map((part) => [part.kind, part.text]);

it("finds what the report mentions, with the words it used", () => {
  expect(
    kinds(
      "You pivoted to pitching the 3-day Leadership Funnel Program and agreed to share video material over WhatsApp and arrange a call the next day alongside a senior manager.",
    ),
  ).toEqual([
    ["program", "3-day Leadership Funnel Program"],
    ["video", "video"],
    ["whatsapp", "WhatsApp"],
    ["date", "next day"],
    ["person", "senior manager"],
  ]);
  expect(
    kinds(
      "It uncovered 15 to 20 lakh of unpaid receivables and the syllabus and workbook.",
    ),
  ).toEqual([
    ["money", "15 to 20 lakh"],
    ["money", "unpaid receivables"],
    ["document", "syllabus"],
    ["document", "workbook"],
  ]);
});

it("leaves ordinary words alone", () => {
  expect(kinds("They asked about the program and the call went well.")).toEqual(
    [],
  );
  expect(findEntities("No mentions here.")).toEqual(["No mentions here."]);
});
