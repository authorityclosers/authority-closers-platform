import { describe, expect, it } from "vitest";

import { MOMENTS } from "./report-copy";
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
import { v8Report } from "./review-fixture/report/pillars/v8-report";
import { AMIT_PILLARS } from "./review-fixture/report/story/amit-pillars";
import callB from "./review-fixture/report/story/fictional-call-b.json";
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
    expect(textOf(doc)).toContain("Clear because Friday · 4:00 PM is agreed.");
  });

  it("shows the outcome a person recorded, in 1.1 and 6.1, with their reason", () => {
    const doc = reportDocumentModel(
      {
        report: amitReport as SalesReport,
        transcript: amitTranscript as Transcript,
      },
      {
        roles: AMIT_SPEAKERS,
        speakerName: (id) => NAMES[id],
        recorded: { status: "Lost", note: "Went with a cheaper course." },
      },
    );
    const [status, reason] = doc.sections[0].parts[0].items;
    expect(status).toEqual({
      type: "status",
      status: "Lost",
      origin: "Set by your team",
      tone: expect.any(String),
    });
    expect(reason).toMatchObject({
      type: "text",
      text: "Went with a cheaper course.",
    });
    const current = doc.sections[5].parts[0];
    expect(current.heading).toBe("6.1 Current Status");
    expect(current.items[0]).toMatchObject({ type: "status", status: "Lost" });
    // Without a person's record the call's own reading stays.
    const [heard] = amitDoc().sections[0].parts[0].items;
    expect(heard).toMatchObject({ origin: "As heard on the call" });
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
      "Discovery",
      "Qualification",
      "Problem / Impact / Desire",
      "Presentation & Value",
      "Objection Intelligence",
      "Closing",
      "Communication",
    ]);
    expect(doc.summary?.type === "summary" && doc.summary.cells[0].label).toBe(
      "Call Outcome",
    );
  });

  it("an observed skill without a note shows its state and play times only", () => {
    // C's sandbox writes `observation: ""` (or a stock note) for a cited skill.
    const report = structuredClone(amitReport) as SalesReport;
    const notes: Record<string, string> = {
      human_connection_trust: "",
      qualification: "Relevant behaviour is evidenced by the cited turn.",
    };
    for (const d of report.dimensions)
      if (d.dimension_id in notes) d.observation = notes[d.dimension_id];
    report.dimensions = report.dimensions.filter(
      (d) => d.dimension_id !== "closing_decision_management",
    );
    const doc = reportDocumentModel(
      { report, transcript: amitTranscript as Transcript },
      { roles: AMIT_SPEAKERS },
    );
    const skills = doc.sections[4].parts[0].items[0];
    if (skills.type !== "skills") throw new Error("no skills");
    const row = (name: string) => skills.rows.find((r) => r.name === name)!;
    for (const name of ["Human Connection & Trust", "Qualification"]) {
      expect(row(name).state).toBe(
        name === "Qualification" ? "Observed" : "Strongly Demonstrated",
      );
      expect(row(name).observation).toBe("");
      expect(row(name).clips.length).toBeGreaterThan(0);
    }
    // A skill the report doesn't cover still says so.
    expect(row("Closing").state).toBe("Not covered");
    expect(row("Closing").observation).toBe(
      "This report doesn't cover this skill.",
    );
  });

  it("opens Deep Analysis in the spec's groups and order", () => {
    const deeper = amitDoc().sections[4].parts.find(
      (p) => p.heading === "Deeper Analysis",
    );
    const groups = (deeper?.items ?? [])
      .filter((i) => i.type === "subheading")
      .map((i) => docItemText(i));
    const order = [
      "Discovery & Qualification",
      "Presentation & Value",
      "Objection / Price / Decision",
      "Communication",
    ];
    expect(groups.length).toBeGreaterThan(0);
    expect(groups).toEqual(order.filter((g) => groups.includes(g)));
  });

  it("today's real pipeline output reads cleanly: no repeated switch quote", () => {
    const doc = reportDocumentModel(
      {
        report: callB.report as unknown as SalesReport,
        transcript: callB.transcript as unknown as Transcript,
      },
      { roles: { seller: "speaker_0", prospect: "speaker_1" } },
    );
    const change = doc.sections[1].parts.find((p) =>
      p.heading?.startsWith("2.3"),
    );
    if (change) {
      const quote = change.items.find((i) => i.type === "quote");
      const texts = change.items
        .filter((i) => i.type === "text")
        .map((i) => docItemText(i));
      if (quote?.type === "quote")
        expect(texts).not.toContain(quote.clip.quote);
    }
    for (const section of doc.sections)
      for (const part of section.parts)
        expect(part.items.length).toBeGreaterThan(0);
  });

  it("someone's own words in Before / After and 'You moved toward' read as quotes", () => {
    const names: Record<string, string> = {
      speaker_0: "Riya",
      speaker_1: "Mr Kulkarni",
    };
    const doc = reportDocumentModel(
      {
        report: callB.report as unknown as SalesReport,
        transcript: callB.transcript as unknown as Transcript,
      },
      {
        roles: { seller: "speaker_0", prospect: "speaker_1" },
        speakerName: (id) => names[id],
      },
    );
    const steps = items(doc).find((i) => i.type === "steps");
    if (steps?.type !== "steps") throw new Error("no Before / After");
    const [before, , after] = steps.steps;
    expect(before.quoted).toBe(true);
    expect(after.quoted).toBe(true);
    expect(Object.values(names)).toContain(before.speaker);
    expect(docItemText(steps)).toContain(`Before: “${before.text}”`);
    const miss = items(doc).find(
      (i) => i.type === "card" && i.kicker?.startsWith("Important Miss"),
    );
    if (miss?.type !== "card") throw new Error("no Important Miss");
    const moved = miss.items.findIndex(
      (i) => i.type === "label" && i.text === MOMENTS.movedToward,
    );
    expect(miss.items[moved + 1]?.type).toBe("quote");
    // Dipak's example: Before / After are summaries, not anyone's words.
    const amit = items(amitDoc()).find((i) => i.type === "steps");
    if (amit?.type !== "steps") throw new Error("no Before / After");
    expect(amit.steps.some((step) => step.quoted)).toBe(false);
  });

  it("a report whose analysis writes the six pillars (v8) fills the whole document", () => {
    const { report, transcript } = v8Report();
    const doc = reportDocumentModel(
      { report, transcript, title: "Qivra Works · discovery call" },
      {
        roles: { seller: "speaker_0", prospect: "speaker_1" },
        speakerName: (id) => ({ speaker_0: "Sela", speaker_1: "Daro" })[id],
      },
    );
    expect(doc.sections).toHaveLength(6);
    expect(doc.sections[0].gaps).toEqual([]);
    const part = (prefix: string) =>
      doc.sections
        .flatMap((s) => s.parts)
        .find((p) => p.heading?.startsWith(prefix));
    // The analysis' own stage names, not Sales Xray's defaults.
    expect(docItemText(part("2.2")!.items[0])).toContain("Work context");
    // A line that stands alone starts with a capital, mid-sentence it doesn't.
    expect(docItemText(part("6.6")!.items[0])).toBe("Next Tuesday");
    expect(docItemText(part("6.7")!.items[0])).toBe(
      "Clear because next Tuesday is agreed.",
    );
    expect(doc.summary?.type === "summary" && doc.summary.cells.at(-1)).toEqual(
      { label: "Next Event", value: "Next Tuesday" },
    );
    // "What was missed" as Dipak sets it: the lead on its own line, then the open point.
    const miss = items(doc).find(
      (i) => i.type === "card" && i.kicker?.startsWith("Important Miss"),
    );
    const lines = miss?.type === "card" ? miss.items.map(docItemText) : [];
    const lead = lines.indexOf("You could have first understood:");
    expect(lead).toBeGreaterThan(lines.indexOf("What was missed"));
    expect(lines[lead + 1]).toBe(
      "The reason for the budget limit remained unclear.",
    );
    expect(textOf(doc)).not.toMatch(
      /\b(undefined|null|NaN|\[object Object\]|inferred|insufficient_evidence|C5)\b/,
    );
  });

  it("a card whose title only repeats its sentence says it once (sandbox reports)", () => {
    const { report, transcript } = v8Report();
    const [first] = report.pillars!.worked!;
    const worked = [
      // The same words twice, and the sentence cut at a title's 48 characters.
      { ...first, title: "Separated evaluation from signing authority" },
      { ...first, title: "Answered a specific scope question with an expli" },
    ];
    worked[0].what = "Separated evaluation from signing authority";
    worked[1].what =
      "Answered a specific scope question with an explicit limit.";
    const doc = reportDocumentModel({
      report: { ...report, pillars: { ...report.pillars!, worked } },
      transcript,
    });
    const cards = doc.sections[2].parts[0].items.filter(
      (item) => item.type === "card",
    );
    expect(cards.map((card) => card.type === "card" && card.title)).toEqual([
      "Separated evaluation from signing authority",
      "Answered a specific scope question with an explicit limit",
    ]);
    const lines = cards.flatMap((card) =>
      card.type === "card" ? card.items.map(docItemText) : [],
    );
    expect(lines.some((line) => line.startsWith("Separated"))).toBe(false);
    expect(lines.some((line) => line.startsWith("Answered"))).toBe(false);
    // A real headline above a different sentence stays as it was.
    const amit = amitDoc().sections[2].parts[0].items[0];
    expect(amit.type === "card" && amit.items[0].type).toBe("text");
  });

  it("Dipak's example as the analysis writes it: price, likely status, Friday", () => {
    const doc = reportDocumentModel(
      {
        report: { ...(amitReport as SalesReport), pillars: AMIT_PILLARS },
        transcript: amitTranscript as Transcript,
      },
      { roles: AMIT_SPEAKERS, speakerName: (id) => NAMES[id] },
    );
    const all = items(doc);
    // "Price stated: ₹2,00,000" is a figure, not somebody's quote.
    const price = all.find(
      (i) => i.type === "card" && i.kicker?.startsWith("Price Moment"),
    );
    const priceItems = price?.type === "card" ? price.items : [];
    const stated =
      priceItems[
        priceItems.findIndex((i) => docItemText(i) === "Price stated") + 1
      ];
    expect(stated).toMatchObject({ type: "text", text: "₹2,00,000" });
    expect(priceItems.filter((i) => i.type === "quote")).toHaveLength(1);
    // Deep analysis: words after a figure keep their case; Likely status listed.
    const deeper = doc.sections[4].parts.find(
      (p) => p.heading === "Deeper Analysis",
    )!;
    const lines = deeper.items.map(docItemText);
    expect(lines).toContain("₹2,00,000 discussed.");
    const likely = lines.indexOf("Likely status");
    expect(likely).toBeGreaterThan(lines.indexOf("Prospect response"));
    expect(lines[likely + 1]).toContain("real stakeholder dependency");
    // A day name keeps its capital inside the sentence.
    const quality = doc.sections[5].parts.find((p) =>
      p.heading?.startsWith("6.7"),
    )!;
    expect(docItemText(quality.items[0])).toBe(
      "Clear because Friday · 4:00 PM is agreed.",
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
    // Said once: "Outcome not set" and eight "Not covered" rows, not again as gaps.
    expect(doc.sections[0].parts[0].items[0]).toMatchObject({
      status: "Outcome not set",
    });
    expect(doc.sections[0].gaps).not.toContain("Call outcome");
    expect(doc.sections[4].gaps).toEqual([]);
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
