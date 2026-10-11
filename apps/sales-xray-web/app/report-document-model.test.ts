import { describe, expect, it } from "vitest";

import type { SalesReport, Transcript } from "./report-contract";
import {
  docItemText,
  reportDocumentModel,
  type DocItem,
  type ReportDoc,
} from "./report-document-model";
import {
  AMIT_SPEAKERS,
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import { syntheticReport } from "./review-fixture/report/synthetic-report";

const NAMES: Record<string, string> = {
  [AMIT_SPEAKERS.seller]: "Arjun",
  [AMIT_SPEAKERS.prospect]: "Amit Sharma",
};

const amitDoc = () =>
  reportDocumentModel(
    {
      report: amitReport as SalesReport,
      transcript: amitTranscript as Transcript,
      title: "Amit Sharma · discovery call",
      callDate: "9 Oct 2026",
    },
    { roles: AMIT_SPEAKERS, speakerName: (id) => NAMES[id] },
  );

function items(doc: ReportDoc): DocItem[] {
  const all: DocItem[] = [];
  const walk = (item: DocItem) => {
    all.push(item);
    if (item.type === "card") item.items.forEach(walk);
  };
  for (const section of doc.sections)
    for (const part of section.parts) part.items.forEach(walk);
  if (doc.summary) walk(doc.summary);
  return all;
}
const textOf = (doc: ReportDoc) =>
  [
    doc.title,
    ...doc.facts.map((f) => `${f.label} ${f.value}`),
    ...doc.sections.flatMap((s) => [
      s.heading,
      s.subtitle,
      ...s.parts.map((p) => p.heading ?? ""),
      ...s.gaps,
    ]),
    ...items(doc).map(docItemText),
  ].join("\n");

describe("report document model", () => {
  it("follows Dipak's document: six pillars, numbered parts, in order", () => {
    const doc = amitDoc();
    expect(doc.sections.map((s) => s.heading)).toEqual([
      "1. The Big Picture",
      "2. How the Call Played Out",
      "3. What Worked — & What Didn't",
      "4. Moments That Mattered",
      "5. Your Skills on This Call",
      "6. Where the Deal Stands",
    ]);
    expect(doc.sections[0].parts.map((p) => p.heading)).toEqual([
      "1.1 Call Outcome",
      "1.2 Executive Summary",
      "1.3 What Most Affected This Call",
      "1.4 Strongest Part",
      "1.5 Biggest Concern",
      "1.6 Next Agreed Step",
    ]);
    expect(doc.sections[1].parts.map((p) => p.heading)).toEqual([
      "2.1 Call Metrics",
      "2.2 Conversation Timeline",
      "2.3 Key Change in the Conversation",
      "2.4 Before / Switch / After",
    ]);
    expect(doc.sections[2].parts.map((p) => p.heading)).toEqual([
      "3.1 What Worked",
      "3.2 What Didn't",
    ]);
    const deal = doc.sections[5].parts.map((p) => p.heading);
    expect(deal[0]).toBe("6.1 Current Status");
    expect(deal).toContain("6.4 Prospect Commitment");
    expect(deal).toContain("6.9 Recommended Deal Action");
  });

  it("puts the call's own words, names and play times in the page", () => {
    const doc = amitDoc();
    const [outcome] = doc.sections[0].parts[0].items;
    expect(outcome).toMatchObject({ type: "status" });
    const strongest = doc.sections[0].parts[3].items[0];
    expect(strongest).toMatchObject({ type: "text" });
    expect(strongest.type === "text" && strongest.clip?.at).toMatch(
      /^\d\d:\d\d$/,
    );
    const quotes = items(doc).filter((i) => i.type === "quote");
    expect(quotes.length).toBeGreaterThan(0);
    expect(
      quotes.some(
        (q) => q.type === "quote" && q.clip.speaker === "Amit Sharma",
      ),
    ).toBe(true);
    expect(textOf(doc)).toContain("Amit Sharma agreed to:");
    expect(doc.facts).toContainEqual({
      label: "Prospect",
      value: "Amit Sharma",
    });
    expect(doc.facts).toContainEqual({ label: "Call length", value: "25:08" });
  });

  it("shows at most five moment cards and lists the rest", () => {
    const doc = amitDoc();
    const moments = doc.sections[3];
    const cards = moments.parts[0].items.filter((i) => i.type === "card");
    expect(cards.length).toBeGreaterThanOrEqual(3);
    expect(cards.length).toBeLessThanOrEqual(5);
    for (const card of cards)
      expect(card.type === "card" && card.kicker).toMatch(/ · \d\d:\d\d$/);
  });

  it("opens all eight skills and ends with the summary strip", () => {
    const doc = amitDoc();
    const skills = doc.sections[4].parts[0].items[0];
    expect(skills.type === "skills" && skills.rows.map((r) => r.name)).toEqual([
      "Human Connection & Trust",
      "Discovery & Deep Understanding",
      "Qualification",
      "Problem, Impact & Desire Clarity",
      "Solution Relevance & Presentation",
      "Certainty & Objection Intelligence",
      "Closing & Decision Management",
      "Communication & Tonality",
    ]);
    expect(doc.summary?.type === "summary" && doc.summary.cells[0].label).toBe(
      "Call Outcome",
    );
  });

  it("an older, sparse report still makes a whole document with honest gaps", () => {
    const doc = reportDocumentModel({ report: syntheticReport as SalesReport });
    expect(doc.sections).toHaveLength(6);
    for (const section of doc.sections)
      for (const part of section.parts)
        expect(part.items.length).toBeGreaterThan(0);
    expect(doc.sections.some((s) => s.gaps.length > 0)).toBe(true);
    expect(doc.title).toBe("Sales call");
  });

  it("never prints internal words or empty values", () => {
    for (const doc of [
      amitDoc(),
      reportDocumentModel({ report: syntheticReport as SalesReport }),
    ]) {
      const text = textOf(doc);
      expect(text).not.toMatch(
        /\b(undefined|null|NaN|\[object Object\]|inferred|insufficient_evidence|C5)\b/,
      );
    }
  });

  it("refuses to build without a report", () => {
    expect(() => reportDocumentModel({})).toThrow("document_report_missing");
  });
});
