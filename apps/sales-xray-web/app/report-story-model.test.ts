import { describe, expect, it } from "vitest";

import type { SalesReport, Transcript } from "./report-contract";
import { callOutcome, reportStoryModel } from "./report-story-model";
import {
  AMIT_SPEAKERS,
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import { syntheticReport } from "./review-fixture/report/synthetic-report";
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
    // The improvement the analysis asked to fix first is the biggest concern.
    expect(model.picture.concern?.text).toBe(
      amitReport.improvements[0].explanation,
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
    const miss = model.moments.find((m) => m.kind === "Important Miss");
    expect(miss?.source.quote).toContain("my team doesn't close");
    expect(miss?.movedToward?.text).toBe(
      "Explaining sales systems and training.",
    );
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
  });
});

describe("honest gaps", () => {
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
    expect(sparse.missing[0]).toContain("Call outcome");
    expect(sparse.flow.metrics).toEqual([]);
    expect(sparse.flow.phases).toBeNull();
    expect(sparse.skills).toHaveLength(8);
    expect(sparse.skills.filter((s) => s.state === null).length).toBe(
      sparse.missing[4].length,
    );
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
    expect(miss?.movedToward?.quoted).toBe(true);
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
    expect(model.picture.concern?.sources).toHaveLength(1);
    expect(model.picture.nextStep?.text).toBe(report.overview!.outcome!.text);
    expect(model.missing[0]).toEqual([]);
  });

  it("says plainly what the older format lacks", () => {
    expect(model.flow.phases).toBeNull();
    expect(model.missing[1]).toContain("Conversation timeline");
    expect(model.deal.quality).toBeNull();
    expect(model.missing[5]).toContain("Commitment quality");
    expect(model.skills.every((skill) => skill.state === "Observed")).toBe(
      true,
    );
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
