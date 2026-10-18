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

describe("prospect signals from this call's Report (owner 18 Oct)", () => {
  const [first, second] = amitTranscript.segments;
  const withSignals = {
    ...latest,
    report: {
      ...amitReport,
      structure: {
        ...(amitReport.structure as object),
        prospect_signals: {
          version: "prospect-signals/1",
          qualification: {
            need: {
              state: "confirmed",
              evidence: [
                { segment_id: first.id, quote: first.text.slice(0, 20) },
              ],
            },
            budget: {
              state: "concern",
              evidence: [
                { segment_id: second.id, quote: second.text.slice(0, 20) },
              ],
            },
            timeline: { state: "unknown", evidence: [] },
          },
          pains: [
            {
              text: "Sales depend on the founder",
              intensity: "high",
              evidence: [],
            },
            { text: "Leads go cold", intensity: "med", evidence: [] },
          ],
          objections: [
            {
              text: "The fee feels high",
              kind: "price_concern",
              status: "open",
              evidence: [
                { segment_id: second.id, quote: second.text.slice(0, 20) },
              ],
            },
          ],
          facts: [],
        },
      },
    },
  };

  it("fills Can & Will They Buy with Confirmed and Concern, quoting the call", () => {
    const brief = prospectBrief(syntheticProspect, [], withSignals);
    const buy = brief.sections[2];
    const fact = (label: string) =>
      buy.facts.find((item) => item.label === label);
    expect(fact("Need")).toMatchObject({
      value: "Confirmed",
      fact: "Observed",
    });
    expect(fact("Need")?.source?.start_ms).toBe(first.start_ms);
    // A saved budget wins over what this call suggests.
    expect(fact("Budget discussed")?.value).not.toBe("Concern");
    const unsaved = prospectBrief(
      { ...syntheticProspect, profile_fields: {} },
      [],
      withSignals,
    ).sections[2].facts.find((item) => item.label === "Budget discussed");
    expect(unsaved).toMatchObject({ value: "Concern", fact: "Inferred" });
    // Unknown is named once in the still-unknown line, never as a fact.
    expect(fact("Timing")).toBeUndefined();
    const holding = brief.sections[4];
    expect(holding.facts.map((item) => item.label)).toContain(
      "Objection · open",
    );
  });

  it("reads nothing from an older or malformed block", () => {
    const old = prospectBrief(syntheticProspect, [], {
      ...latest,
      report: {
        ...amitReport,
        structure: { prospect_signals: { version: "x" } },
      },
    });
    expect(old.sections[2].facts.map((item) => item.value)).not.toContain(
      "Confirmed",
    );
  });
});
