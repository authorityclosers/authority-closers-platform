import { describe, expect, it } from "vitest";

import fixture from "../../review-fixture/insights/sandbox.json";
import {
  DEFAULT_FILTERS,
  activeFilterCount,
  bucketLabel,
  duration,
  filtersFrom,
  parseCallPage,
  parseInsights,
  percent,
  queryOf,
  rupees,
} from "./insights-data";

describe("insights data", () => {
  it("parses the server's answer through every section", () => {
    const data = parseInsights(fixture.overview);
    expect(data.synthetic).toBe(true);
    expect(data.totals.calls).toBeGreaterThan(1000);
    expect(data.trend.length).toBeGreaterThan(3);
    expect(data.skills).toHaveLength(8);
    expect(data.people[0].skills).toHaveLength(8);
    expect(data.teams.length).toBeGreaterThan(1);
    expect(data.strongest[0].skills).toHaveLength(8);
    expect(data.facets.teams[0].name).not.toMatch(/TEAM$/);
    const page = parseCallPage(fixture.calls);
    expect(page.items[0].key).toMatch(/^syn-/);
  });

  it("never throws on a missing or odd answer", () => {
    for (const body of [null, 42, "x", [], { totals: "nope", trend: [null] }]) {
      const data = parseInsights(body);
      expect(data.totals.calls).toBe(0);
      expect(data.previous).toBeNull();
      expect(data.window.unit).toBe("month");
    }
    const odd = parseInsights({
      synthetic: "yes",
      trend: [{ at: "2026-09-01", calls: "many" }],
      calls: { strongest: [{ key: "a", skills: "SOO" }] },
    });
    expect(odd.synthetic).toBe(false);
    expect(odd.trend[0].calls).toBe(0);
    // A skills string that isn't eight states is dropped, never misread.
    expect(odd.strongest[0].skills).toBeNull();
    expect(parseCallPage(undefined)).toEqual({
      synthetic: false,
      total: 0,
      nextOffset: null,
      items: [],
    });
  });

  it("keeps filters in the address and drops unknown values", () => {
    const filters = filtersFrom({
      range: "12m",
      person: "p-1",
      outcome: "won",
      team: ["t-1", "t-2"],
    });
    expect(filters).toEqual({
      range: "12m",
      person: "p-1",
      team: "t-1",
      outcome: "won",
      language: null,
    });
    expect(queryOf(filters)).toBe("?range=12m&person=p-1&team=t-1&outcome=won");
    expect(queryOf(DEFAULT_FILTERS)).toBe("");
    expect(queryOf(DEFAULT_FILTERS, { offset: "50" })).toBe("?offset=50");
    expect(filtersFrom({ range: "7y", outcome: "maybe" })).toEqual(
      DEFAULT_FILTERS,
    );
    expect(activeFilterCount(filters)).toBe(3);
  });

  it("formats figures for people, not machines", () => {
    expect(percent(0.7568)).toBe("76%");
    expect(percent(null)).toBe("—");
    expect(rupees(168_309_200)).toBe("₹16.8 Cr");
    expect(rupees(360_000)).toBe("₹3.6 L");
    expect(rupees(null)).toBeNull();
    expect(duration(327_140)).toBe("5:27");
    expect(duration(4_000_000)).toBe("1 h 6 min");
    expect(bucketLabel("2026-09-01", "month")).toBe("Sept 26");
    expect(bucketLabel("2026-09-07", "week")).toBe("7 Sept");
  });
});
