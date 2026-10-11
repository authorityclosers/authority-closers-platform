import { describe, expect, it } from "vitest";

import type { ReportEvidence } from "./report-contract";
import { parseReportPillars } from "./report-pillars-contract";
import { reportStoryModel } from "./report-story-model";
import {
  AMIT_SPEAKERS,
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";

const segments = new Map(amitTranscript.segments.map((s) => [s.id, s]));
/** The report's strict check in miniature: the quote must be in the segment. */
const evidence = (value: unknown): ReportEvidence => {
  const ref = value as ReportEvidence;
  const segment = segments.get(ref?.segment_id);
  if (!segment || !segment.text.includes(ref.quote))
    throw new Error("evidence_invalid");
  return {
    segment_id: segment.id,
    quote: ref.quote,
    start_ms: segment.start_ms,
    end_ms: segment.end_ms,
  };
};
const ref = (n: number) => {
  const segment = amitTranscript.segments[n];
  return {
    segment_id: segment.id,
    quote: segment.text.slice(0, 24),
    start_ms: segment.start_ms,
    end_ms: segment.end_ms,
  };
};

const PILLARS = {
  version: "report-pillars/1",
  outcome: {
    status: "Decision Pending",
    line: "Amit is interested but wants to talk to his partner first.",
    evidence: [ref(33)],
  },
  summary:
    "You understood Amit's goal. You explained the program well. He will speak to his partner.",
  strongest_part: {
    text: "You tied the program to his goal.",
    evidence: [ref(25)],
    short: "Value tied to his goal",
  },
  biggest_concern: {
    text: "You explained before diagnosing.",
    evidence: [ref(15)],
    short: "Root problem only partly diagnosed",
  },
  next_step: {
    text: "Amit talks to his partner.",
    evidence: [ref(34)],
    when: "Friday · 4:00 PM",
  },
  timeline: [
    { label: "Opening", start_ms: 0 },
    { label: "Business Context", start_ms: 150_000 },
    { label: "Price & Decision", start_ms: 1_125_000 },
  ],
  didnt: [
    {
      title: "The root sales problem remained unclear",
      what: "You did not find out why the team struggles without him.",
      evidence: [ref(15)],
      what_it_affected: "You presented with a partial diagnosis.",
      possible_areas: ["weak closing", "bad lead quality"],
    },
  ],
  moments: [
    {
      kind: "Buying Signal",
      title: "Amit asked about implementation",
      evidence: [ref(33)],
      why: "He was picturing the work.",
    },
    { kind: "Worth Replaying", title: "Not a spec kind", evidence: [ref(10)] },
    {
      kind: "Risk",
      title: "No quote here",
      evidence: [{ segment_id: "nope", quote: "x" }],
    },
  ],
  deal: {
    position: { text: "Interested, not committed.", evidence: [] },
    blocker: {
      text: "Partner discussion first.",
      evidence: [ref(31)],
      basis: "said",
    },
    prospect_commitments: [
      { text: "Talk to his partner before Friday.", evidence: [ref(34)] },
    ],
    seller_commitments: [],
    next_event: {
      text: "Follow-up call",
      when: "Friday · 4:00 PM",
      evidence: [ref(34)],
    },
    commitment_quality: "Clear",
    still_unclear: ["Is partner approval required?"],
    deal_action: "First ask what the partner said.",
    coaching_mission: "Diagnose one level deeper.",
  },
  most_important_moment: 0,
};

describe("parseReportPillars", () => {
  it("keeps what checks out and drops only the parts that don't", () => {
    const pillars = parseReportPillars(PILLARS, evidence)!;
    expect(pillars.outcome?.status).toBe("Decision Pending");
    expect(pillars.timeline?.map((s) => s.label)).toEqual([
      "Opening",
      "Business Context",
      "Price & Decision",
    ]);
    // Not a spec kind, and a quote that is not in the call: both left out.
    expect(pillars.moments?.map((m) => m.kind)).toEqual(["Buying Signal"]);
    expect(pillars.deal?.blocker?.basis).toBe("said");
  });

  it("never takes Won or Lost from the analysis", () => {
    const pillars = parseReportPillars(
      { ...PILLARS, outcome: { status: "Won", line: "Closed", evidence: [] } },
      evidence,
    )!;
    expect(pillars.outcome).toBeUndefined();
    expect(pillars.summary).toBeDefined();
  });

  it("ignores another version or a malformed envelope", () => {
    expect(
      parseReportPillars({ ...PILLARS, version: "x" }, evidence),
    ).toBeUndefined();
    expect(parseReportPillars("pillars", evidence)).toBeUndefined();
    expect(
      parseReportPillars({ version: "report-pillars/1", deal: 7 }, evidence),
    ).toEqual({
      version: "report-pillars/1",
    });
  });
});

describe("reportStoryModel with pillars", () => {
  const pillars = parseReportPillars(PILLARS, evidence)!;
  const model = reportStoryModel({ ...amitReport, pillars }, amitTranscript, {
    roles: AMIT_SPEAKERS,
  });

  it("reads the analysis' own pillar words first", () => {
    expect(model.picture.outcome.status).toBe("Decision Pending");
    expect(model.picture.summary?.text).toBe(PILLARS.summary);
    expect(model.picture.assessment).toBeNull();
    expect(model.flow.phases?.map((p) => p.label)).toEqual([
      "Opening",
      "Business Context",
      "Price & Decision",
    ]);
    expect(model.didnt[0].areas).toEqual(["weak closing", "bad lead quality"]);
    expect(model.topMoments.map((m) => m.kind)).toEqual(["Buying Signal"]);
    expect(model.deal.blocker?.inferred).toBeUndefined();
    expect(model.deal.nextEvent?.text).toBe("Friday · 4:00 PM");
    expect(model.end).toMatchObject({
      strongest: "Value tied to his goal",
      issue: "Root problem only partly diagnosed",
      nextEvent: "Friday · 4:00 PM",
    });
  });

  it("keeps the derived value for any part the pillars leave out", () => {
    const derived = reportStoryModel(amitReport, amitTranscript, {
      roles: AMIT_SPEAKERS,
    });
    expect(model.picture.influence).toEqual(derived.picture.influence);
    expect(model.worked).toEqual(derived.worked);
    expect(model.skills).toEqual(derived.skills);
  });

  it("lets a person's recorded outcome win over the analysis", () => {
    const recorded = reportStoryModel(
      { ...amitReport, pillars },
      amitTranscript,
      {
        recorded: { status: "Won" },
      },
    );
    expect(recorded.picture.outcome).toMatchObject({
      status: "Won",
      origin: "person",
    });
  });
});
