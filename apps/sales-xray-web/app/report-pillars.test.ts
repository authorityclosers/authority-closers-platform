import { describe, expect, it } from "vitest";
import { reportPillars, REPORT_PILLARS } from "./report-pillars";
import { syntheticReport } from "./review-fixture/report/synthetic-report";

describe("C5 six-pillar projection", () => {
  it("does not promote legacy outcomes, coaching priorities or actions into deal facts", () => {
    const pillars = reportPillars(syntheticReport);
    expect(pillars.map((p) => p.label)).toEqual(
      REPORT_PILLARS.map((p) => p.label),
    );
    const picture = pillars[0].entries;
    for (const label of [
      "Call outcome",
      "Strongest part",
      "Biggest concern",
      "Next agreed step",
    ])
      expect(picture.find((entry) => entry.label === label)?.gap).toBe(true);
    expect(pillars[5].entries).toHaveLength(9);
    expect(
      pillars[5].entries.every(
        (entry) => entry.gap && entry.evidence.length === 0,
      ),
    ).toBe(true);
    const content = JSON.stringify(pillars);
    expect(content).not.toContain(
      syntheticReport.overview!.next_call_focus!.behavior,
    );
    expect(content).not.toContain(
      syntheticReport.overview!.practice!.instructions,
    );
  });

  it("keeps the exact supplied evidence and qualifies interpretations", () => {
    const pillars = reportPillars(syntheticReport);
    const worked = pillars[2].entries.find((entry) =>
      entry.label.startsWith("What worked"),
    )!;
    expect(worked.evidence).toEqual(syntheticReport.strengths[0].evidence);
    const effects = pillars
      .flatMap((p) => p.entries)
      .filter((e) => /Possible|may have/.test(e.label));
    expect(effects.length).toBeGreaterThan(0);
    expect(effects.every((e) => e.hypothesis)).toBe(true);
    expect(pillars[4].entries).toHaveLength(8);
  });

  it("does not fill a moments quota or assert missed chances from a legacy finding", () => {
    const report = {
      ...syntheticReport,
      missed_opportunities: [
        {
          title: "Unverified miss",
          explanation: "Not proof of an opportunity",
          evidence: syntheticReport.strengths[0].evidence,
        },
      ],
    };
    const moments = reportPillars(report)[3].entries;
    expect(
      moments.some((entry) => entry.label.includes("Unverified miss")),
    ).toBe(false);
    expect(moments.find((entry) => entry.label === "Missed chances")?.gap).toBe(
      true,
    );
    const empty = reportPillars({
      ...report,
      overview: undefined,
      strengths: [],
    });
    expect(empty[3].entries.every((entry) => entry.gap)).toBe(true);
    expect(
      empty[1].entries.find((entry) => entry.label === "Conversation timeline")
        ?.gap,
    ).toBe(true);
  });

  it("does not label evidence-free observed or legacy partial skills as positive assessments", () => {
    const report = {
      ...syntheticReport,
      dimensions: syntheticReport.dimensions.map((d) => ({
        ...d,
        status: "partial",
        evidence: [],
      })),
    };
    expect(reportPillars(report)[4].entries.every((entry) => entry.gap)).toBe(
      true,
    );
    const observed = {
      ...report,
      dimensions: report.dimensions.map((d) => ({ ...d, status: "observed" })),
    };
    expect(reportPillars(observed)[4].entries.every((entry) => entry.gap)).toBe(
      true,
    );
  });
});
