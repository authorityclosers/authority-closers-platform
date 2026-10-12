import { describe, expect, it } from "vitest";

import * as copy from "./report-copy";
import {
  BIG_PICTURE,
  CALL_FLOW,
  DEAL,
  GUEST,
  PILLAR_COPY,
  PILLAR_IDS,
  WORKED_DIDNT,
  partHeading,
  pillarHeading,
  prospectAgreed,
  viewAllMoments,
} from "./report-copy";

/** Every fixed string in the module, however deeply it sits. */
function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  if (value && typeof value === "object")
    return Object.values(value).flatMap(strings);
  return [];
}
const ALL = strings(
  Object.fromEntries(
    Object.entries(copy).filter(([, value]) => typeof value !== "function"),
  ),
).filter((text) => text !== copy.REPORT_COPY_VERSION);

describe("report copy", () => {
  it("names the six pillars exactly as Dipak's document, in its order", () => {
    expect(PILLAR_IDS.map(pillarHeading)).toEqual([
      "1. The Big Picture",
      "2. How the Call Played Out",
      "3. What Worked — & What Didn't",
      "4. Moments That Mattered",
      "5. Your Skills on This Call",
      "6. Where the Deal Stands",
    ]);
    expect(PILLAR_IDS.map((id) => PILLAR_COPY[id].subtitle)).toEqual([
      "Understand the call in seconds.",
      "See how the conversation moved.",
      "See what helped the conversation and what made it harder.",
      "Replay the moments that changed the conversation.",
      "See how your sales skills showed up in this conversation.",
      "Know exactly what happens next.",
    ]);
  });

  it("numbers each pillar's parts like the document", () => {
    expect(Object.values(BIG_PICTURE).flatMap(strings)).toEqual(
      expect.arrayContaining(["1.1", "1.6"]),
    );
    expect(partHeading(BIG_PICTURE.outcome)).toBe("1.1 Call Outcome");
    expect(partHeading(BIG_PICTURE.nextStep)).toBe("1.6 Next Agreed Step");
    expect(partHeading(CALL_FLOW.beforeAfter)).toBe(
      "2.4 Before / Switch / After",
    );
    expect(partHeading(WORKED_DIDNT.didnt)).toBe("3.2 What Didn't");
    expect(partHeading(DEAL.action)).toBe("6.9 Recommended Deal Action");
    const deal = [
      DEAL.status,
      DEAL.position,
      DEAL.blocker,
      DEAL.prospectCommitment,
      DEAL.sellerCommitment,
      DEAL.nextEvent,
      DEAL.quality,
      DEAL.unclear,
      DEAL.action,
    ].map((part) => part.number);
    expect(deal).toEqual(
      Array.from({ length: 9 }, (_, index) => `6.${index + 1}`),
    );
  });

  it("speaks plain sales language: no internal or analyst words", () => {
    const banned =
      /\b(C\d|pillar|inferred|interpretation|hypothesis|insufficient|establish(ed|es)?|supplied|evidence status|projection|revision|payload|schema|model|dimension|null|undefined|N\/A)\b/i;
    expect(ALL.filter((text) => banned.test(text))).toEqual([]);
  });

  it("keeps lines short and tidy", () => {
    for (const text of ALL) {
      expect(text, text).toBe(text.trim());
      expect(text, text).not.toMatch(/ {2}/);
      expect(text.length, text).toBeLessThanOrEqual(110);
    }
  });

  it("fills in names and counts", () => {
    expect(prospectAgreed("Amit Sharma")).toBe("Amit Sharma agreed to");
    expect(prospectAgreed("  ")).toBe("Prospect agreed to");
    expect(viewAllMoments(8)).toBe("View all 8 moments");
    expect(copy.prospectInsights(1)).toBe("1 prospect insight captured");
    expect(copy.changedAt("11:18")).toBe("The call changed here · 11:18");
    expect(copy.followUpDate("2026-10-16")).toBe("Follow-up: Friday, 16 Oct");
    expect(copy.followUpDate("soon")).toBe("Follow-up: soon");
    expect(copy.backTo("Moments That Mattered")).toBe(
      "Back to Moments That Mattered",
    );
  });

  it("names the outcome buttons exactly like the status they set", () => {
    for (const status of Object.values(copy.OUTCOME_CHOICES))
      expect(copy.OUTCOME_STATUSES).toContain(status);
    expect(
      copy.recordedOutcome({ outcome: "lost", lost_reason: " Price " }),
    ).toEqual({ status: "Lost", note: "Price" });
    expect(
      copy.recordedOutcome({
        outcome: "follow_up",
        follow_up_on: "2026-10-16",
      }),
    ).toEqual({ status: "Follow-up Set", note: "Follow-up: Friday, 16 Oct" });
    expect(copy.recordedOutcome({ outcome: "no_decision" })).toEqual({
      status: "Decision Pending",
      note: null,
    });
  });

  it("keeps guest wording and counts singular and plural saved items", () => {
    expect(GUEST.more(1, ["moment", "moments"])).toBe(
      "1 more moment is saved for your account.",
    );
    expect(GUEST.more(2, ["moment", "moments"])).toBe(
      "2 more moments are saved for your account.",
    );
    expect(GUEST.unlock).toBe("Unlock with a free account");
    expect(GUEST.fullReport).toBe("Sign in to see the full report");
  });
});
