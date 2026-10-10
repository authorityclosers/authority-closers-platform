import { describe, expect, it } from "vitest";
import { parseReportStory } from "./report-story";
import type { Transcript } from "./report-contract";
import { reportPillars } from "./report-pillars";
import { syntheticReport } from "./review-fixture/report/synthetic-report";

const transcript: Transcript = {
  source_sha256: "0".repeat(64),
  revision: "fictional-1",
  timebase_id: "1ms",
  duration_ms: 10000,
  segments: [
    {
      id: "s1",
      speaker_id: "buyer",
      text: "Let's talk Friday at four.",
      start_ms: 1000,
      end_ms: 4000,
    },
  ],
};
const refs = [{ segment_id: "s1", quote: "Let's talk Friday at four." }];
const wire = () => ({
  version: "report-story/1",
  phases: [
    { name: "opening", start_ms: 0 },
    { name: "discovery", start_ms: 1000 },
    { name: "pitch", start_ms: 4000 },
    { name: "discovery", start_ms: 5000 },
  ],
  outcome: {
    kind: "follow_up",
    next_step_rung: "dated_call",
    next_step_when: "Friday at four",
    evidence: refs,
  },
  next_step: { text: "Talk on Friday", evidence: refs },
  prospect_commitments: [
    { text: "Talk on Friday", effort_ms: null, evidence: refs },
  ],
  seller_commitments: [],
});

describe("Report story source binding", () => {
  it("opens a privacy-withheld report with dependent dates and commitments unavailable", () => {
    const marker = "[Withheld for privacy]";
    const candidate = wire();
    const redactedRefs = [{ segment_id: "s1", quote: marker }];
    candidate.outcome.evidence = redactedRefs;
    candidate.next_step.evidence = redactedRefs;
    candidate.prospect_commitments[0].evidence = redactedRefs;
    const source = {
      ...transcript,
      segments: transcript.segments.map((s) => ({ ...s, text: marker })),
    };
    const story = parseReportStory(candidate, source);
    expect(story.outcome).toMatchObject({
      kind: "none",
      next_step_rung: "none",
      next_step_when: null,
    });
    expect(story.next_step).toBeNull();
    expect(story.prospect_commitments).toEqual([]);
    expect(() => parseReportStory(candidate, transcript)).toThrow();
  });
  it("resolves native timing, keeps literal dates and preserves a return to discovery", () => {
    const story = parseReportStory(wire(), transcript);
    expect(story.outcome.next_step_when).toBe("Friday at four");
    expect(story.next_step?.evidence[0]).toEqual({
      ...refs[0],
      start_ms: 1000,
      end_ms: 4000,
    });
    const pillars = reportPillars(
      { ...syntheticReport, story },
      transcript.duration_ms,
    );
    expect(pillars[0].entries[0].text).toBe("Follow-up Set");
    expect(pillars[1].timeline?.map((p) => p.label)).toEqual([
      "Opening",
      "Discovery",
      "Offer discussion",
      "Discovery",
    ]);
    expect(
      pillars[5].entries.find((e) => e.label === "Prospect commitment")?.text,
    ).toBe("Talk on Friday");
    expect(
      pillars[5].entries.find((e) => e.label === "Seller commitment")?.gap,
    ).toBe(true);
    expect(
      pillars[5].entries.find((e) => e.label === "Commitment quality")?.gap,
    ).toBe(true);
  });

  it.each([
    (w: ReturnType<typeof wire>) => {
      w.outcome.evidence = [{ segment_id: "unknown", quote: "Friday" }];
    },
    (w: ReturnType<typeof wire>) => {
      w.outcome.evidence = [{ segment_id: "s1", quote: "Invented quote" }];
    },
    (w: ReturnType<typeof wire>) => {
      w.outcome.evidence = [];
    },
    (w: ReturnType<typeof wire>) => {
      w.outcome.next_step_when = "2026-10-16T16:00:00Z";
    },
    (w: ReturnType<typeof wire>) => {
      w.phases[1].start_ms = 10000;
    },
    (w: ReturnType<typeof wire>) => {
      w.phases[1].start_ms = 0;
    },
  ])(
    "rejects unbound evidence, repaired dates or invalid phases (%#)",
    (mutate) => {
      const candidate = wire();
      mutate(candidate);
      expect(() => parseReportStory(candidate, transcript)).toThrow(
        "report_story_invalid",
      );
    },
  );

  it("does not infer an outcome from an empty map outcome", () => {
    const candidate = {
      ...wire(),
      next_step: null,
      outcome: {
        kind: "none",
        next_step_rung: "none",
        next_step_when: null,
        evidence: [],
      },
    };
    const story = parseReportStory(candidate, transcript);
    expect(reportPillars({ ...syntheticReport, story })[0].entries[0].gap).toBe(
      true,
    );
  });
});
