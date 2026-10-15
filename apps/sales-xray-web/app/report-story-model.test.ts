import { describe, expect, it } from "vitest";

import type { SalesReport, Transcript } from "./report-contract";
import { callOutcome, reportStoryModel } from "./report-story-model";
import {
  AMIT_SPEAKERS,
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import { syntheticReport } from "./review-fixture/report/synthetic-report";
import {
  contentFixture,
  contentReport,
} from "./review-fixture/report/pillars/content-fixture";
import callB from "./review-fixture/report/story/fictional-call-b.json";

const withOutcome = (
  kind: string,
  report: SalesReport = amitReport,
): SalesReport => ({
  ...report,
  story: undefined,
  overview: {
    ...report.overview!,
    outcome: { ...report.overview!.outcome!, kind } as never,
  },
});

describe("reportStoryModel", () => {
  const model = reportStoryModel(amitReport, amitTranscript, {
    roles: AMIT_SPEAKERS,
  });

  it("opens with one outcome, summary, influence, strongest part, concern and next step", () => {
    expect(model.picture.outcome).toMatchObject({
      status: "Follow-up Set",
      origin: "call",
    });
    expect(model.picture.summary?.text).toBe(amitReport.summary);
    expect(model.picture.influence?.text).toBe(
      amitReport.overview!.diagnosis!.text,
    );
    expect(model.picture.strongest?.text).toBe(
      amitReport.strengths[0].explanation,
    );
    // The Report uses the separate observation, keeping the coaching instruction out.
    expect(model.picture.concern?.text).toBe(
      amitReport.overview!.improvement_details[0].what_happened.text,
    );
    expect(model.picture.nextStep?.text).toBe(
      amitReport.story!.next_step!.text,
    );
    expect(model.missing[0]).toEqual([]);
  });

  it("measures the call without judging it", () => {
    const labels = model.flow.metrics.map((m) => m.label);
    expect(labels).toEqual([
      "Call length",
      "Talk share",
      "Questions asked",
      "Longest seller turn",
      "Talk-overs",
    ]);
    expect(model.flow.metrics[0].value).toBe("25:08");
    expect(model.flow.metrics[1].note).toBe("You : Prospect");
    expect(model.flow.phases?.at(-1)?.end_ms).toBe(amitTranscript.duration_ms);
    expect(model.flow.change?.turn.sources[0].start_ms).toBe(678_000);
  });

  it("keeps at most five strengths and three issues, each with its source", () => {
    expect(model.worked).toHaveLength(3);
    expect(model.didnt).toHaveLength(3);
    for (const item of [...model.worked, ...model.didnt])
      expect(item.what.sources.length).toBe(1);
    expect(model.didnt[0].why?.text).toBe(
      amitReport.overview!.improvement_details[0].why_it_matters,
    );
  });

  it("picks at most five key moments, in call order, without duplicates", () => {
    expect(model.topMoments.length).toBeLessThanOrEqual(5);
    const times = model.topMoments.map((m) => m.source.start_ms);
    expect(times).toEqual([...times].sort((a, b) => a - b));
    expect(new Set(model.moments.map((m) => m.key)).size).toBe(
      model.moments.length,
    );
    expect(model.moments.some((m) => m.kind === "Important Miss")).toBe(false);
    expect(model.topMoments.map((m) => m.kind)).toContain("Turning Point");
  });

  it("shows all eight skills with the five call states", () => {
    expect(model.skills).toHaveLength(8);
    expect(model.skills.map((s) => s.state)).toEqual([
      "Strongly Demonstrated",
      "Needs Attention",
      "Observed",
      "Observed",
      "Observed",
      "Observed",
      "Strongly Demonstrated",
      "Observed",
    ]);
  });

  it("closes with the deal's position, commitments, next event and open questions", () => {
    expect(model.deal.quality).toBe("Clear");
    expect(model.deal.nextEvent?.text).toBe("Friday · 4:00 PM");
    expect(model.deal.prospectCommitments).toHaveLength(1);
    expect(model.deal.sellerCommitments[0].text).toBe(
      "Send the program summary and a relevant case study · today",
    );
    expect(model.deal.blocker?.inferred).toBe(true);
    expect(model.deal.unclear).toHaveLength(4);
    expect(model.deal.action).toBe(
      amitReport.overview!.final_assessment.next_focus,
    );
    expect(model.deal.position).toBeNull();
  });
});

describe("honest gaps", () => {
  it("keeps an older report's saved deal recommendation without restoring gated misses", () => {
    const model = reportStoryModel(syntheticReport);
    expect(model.deal.action).toBe(
      "Respect the buyer's request not to follow up.",
    );
    expect(model.deal.coachingMission).toBe(
      syntheticReport.overview!.next_call_focus?.behavior,
    );
    expect(
      model.moments.some((moment) => moment.kind === "Important Miss"),
    ).toBe(false);
    expect(
      reportStoryModel({ ...syntheticReport, overview: undefined }).deal.action,
    ).toBeNull();
    expect(
      reportStoryModel({
        ...syntheticReport,
        overview: {
          ...syntheticReport.overview!,
          final_assessment: {
            ...syntheticReport.overview!.final_assessment,
            next_focus: "   ",
          },
        },
      }).deal.action,
    ).toBeNull();
  });

  it.each([contentFixture.action, null])(
    "lets validated content own the deal action, including an absent recommendation: %j",
    (action) => {
      const model = reportStoryModel({
        ...contentReport,
        overview: syntheticReport.overview,
        report_content: { ...contentFixture, action },
      });
      expect(model.deal.action).toBe(action?.text ?? null);
      expect(model.deal.action).not.toBe(
        syntheticReport.overview!.final_assessment.next_focus,
      );
      expect(model.deal.coachingMission).toBeNull();
    },
  );

  it("keeps a matching pillar summary's citations without lending them to other words", () => {
    expect(amitReport.summary_evidence?.length).toBeGreaterThan(0);
    const matching = reportStoryModel(
      {
        ...amitReport,
        pillars: { version: "report-pillars/1", summary: amitReport.summary },
      },
      amitTranscript,
    );
    expect(matching.picture.summary).toEqual({
      text: amitReport.summary,
      sources: amitReport.summary_evidence,
    });
    const unrelated = reportStoryModel(
      {
        ...amitReport,
        pillars: {
          version: "report-pillars/1",
          summary: "A different saved summary without its own citations.",
        },
      },
      amitTranscript,
    );
    expect(unrelated.picture.summary).toEqual({
      text: "A different saved summary without its own citations.",
      sources: [],
    });
  });

  it.each([false, true])(
    "does not turn an assigned task into an agreed commitment (pillars: %s)",
    (pillars) => {
      const report: SalesReport = {
        ...amitReport,
        pillars: pillars ? { version: "report-pillars/1" } : undefined,
        story: {
          ...amitReport.story!,
          prospect_commitments: [],
          prospect_tasks: [amitReport.story!.prospect_commitments[0]],
        },
      };
      const model = reportStoryModel(report, amitTranscript);
      expect(model.deal.prospectCommitments).toEqual([]);
      expect(model.missing[5]).toContain("Prospect commitment");
      expect(report.story!.prospect_tasks).toHaveLength(1);
    },
  );

  it("never turns the analysis into Won or Lost", () => {
    expect(callOutcome(withOutcome("closed")).status).toBeNull();
    expect(callOutcome(withOutcome("no_sale")).status).toBeNull();
    expect(callOutcome(withOutcome("future_date")).status).toBe("Deferred");
    expect(callOutcome(withOutcome("unclear")).status).toBe(
      "No Clear Next Step",
    );
    const story = {
      ...amitReport,
      story: {
        ...amitReport.story!,
        outcome: { ...amitReport.story!.outcome, kind: "won" as const },
      },
      overview: { ...amitReport.overview!, outcome: null },
    } satisfies SalesReport;
    expect(callOutcome(story).status).toBeNull();
  });

  it("lets a person's recorded outcome win", () => {
    expect(
      callOutcome(withOutcome("closed"), { status: "Won", note: "Signed" }),
    ).toMatchObject({ status: "Won", origin: "person" });
  });

  it("opens an older, sparse report and lists what it lacks instead of inventing it", () => {
    const sparse = reportStoryModel(syntheticReport);
    expect(sparse.picture.outcome.status).toBeNull();
    // The badge says the outcome isn't set; the gap line doesn't repeat it.
    expect(sparse.missing[0]).not.toContain("Call outcome");
    expect(sparse.flow.metrics).toEqual([]);
    expect(sparse.flow.phases).toBeNull();
    expect(sparse.skills).toHaveLength(8);
    // Each row says "Not covered" itself; no second list of names.
    expect(sparse.skills.some((s) => s.state === null)).toBe(true);
    expect(sparse.missing[4]).toEqual([]);
    expect(sparse.deal.nextEvent).toBeNull();
    expect(sparse.missing[5]).toContain("Next event");
  });

  it("opens a report with no overview or story at all", () => {
    const bare = {
      ...syntheticReport,
      overview: undefined,
      story: undefined,
      strengths: [],
      improvements: [],
      dimensions: [],
    } as SalesReport;
    const model = reportStoryModel(bare);
    expect(model.picture.summary?.text).toBe(bare.summary);
    expect(model.worked).toEqual([]);
    expect(model.moments).toEqual([]);
    expect(model.missing[3]).toEqual(["Moments"]);
  });
});

describe("today's real pipeline output (corpus call B, invented script)", () => {
  const report = callB.report as unknown as SalesReport;
  const transcript = callB.transcript as unknown as Transcript;
  const model = reportStoryModel(report, transcript, {
    roles: { seller: "speaker_0", prospect: "speaker_1" },
  });

  it("marks lines that are someone's own words, so they read as speech", () => {
    expect(model.flow.change?.before.quoted).toBe(true);
    expect(model.flow.change?.after.quoted).toBe(true);
    const miss = model.moments.find((m) => m.kind === "Important Miss");
    expect(miss).toBeUndefined();
    // The spec example's before/after are summaries, not quotes.
    const amit = reportStoryModel(amitReport, amitTranscript);
    expect(amit.flow.change?.before.quoted).toBeUndefined();
  });

  it("shows one summary when the final assessment only restates it", () => {
    expect(report.overview?.final_assessment.assessment).toBeTruthy();
    expect(model.picture.summary?.text).toBe(report.summary);
    expect(model.picture.assessment).toBeNull();
    // The spec example's second paragraph adds to the first, so it stays.
    expect(
      reportStoryModel(amitReport, amitTranscript).picture.assessment,
    ).toBeTruthy();
  });

  it("fills the Big Picture from the overview it already has", () => {
    expect(model.picture.outcome).toMatchObject({
      status: "Follow-up Set",
      origin: "call",
    });
    expect(model.picture.influence?.sources.length).toBeGreaterThan(0);
    expect(model.picture.strongest?.sources).toHaveLength(1);
    expect(model.picture.concern?.sources.length).toBeGreaterThan(0);
    expect(model.picture.nextStep?.text).toBe(report.overview!.outcome!.text);
    expect(model.missing[0]).toEqual([]);
  });

  it("says plainly what the older format lacks", () => {
    expect(model.flow.phases).toBeNull();
    expect(model.missing[1]).toContain("Call stages");
    expect(model.deal.quality).toBeNull();
    expect(model.missing[5]).toContain("Commitment quality");
    expect(model.skills.every((skill) => skill.state === null)).toBe(true);
    expect(model.deal.nextEvent?.text).toBe(report.overview!.outcome!.text);
    expect(model.topMoments.length).toBeGreaterThan(0);
  });
});

describe("never breaks on a malformed older report", () => {
  it("opens with missing lists, findings without evidence and a bare overview", () => {
    const broken = {
      summary: "Only a summary survived.",
      strengths: [{ title: "Kept going", explanation: "Steady." }],
      overview: { outcome: null },
      dimensions: undefined,
    } as unknown as SalesReport;
    const model = reportStoryModel(broken);
    expect(model.picture.summary?.text).toBe("Only a summary survived.");
    expect(model.picture.strongest).toBeNull();
    expect(model.worked[0].what.sources).toEqual([]);
    expect(model.skills).toHaveLength(8);
    expect(model.missing[0]).toContain("Strongest part");
  });
});

describe("Sandbox-style findings and prices (G's findings, 11 Oct)", () => {
  it("shows a title that only repeats its sentence as the sentence, once", () => {
    const what = amitReport.strengths[0].explanation;
    const report: SalesReport = {
      ...amitReport,
      strengths: [
        { ...amitReport.strengths[0], title: what.slice(0, 30) },
        ...amitReport.strengths.slice(1),
      ],
    };
    const model = reportStoryModel(report, amitTranscript);
    expect(model.worked[0]).toMatchObject({
      sentence: true,
      title: what.replace(/\.$/, ""),
    });
    // Real headlines are untouched.
    expect(model.worked[1].sentence).toBeUndefined();
  });

  const withLines = (lines: Record<string, string>): Transcript =>
    ({
      ...amitTranscript,
      segments: amitTranscript.segments.map((segment) =>
        lines[segment.id] ? { ...segment, text: lines[segment.id] } : segment,
      ),
    }) as Transcript;

  it("takes the price from the seller's words and the reply from the prospect", () => {
    const transcript = withLines({
      a27: "What is the price? Our budget is about one lakh.",
      a28: "The price is two lakh rupees for the full twelve weeks.",
    });
    const report = { ...amitReport };
    const model = reportStoryModel(report, transcript, {
      roles: AMIT_SPEAKERS,
    });
    const price = model.moments.find((m) => m.kind === "Price Moment");
    expect(price?.priceStated?.text).toContain("two lakh");
    expect(price?.prospectResponse?.text).toContain(
      "discuss this with my partner",
    );
  });

  it("never shows the prospect's own budget as the price stated", () => {
    const transcript = withLines({
      a27: "Our budget is about one lakh, what does this cost?",
      a28: "Let me first explain what the program includes.",
    });
    const model = reportStoryModel(amitReport, transcript, {
      roles: AMIT_SPEAKERS,
    });
    expect(model.moments.some((m) => m.kind === "Price Moment")).toBe(false);
  });

  it("claims no 'Price stated' when nobody knows who said what", () => {
    const transcript = withLines({
      a27: "What is the price? Our budget is about one lakh.",
      a28: "The price is two lakh rupees for the full twelve weeks.",
    });
    const price = reportStoryModel(amitReport, transcript).moments.find(
      (m) => m.kind === "Price Moment",
    );
    expect(price?.source.segment_id).toBe("a27");
    expect(price?.priceStated).toBeUndefined();
    expect(price?.prospectResponse).toBeUndefined();
  });
});

it("shows a skill's state and evidence without a placeholder note (C's Sandbox data)", () => {
  const stock = "Relevant behaviour is evidenced by the cited turn.";
  const report: SalesReport = {
    ...amitReport,
    dimensions: amitReport.dimensions.map((d) => ({
      ...d,
      observation: stock,
    })),
  };
  const model = reportStoryModel(report, amitTranscript);
  const communication = model.skills.find(
    (s) => s.id === "communication_tonality",
  );
  expect(communication?.state).toBeTruthy();
  expect(communication?.observation).toBeNull();
  expect(communication?.sources.length).toBeGreaterThan(0);
  expect(model.deeper.communication.observation).toBeNull();
});

it("puts a person's outcome first, without the call's contradicting line", () => {
  const won = reportStoryModel(amitReport, amitTranscript, {
    recorded: { status: "Won" },
  });
  expect(won.picture.outcome).toMatchObject({
    status: "Won",
    origin: "person",
    detail: null,
  });
  // Where the prospect stands still reads what the call heard.
  expect(won.deal.position?.text).toBe(amitReport.overview!.outcome!.text);
  const lost = reportStoryModel(amitReport, amitTranscript, {
    recorded: { status: "Lost", note: "Chose another program." },
  });
  expect(lost.picture.outcome.detail?.text).toBe("Chose another program.");
});
