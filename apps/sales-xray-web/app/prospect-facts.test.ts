import { describe, expect, it } from "vitest";

import {
  factsFromCallData,
  factsFromCallReview,
  factsFromReport,
  factsFromSavedProspect,
  prospectFacts,
} from "./prospect-facts";
import { amitTranscript } from "./review-fixture/report/story/amit-call";
import { AMIT_PROFILE } from "./review-fixture/prospects/amit-profile";
import { syntheticProspect } from "./review-fixture/prospects/synthetic-prospect";

const [s1] = amitTranscript.segments;

describe("prospect facts read model", () => {
  const call = factsFromCallReview(
    { prospect_profile: AMIT_PROFILE },
    amitTranscript,
  );

  it("takes call facts only with evidence from this transcript", () => {
    const facts = prospectFacts(call);
    expect(facts.name).toMatchObject({ value: "Amit", basis: "call" });
    expect(facts.name.evidence[0].start_ms).toBe(s1.start_ms);
    // No evidence: Unknown, never shown as a fact.
    expect(facts.industry.value).toBeNull();
    expect(facts.personal.value).toBeNull();
    expect(facts.insights.map((item) => item.text)).toEqual([
      "Considering a ₹2 lakh investment.",
    ]);
    expect(facts.quality).toEqual({
      score: 8,
      reason: "Clear need and budget.",
    });
    expect(facts.fit.value).toBe("strong");
    expect(facts.followUp.when).toBe("Friday 4 PM");
    expect(facts.reviewed).toBe(true);
    // Saved-prospect keys travel with the fact so a person can confirm it.
    expect(facts.company.editKey).toBe("business");
  });

  it("lets a saved prospect win and fills gaps from the report", () => {
    const facts = prospectFacts(
      factsFromSavedProspect(syntheticProspect, amitTranscript),
      call,
      factsFromReport({
        deal: "Decision Pending",
        nextAction: "Ask what the partner thought.",
        blocker: null,
        nextStep: null,
      }),
    );
    const saved = syntheticProspect.profile_fields?.business;
    if (saved?.state === "known") expect(facts.company.basis).not.toBe(null);
    expect(facts.deal).toBe("Decision Pending");
    expect(facts.nextAction).toMatchObject({
      value: "Ask what the partner thought.",
      basis: "ai_read",
    });
  });

  it("gives nothing from an older or malformed block", () => {
    expect(
      factsFromCallReview(
        { prospect_profile: { version: "x" } },
        amitTranscript,
      ),
    ).toEqual({});
    const empty = prospectFacts(factsFromCallReview(null, amitTranscript));
    expect(empty.name.value).toBeNull();
    expect(empty.reviewed).toBe(false);
    expect(empty.quality.score).toBeNull();
  });

  it("rejects a quality score outside 1-10", () => {
    const facts = prospectFacts(
      factsFromCallReview(
        {
          prospect_profile: {
            ...AMIT_PROFILE,
            quality: { score: 11, reason: "x" },
          },
        },
        amitTranscript,
      ),
    );
    expect(facts.quality).toEqual({ score: null, reason: null });
  });
});

describe("call data engine source (prospect-facts/1)", () => {
  const [first, second] = amitTranscript.segments;
  const fact = (type: string, display: string, extra: object = {}) => ({
    object_id: type,
    type,
    display,
    value: {},
    basis: "observed",
    status: "kept",
    ai_read: false,
    evidence: [
      {
        segment_id: first.id,
        quote: first.text.slice(0, 20),
        start_ms: first.start_ms,
        end_ms: first.end_ms,
        speaker: "spk",
      },
    ],
    ...extra,
  });
  const payload = {
    schema: "prospect-facts/1",
    facts: [
      fact("company.name", "XYZ Digital"),
      fact("company.revenue", "₹4–5 lakh a month", { basis: "edited" }),
      fact("need.goal", "Reach ₹10 lakh a month", { basis: "inferred" }),
      fact("commitment.follow_up", "Friday 4 PM", {
        value: { date: "2026-10-23", time: "16:00", purpose: "Partner call" },
      }),
      fact("money.investment_discussed", "Considering ₹2 lakh"),
      fact("friction.question", "Will the team close alone?"),
      fact("conversation.segment", "ignored"),
      fact("company.industry", "", {}),
    ],
  };

  it("maps engine facts by type with their basis and evidence", () => {
    const source = factsFromCallData(payload, amitTranscript);
    expect(source.company).toMatchObject({
      value: "XYZ Digital",
      basis: "call",
    });
    expect(source.company?.evidence[0].start_ms).toBe(first.start_ms);
    expect(source.revenue?.basis).toBe("person");
    expect(source.wants?.basis).toBe("ai_read");
    expect(source.industry).toBeUndefined();
    expect(source.followUp).toMatchObject({
      when: "Fri 23 Oct · 4:00 pm",
      about: "Partner call",
    });
    expect(source.insights?.map((item) => item.kind)).toEqual([
      "investment",
      "question",
    ]);
  });

  it("sits after the saved prospect and before the call review", () => {
    const facts = prospectFacts(
      {},
      factsFromCallData(payload, amitTranscript),
      factsFromCallReview({ prospect_profile: AMIT_PROFILE }, amitTranscript),
    );
    expect(facts.company.value).toBe("XYZ Digital");
    // The review still fills what the engine has not read.
    expect(facts.name.value).toBe("Amit");
    expect(second).toBeDefined();
  });

  it("gives nothing for an older server or another schema", () => {
    expect(factsFromCallData(null, amitTranscript)).toEqual({});
    expect(
      factsFromCallData({ schema: "x", facts: [] }, amitTranscript),
    ).toEqual({});
  });
});
