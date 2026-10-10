import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { syntheticReport } from "./review-fixture/report/synthetic-report";
import { callCoachingFocus, ReportCallCoaching } from "./report-call-coaching";

it("keeps the retained focus, source and mission together without a new assessment", () => {
  const focus = callCoachingFocus(syntheticReport)!;
  expect(focus.finding).toBe(syntheticReport.improvements[0]);
  expect(focus.behavior).toBe(
    syntheticReport.overview!.next_call_focus!.behavior,
  );
  expect(focus.target).toBe(syntheticReport.overview!.next_call_focus!.target);
  expect(focus.replacement).toBe(
    syntheticReport.overview!.improvement_details[0].replacement_behavior,
  );
});

it("opens legacy sourced findings without an overview or assessed skill", () => {
  const report = { ...syntheticReport, overview: undefined, dimensions: [] };
  const focus = callCoachingFocus(report)!;
  expect(focus.behavior).toBe(report.improvements[0].title);
  expect(focus.finding.evidence).toEqual(report.improvements[0].evidence);
  expect(focus.skillId).toBeNull();
  expect(focus.target).toBeNull();
  const html = renderToStaticMarkup(<ReportCallCoaching data={{ report }} />);
  expect(html).toContain(report.improvements[0].explanation);
  expect(html).toContain("Your next-call mission");
  expect(html).not.toContain("Not Enough Evidence");
});

it("withholds an unsupported preferred focus and its wording and practice", () => {
  const report = structuredClone(syntheticReport);
  report.improvements[0].evidence = [];
  report.strengths = [];
  const index = report.improvements.findIndex(
    (finding) => finding.evidence.length,
  );
  const focus = callCoachingFocus(report);
  if (index < 0) expect(focus).toBeNull();
  else {
    expect(focus!.finding).toBe(report.improvements[index]);
    expect(focus!.target).toBeNull();
    expect(focus!.practice).toBeNull();
  }
});

it("does not invent a deficit when only a strength has source evidence", () => {
  const report = { ...syntheticReport, improvements: [], overview: undefined };
  const focus = callCoachingFocus(report)!;
  expect(focus.improvement).toBe(false);
  expect(focus.finding).toBe(
    report.strengths.find((finding) => finding.evidence.length),
  );
  expect(focus.replacement).toBeNull();
  expect(
    renderToStaticMarkup(<ReportCallCoaching data={{ report }} />),
  ).toContain("Keep doing");
});

it("requires a unique exact source association before suggesting a skill", () => {
  const report = structuredClone(syntheticReport);
  const source = report.improvements[0].evidence[0];
  report.dimensions = [
    {
      ...report.dimensions[0],
      dimension_id: "qualification",
      status: "observed",
      evidence: [source],
    },
  ];
  expect(callCoachingFocus(report)!.skillId).toBe("qualification");
  report.dimensions.push({
    ...report.dimensions[0],
    dimension_id: "human_connection_trust",
  });
  expect(callCoachingFocus(report)!.skillId).toBeNull();
  report.dimensions = [
    {
      ...report.dimensions[0],
      evidence: [{ ...source, quote: "Different words" }],
    },
  ];
  expect(callCoachingFocus(report)!.skillId).toBeNull();
});

it("offers explicit skill choices when the report has no supported focus", () => {
  const report = {
    ...syntheticReport,
    improvements: [],
    strengths: [],
    overview: undefined,
  };
  const html = renderToStaticMarkup(<ReportCallCoaching data={{ report }} />);
  expect(callCoachingFocus(report)).toBeNull();
  expect(html).toContain("Choose a skill to work on below");
  expect(html.match(/href="\/coaching\?focus=/g)).toHaveLength(8);
  expect(html).not.toContain("Your next-call mission");
});

it("never derives full coaching from a partial guest projection", () => {
  const report = {
    ...syntheticReport,
    preview: { version: "guest-findings-v1" } as NonNullable<
      typeof syntheticReport.preview
    >,
  };
  expect(callCoachingFocus(report)).toBeNull();
  expect(renderToStaticMarkup(<ReportCallCoaching data={{ report }} />)).toBe(
    "",
  );
});
