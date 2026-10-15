import { describe, expect, it } from "vitest";

import { prospectBrief } from "./prospect-brief-model";
import { latestAnalysedCall } from "./prospect-latest-call";
import {
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import {
  AMIT_CALL_ID,
  AMIT_SPEAKERS,
  amitCalls,
  amitProspect,
} from "./review-fixture/prospects/amit-prospect";
import { syntheticProspect } from "./review-fixture/prospects/synthetic-prospect";

const latest = {
  callId: AMIT_CALL_ID,
  report: amitReport,
  transcript: amitTranscript,
  roles: AMIT_SPEAKERS,
};

const labels = (section: { facts: { label: string }[] }) =>
  section.facts.map((fact) => fact.label);

describe("prospectBrief", () => {
  const brief = prospectBrief(amitProspect, amitCalls, latest);

  it("briefs the next call first: who, problem, blocker, decision-maker, stage, next step and follow-up", () => {
    const now = brief.sections[0];
    expect(labels(now)).toEqual([
      "Name",
      "Role",
      "Company",
      "Main problem",
      "Current blocker",
      "Decision-maker",
      "Deal stage",
      "Next step",
      "Follow-up",
      "Who acts next",
      "Biggest unanswered question",
    ]);
    const fact = (label: string) =>
      now.facts.find((item) => item.label === label)!;
    expect(fact("Role")).toMatchObject({ value: "Founder", basis: "person" });
    expect(fact("Current blocker").fact).toBe("Inferred");
    expect(fact("Follow-up").value).toBe("Friday · 4:00 PM");
    expect(fact("Deal stage").value).toBe("Follow-up Set");
    expect(fact("Who acts next").value).toBe("Both: you and the prospect");
    // Fit, urgency and the main goal are never guessed.
    expect(now.unknown.map((item) => item.label)).toEqual([
      "Main goal",
      "Fit",
      "Urgency",
    ]);
  });

  it("keeps heard values with their quote and call", () => {
    const pain = brief.sections[0].facts.find(
      (item) => item.label === "Main problem",
    )!;
    expect(pain.fact).toBe("Observed");
    expect(pain.basis).toBe("call");
    expect(pain.source).toMatchObject({
      callId: AMIT_CALL_ID,
      quote: amitTranscript.segments[13].text,
    });
  });

  it("quotes the prospect's own words only with confirmed speaker roles", () => {
    const words = brief.sections[1].facts.find(
      (item) => item.label === "In their own words",
    );
    expect(words?.list?.length).toBeGreaterThan(0);
    expect(
      words?.list?.every((text) =>
        amitTranscript.segments.some(
          (segment) =>
            segment.text === text &&
            segment.speaker_id === AMIT_SPEAKERS.prospect,
        ),
      ),
    ).toBe(true);
    const unconfirmed = prospectBrief(amitProspect, amitCalls, {
      ...latest,
      roles: undefined,
    });
    expect(
      unconfirmed.sections[1].facts.some(
        (item) => item.label === "In their own words",
      ),
    ).toBe(false);
  });

  it("shows each value once and names qualification gaps instead of scoring", () => {
    const buy = brief.sections[2];
    expect(labels(buy)).toEqual([]);
    expect(buy.unknown.map((item) => item.label)).toEqual([
      "Need",
      "Desire",
      "Budget discussed",
      "Willingness to invest",
      "Urgency",
      "Timing",
      "Fit",
      "Implementation readiness",
    ]);
    expect(JSON.stringify(brief)).not.toMatch(/score|probability|%/i);
  });

  it("lists the saved recommendation separately from agreed next steps and coaching", () => {
    expect(labels(brief.sections[4])).toEqual([
      "Current blocker",
      "Objection · open",
    ]);
    expect(labels(brief.sections[5])).toEqual([
      "Recommended next move",
      "Next event",
      "Prospect agreed to",
      "You agreed to",
      "Still needs to become clear",
    ]);
    expect(brief.sections[5].facts[0]).toEqual({
      label: "Recommended next move",
      value: amitReport.overview!.final_assessment.next_focus,
      fact: "Inferred",
      basis: "call",
    });
    expect(JSON.stringify(brief.sections[5])).not.toContain(
      amitReport.overview!.next_call_focus!.behavior,
    );
    expect(brief.basedOn?.label).toContain("Discovery call");
  });

  it("works from saved facts alone when no analysed call can be read", () => {
    const alone = prospectBrief(syntheticProspect, []);
    expect(alone.basedOn).toBeNull();
    expect(alone.sections).toHaveLength(6);
    const now = alone.sections[0];
    expect(labels(now)).toEqual(["Name", "Company"]);
    expect(now.facts[1].fact).toBe("Contradiction");
    expect(now.unknown.map((item) => item.label)).toContain("Current blocker");
    expect(alone.sections[5].facts).toEqual([]);
  });
});

describe("latestAnalysedCall", () => {
  it("picks the newest call that has a finished Report", () => {
    const older = {
      ...amitCalls[0],
      submission_id: "a",
      created_at: "2026-10-01T00:00:00Z",
    };
    const newerNoReport = {
      ...amitCalls[0],
      submission_id: "b",
      created_at: "2026-10-10T00:00:00Z",
      has_report: false,
    };
    const newer = {
      ...amitCalls[0],
      submission_id: "c",
      created_at: "2026-10-05T00:00:00Z",
    };
    expect(
      latestAnalysedCall([older, newerNoReport, newer])?.submission_id,
    ).toBe("c");
    expect(latestAnalysedCall([newerNoReport])).toBeNull();
  });
});
