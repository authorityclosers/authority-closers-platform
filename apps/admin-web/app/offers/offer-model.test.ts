import { describe, expect, it } from "vitest";

import { CATALOGUE } from "../catalogue/catalogue-data";
import { fixtureOffer } from "./offer-fixture-data";
import {
  TEMPLATES,
  blankOffer,
  fillPrompt,
  fromTemplate,
  mergeStudios,
  normalizeStudio,
  onePagerMarkdown,
  positioningStatement,
  stackTotal,
  suggestedName,
  valueMultiple,
  valueScore,
  valueVerdict,
  type Offer,
} from "./offer-model";

const NOW = "2026-10-23T00:00:00Z";

describe("value equation", () => {
  it("is (dream × likelihood) ÷ (time × effort), each clamped to 1..10", () => {
    const value = (d: number, l: number, t: number, e: number) => ({
      dream: { text: "", score: d },
      likelihood: { text: "", score: l },
      time: { text: "", score: t },
      effort: { text: "", score: e },
    });
    expect(valueScore(value(9, 8, 2, 3))).toBe(12);
    expect(valueScore(value(5, 5, 5, 5))).toBe(1);
    expect(valueScore(value(40, 0, 0, 1))).toBe(10);
    expect(valueVerdict(12).label).toBe("Grand slam");
    expect(valueVerdict(3).label).toBe("Strong");
    expect(valueVerdict(1).label).toBe("Fair");
    expect(valueVerdict(0.4).label).toBe("Weak");
  });
});

describe("value stack and tiers", () => {
  it("adds item and bonus worth, per tier when it includes only some", () => {
    const offer = fixtureOffer();
    const items = offer.stack.reduce((sum, s) => sum + s.worth, 0);
    expect(stackTotal(offer)).toBe(items + 15000);
    const starter = offer.tiers[0]!;
    const starterItems = offer.stack
      .slice(0, 5)
      .reduce((sum, s) => sum + s.worth, 0);
    expect(stackTotal(offer, starter.featureIds)).toBe(starterItems + 15000);
    expect(valueMultiple(offer, starter)).toBeCloseTo(
      (starterItems + 15000) / 49990,
    );
    expect(valueMultiple(offer, { ...starter, monthly: 0, yearly: 0 })).toBe(
      null,
    );
  });
});

describe("templates", () => {
  it("only pick features the catalogue has, and never set prices", () => {
    const known = new Set(CATALOGUE.features.map((f) => f.id));
    for (const template of TEMPLATES) {
      for (const id of template.features) expect(known.has(id), id).toBe(true);
      const offer = fromTemplate(template.id, CATALOGUE, NOW);
      expect(offer.stack.every((s) => s.worth === 0)).toBe(true);
      expect(offer.tiers).toEqual([]);
    }
  });
});

describe("import", () => {
  it("rebuilds offers from untrusted JSON and drops what doesn't fit", () => {
    const studio = normalizeStudio({
      offers: [
        {
          id: "a",
          name: "x".repeat(500),
          stack: [{ featureId: "the-report", worth: -5 }, { worth: 3 }],
          value: { dream: { text: 1, score: 99 } },
          guarantee: { kind: "forever" },
          tiers: [{ monthly: "lots", featureIds: ["the-report", 7] }],
          ideas: [{ text: "go", column: "sideways", votes: 1e9 }],
          evil: "<script>",
        },
        { id: "a", name: "Same id" },
      ],
      activeId: "nope",
    });
    const [first, second] = studio.offers as [Offer, Offer];
    expect(first.name).toHaveLength(200);
    expect(first.stack).toEqual([
      { featureId: "the-report", worth: 0, label: "" },
    ]);
    expect(first.value.dream).toEqual({ text: "", score: 5 });
    expect(first.guarantee.kind).toBe("none");
    expect(first.tiers[0]?.monthly).toBe(0);
    expect(first.tiers[0]?.featureIds).toEqual(["the-report"]);
    expect(first.ideas[0]).toMatchObject({ column: "idea", votes: 99 });
    expect("evil" in first).toBe(false);
    expect(second.id).not.toBe("a");
    expect(studio.activeId).toBe("a");
  });

  it("takes a single exported offer, and refuses a file with none", () => {
    const single = normalizeStudio({ ...blankOffer("One", NOW), id: "solo" });
    expect(single.offers.map((o) => o.id)).toEqual(["solo"]);
    expect(() => normalizeStudio({ hello: 1 })).toThrow(/no offers/);
    expect(() => normalizeStudio(null)).toThrow();
  });

  it("merges imports as copies when an id is already here", () => {
    const here = normalizeStudio({ offers: [{ id: "a", name: "Here" }] });
    const merged = mergeStudios(here, here);
    expect(merged.offers).toHaveLength(2);
    expect(merged.offers[1]?.id).not.toBe("a");
    expect(merged.offers[1]?.name).toBe("Here (imported)");
    expect(merged.activeId).toBe(merged.offers[1]?.id);
  });
});

describe("words", () => {
  it("builds the MAGIC name, positioning statement and prompts", () => {
    const offer = fixtureOffer();
    expect(suggestedName(offer.naming)).toBe(
      "Founding Sales Team Close-More 30-Day System",
    );
    expect(positioningStatement(offer.positioning, "X")).toBe(
      "For owners of small sales teams who can't hear what happens on their calls, X is a sales CRM that listens to every call that turns each call into coaching and the next step. Unlike dialers that only count calls, it knows what was said and what to do about it.",
    );
    expect(positioningStatement(blankOffer().positioning, "X")).toBe("");
    expect(fillPrompt("Help {avatar} with {goal}", offer)).toBe(
      "Help Sales Team with Close-More",
    );
  });

  it("exports a one-pager with prices only when asked", () => {
    const offer = fixtureOffer();
    const withPrices = onePagerMarkdown(offer, { prices: true });
    const without = onePagerMarkdown(offer, { prices: false });
    expect(withPrices).toContain("# Founding Sales Team Close-More System");
    expect(withPrices).toContain("## Plans");
    expect(withPrices).toContain("₹4,999/month");
    expect(without).not.toMatch(/₹/);
    expect(without).not.toContain("## Plans");
    expect(without).toContain("## Our guarantee");
  });
});
