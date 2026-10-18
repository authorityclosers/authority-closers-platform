import { describe, expect, it } from "vitest";

import {
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
